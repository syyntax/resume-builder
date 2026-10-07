"""Applications: create (start generation), progress events, results, exports (DESIGN.md §4.6, §9)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import current_user, get_settings
from app.auth.sessions import AuthContext
from app.config import Settings
from app.db.engine import get_db
from app.db.models import AiCall, Application, Document, JobPosting, MasterResume, MasterResumeVersion
from app.db.types import utcnow
from app.errors import ApiError
from app.keys import service as keys
from app.masters.repository import MasterRepository
from app.models.api import ApplicationCreateIn, ApplicationDetailOut, ApplicationOut, JobRef, MasterRef
from app.pipeline import usage
from app.pipeline.export import filename, to_markdown
from app.pipeline.run import ACTIVE, run_application
from app.services import settings_store

router = APIRouter(prefix="/api/applications", tags=["applications"])
KEEPALIVE_SECONDS = 15.0


class ApplicationRepository:
    """Owner-scoped access to applications and their documents."""

    def __init__(self, db: AsyncSession, owner_id: str) -> None:
        self.db, self.owner_id = db, owner_id

    def _base(self):  # noqa: ANN202
        return (
            select(Application, JobPosting, MasterResumeVersion, MasterResume)
            .join(JobPosting, JobPosting.id == Application.job_id)
            .join(MasterResumeVersion, MasterResumeVersion.id == Application.master_version_id)
            .outerjoin(MasterResume, MasterResume.id == MasterResumeVersion.master_id)
            .where(Application.owner_id == self.owner_id)
        )

    async def list(self) -> list[Any]:
        return list((await self.db.execute(self._base().order_by(Application.created_at.desc()))).all())

    async def get(self, application_id: str) -> Any:
        row = (await self.db.execute(self._base().where(Application.id == application_id))).first()
        if row is None:
            raise ApiError(404, "Application not found.")
        return row

    async def resume(self, application_id: str) -> Document | None:
        return (await self.db.execute(select(Document).where(
            Document.application_id == application_id, Document.kind == "resume", Document.owner_id == self.owner_id,
        ))).scalar_one_or_none()

    async def cost(self, application_id: str) -> float:
        stmt = select(func.coalesce(func.sum(AiCall.est_cost_usd), 0.0)).where(
            AiCall.application_id == application_id, AiCall.owner_id == self.owner_id)
        return float((await self.db.execute(stmt)).scalar_one())


def get_repo(ctx: AuthContext = Depends(current_user), db: AsyncSession = Depends(get_db)) -> ApplicationRepository:
    return ApplicationRepository(db, ctx.user.id)


def _out(row: Any) -> dict[str, Any]:
    application, job, version, master = row
    return {
        "id": application.id, "status": application.status, "error": application.error, "model": application.model,
        "options": application.options, "coverage_score": application.coverage_score,
        "created_at": application.created_at, "updated_at": application.updated_at,
        "job": JobRef(id=job.id, company=job.company, title=job.title, url=job.url),
        "master": MasterRef(id=master.id if master else None, label=master.label if master else None,
                            version_id=version.id, version_number=version.version_number),
    }


def _start(request: Request, owner_id: str, application_id: str) -> None:
    app = request.app
    app.state.jobs.submit(owner_id, lambda: run_application(app, application_id))


# ---- create & list -----------------------------------------------------------------------------------


@router.post("", response_model=ApplicationOut, status_code=202)
async def create_application(body: ApplicationCreateIn, request: Request, ctx: AuthContext = Depends(current_user),
                             db: AsyncSession = Depends(get_db), settings: Settings = Depends(get_settings),
                             repo: ApplicationRepository = Depends(get_repo)) -> ApplicationOut:
    masters = MasterRepository(db, ctx.user.id)
    master = await masters.get(body.master_id)
    version = await masters.current_version(master) if master else None
    if master is None or version is None:
        raise ApiError(404, "Master résumé not found.")
    key = await keys.resolve(db, ctx.user, settings)  # fails early with "add your key" instead of mid-job
    model = (await settings_store.model_policy(db)).choose(ctx.user.preferred_model)
    await usage.ensure_within_cap(db, ctx.user, key.source, settings, usage.estimate_job_cost(model, settings))

    job = JobPosting(owner_id=ctx.user.id, raw_text=body.job.text, company=body.job.company or None,
                     title=body.job.title or None, url=body.job.url or None, created_at=utcnow())
    db.add(job)
    await db.flush()
    now = utcnow()
    application = Application(owner_id=ctx.user.id, master_version_id=version.id, job_id=job.id, status="queued",
                              options=body.options.model_dump(by_alias=True, exclude_none=True), model=model,
                              template="meridian", theme={}, created_at=now, updated_at=now)
    db.add(application)
    await db.commit()
    _start(request, ctx.user.id, application.id)
    return ApplicationOut(**_out(await repo.get(application.id)))


@router.get("", response_model=list[ApplicationOut])
async def list_applications(repo: ApplicationRepository = Depends(get_repo)) -> list[ApplicationOut]:
    return [ApplicationOut(**_out(row)) for row in await repo.list()]


@router.get("/{application_id}", response_model=ApplicationDetailOut)
async def get_application(application_id: str, repo: ApplicationRepository = Depends(get_repo)) -> ApplicationDetailOut:
    row = await repo.get(application_id)
    document = await repo.resume(application_id)
    return ApplicationDetailOut(**_out(row), posting=row[1].raw_text, analysis=row[1].analysis,
                                resume=document.current if document else None,
                                cost_usd=round(await repo.cost(application_id), 4))


@router.post("/{application_id}/retry", response_model=ApplicationOut, status_code=202)
async def retry_application(application_id: str, request: Request, ctx: AuthContext = Depends(current_user),
                            settings: Settings = Depends(get_settings),
                            repo: ApplicationRepository = Depends(get_repo)) -> ApplicationOut:
    application = (await repo.get(application_id))[0]
    if application.status != "failed":
        raise ApiError(409, "Only failed applications can be retried.")
    key = await keys.resolve(repo.db, ctx.user, settings)
    await usage.ensure_within_cap(repo.db, ctx.user, key.source, settings,
                                  usage.estimate_job_cost(application.model, settings))
    application.status, application.error, application.updated_at = "queued", None, utcnow()
    await repo.db.commit()
    _start(request, ctx.user.id, application.id)
    return ApplicationOut(**_out(await repo.get(application_id)))


@router.delete("/{application_id}", status_code=204)
async def delete_application(application_id: str, repo: ApplicationRepository = Depends(get_repo)) -> Response:
    application = (await repo.get(application_id))[0]
    if application.status in ACTIVE:
        raise ApiError(409, "This application is still generating. Wait for it to finish, then delete it.")
    await repo.db.delete(application)  # usage records stay (application_id is cleared) so caps still count them
    await repo.db.commit()
    return Response(status_code=204)


# ---- progress events (SSE) -------------------------------------------------------------------------------


def _sse(event: dict[str, Any]) -> str:
    return f"event: {event['type']}\ndata: {json.dumps(event)}\n\n"


@router.get("/{application_id}/events")
async def application_events(application_id: str, request: Request,
                             repo: ApplicationRepository = Depends(get_repo)) -> StreamingResponse:
    await repo.get(application_id)  # ownership check
    bus = request.app.state.events
    queue = bus.subscribe(application_id)

    async def stream() -> AsyncIterator[str]:
        try:
            # Read the current state after subscribing, so nothing that happens in between is missed.
            async with request.app.state.sessionmaker() as db:
                current = await db.get(Application, application_id)
            if current is None:
                return
            yield _sse({"type": "status", "status": current.status})
            if current.status == "done":
                yield _sse({"type": "done"})
                return
            if current.status == "failed":
                yield _sse({"type": "error", **(current.error or {})})
                return
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=KEEPALIVE_SECONDS)
                except TimeoutError:
                    if await request.is_disconnected():
                        return
                    yield ": keepalive\n\n"
                    continue
                yield _sse(event)
                if event["type"] in ("done", "error"):
                    return
        finally:
            bus.unsubscribe(application_id, queue)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


# ---- exports -----------------------------------------------------------------------------------------------


@router.get("/{application_id}/export")
async def export_application(application_id: str, format: str = Query("md", pattern="^(md|json)$"),
                             repo: ApplicationRepository = Depends(get_repo)) -> Response:
    row = await repo.get(application_id)
    document = await repo.resume(application_id)
    if document is None or document.current is None:
        raise ApiError(409, "This application has no résumé yet.")
    resume = document.current
    job = {"company": row[1].company, "title": row[1].title}
    if format == "json":
        body, media = json.dumps(resume, indent=2, ensure_ascii=False) + "\n", "application/json"
    else:
        body, media = to_markdown(resume), "text/markdown; charset=utf-8"
    name = filename(resume, job, "Resume", format)
    return Response(body, media_type=media, headers={"Content-Disposition": f'attachment; filename="{name}"'})
