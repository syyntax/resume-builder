"""Applications: create (start generation), progress events, results, exports (DESIGN.md §4.6, §9)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any, Literal

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
from app.models.api import (
    ApplicationCreateIn,
    ApplicationDetailOut,
    ApplicationOut,
    DesignIn,
    DesignOut,
    JobRef,
    MasterRef,
)
from app.pipeline import usage
from app.pipeline.export import filename, markdown_to_text, to_markdown
from app.pipeline.letter import to_markdown as letter_markdown
from app.pipeline.run import ACTIVE, Phase, run_application
from app.render.service import (
    letter_metadata,
    render_letter,
    render_packet,
    render_resume,
    resume_metadata,
    stored_design,
)
from app.render.theme import TEMPLATES
from app.render.word import build_letter_docx, build_resume_docx
from app.services import defaults, settings_store

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

    async def document(self, application_id: str, kind: str) -> Document | None:
        return (await self.db.execute(select(Document).where(
            Document.application_id == application_id, Document.kind == kind, Document.owner_id == self.owner_id,
        ))).scalar_one_or_none()

    async def resume(self, application_id: str) -> Document | None:
        return await self.document(application_id, "resume")

    async def letter(self, application_id: str) -> Document | None:
        return await self.document(application_id, "cover_letter")

    async def cost(self, application_id: str) -> float:
        stmt = select(func.coalesce(func.sum(AiCall.est_cost_usd), 0.0)).where(
            AiCall.application_id == application_id, AiCall.owner_id == self.owner_id)
        return float((await self.db.execute(stmt)).scalar_one())


def get_repo(ctx: AuthContext = Depends(current_user), db: AsyncSession = Depends(get_db)) -> ApplicationRepository:
    return ApplicationRepository(db, ctx.user.id)


def _out(row: Any) -> dict[str, Any]:
    application, job, version, master = row
    template, theme = stored_design(application.template, application.theme)
    return {
        "template": template, "theme": theme,
        "id": application.id, "status": application.status, "error": application.error, "model": application.model,
        "options": application.options, "coverage_score": application.coverage_score,
        "created_at": application.created_at, "updated_at": application.updated_at,
        "job": JobRef(id=job.id, company=job.company, title=job.title, url=job.url),
        "master": MasterRef(id=master.id if master else None, label=master.label if master else None,
                            version_id=version.id, version_number=version.version_number),
    }


def start(request: Request, owner_id: str, application_id: str, phase: Phase = "full") -> None:
    app = request.app
    app.state.jobs.submit(owner_id, lambda: run_application(app, application_id, phase))


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
    options = {**body.options.model_dump(by_alias=True, exclude_none=True),
               "coverLetter": body.cover_letter.model_dump(by_alias=True)}
    design = await defaults.design_for(db, ctx.user)
    application = Application(owner_id=ctx.user.id, master_version_id=version.id, job_id=job.id, status="queued",
                              options=options, model=model, template=design.template,
                              theme=design.theme.model_dump(mode="json", by_alias=True), created_at=now,
                              updated_at=now)
    db.add(application)
    await db.commit()
    start(request, ctx.user.id, application.id)
    return ApplicationOut(**_out(await repo.get(application.id)))


@router.get("", response_model=list[ApplicationOut])
async def list_applications(repo: ApplicationRepository = Depends(get_repo)) -> list[ApplicationOut]:
    return [ApplicationOut(**_out(row)) for row in await repo.list()]


@router.get("/{application_id}", response_model=ApplicationDetailOut)
async def get_application(application_id: str, repo: ApplicationRepository = Depends(get_repo)) -> ApplicationDetailOut:
    row = await repo.get(application_id)
    document = await repo.resume(application_id)
    letter = await repo.letter(application_id)
    return ApplicationDetailOut(
        **_out(row), posting=row[1].raw_text, analysis=row[1].analysis, analysis_edited=row[1].analysis_edited,
        resume=document.current if document else None,
        cover_letter=letter.current if letter else None,
        cover_letter_status=letter.status if letter else "none",  # type: ignore[arg-type]
        cover_letter_error=letter.error if letter else None,
        cost_usd=round(await repo.cost(application_id), 4),
    )


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
    # A failure after the analysis doesn't need it again (and the candidate may have edited it).
    start(request, ctx.user.id, application.id, "tailor" if (await repo.get(application_id))[1].analysis else "full")
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
            if current.status == "review":
                yield _sse({"type": "review"})
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
                if event["type"] in ("done", "error", "review"):
                    return
        finally:
            bus.unsubscribe(application_id, queue)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


# ---- exports -----------------------------------------------------------------------------------------------


async def _resume_or_409(repo: ApplicationRepository, application_id: str) -> tuple[Any, dict[str, Any]]:
    row = await repo.get(application_id)
    document = await repo.resume(application_id)
    if document is None or document.current is None:
        raise ApiError(409, "This application has no résumé yet.")
    return row, document.current


async def _letter_or_409(repo: ApplicationRepository, application_id: str) -> dict[str, Any]:
    document = await repo.letter(application_id)
    if document is None or document.status != "ready" or not document.current:
        raise ApiError(409, "This application has no cover letter yet.")
    return document.current


Doc = Literal["resume", "cover-letter", "packet"]
DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


async def _render_doc(request: Request, repo: ApplicationRepository, application_id: str, doc: Doc) -> Any:
    row, resume = await _resume_or_409(repo, application_id)
    application, job = row[0], {"company": row[1].company, "title": row[1].title}
    if doc == "resume":
        return await render_resume(request.app, resume, job, application.template, application.theme)
    letter = await _letter_or_409(repo, application_id)
    if doc == "cover-letter":
        return await render_letter(request.app, letter, job, application.template, application.theme)
    return await render_packet(request.app, letter, resume, job, application.template, application.theme)


@router.get("/{application_id}/preview.pdf")
async def preview_pdf(application_id: str, request: Request, doc: Doc = "resume",
                      repo: ApplicationRepository = Depends(get_repo)) -> Response:
    """A document exactly as it exports (TPL-1). ``X-Page-Count`` gives the number of pages."""
    pdf = await _render_doc(request, repo, application_id, doc)
    return Response(pdf.data, media_type="application/pdf", headers={
        "X-Page-Count": str(pdf.pages), "Content-Disposition": "inline", "Cache-Control": "no-store"})


@router.put("/{application_id}/design", response_model=DesignOut)
async def save_design(application_id: str, body: DesignIn,
                      repo: ApplicationRepository = Depends(get_repo)) -> DesignOut:
    """Choose the template and theme (accent, fonts, density, paper, margins, date format, contact icons)."""
    template = TEMPLATES.get(body.template)
    if template is None or not template.available:
        raise ApiError(422, f"There's no {body.template} template.",
                       errors=[{"field": "template", "message": "unknown template"}])
    application = (await repo.get(application_id))[0]
    theme = body.theme.model_dump(mode="json", by_alias=True)
    application.template, application.theme, application.updated_at = body.template, theme, utcnow()
    document = await repo.resume(application_id)
    if document is not None and document.current is not None:  # keep the JSON export's metadata in step
        meta = {**(document.current.get("meta") or {}), "template": body.template, "theme": theme}
        document.current = {**document.current, "meta": meta}
    await repo.db.commit()
    return DesignOut(template=body.template, theme=body.theme)


@router.get("/{application_id}/export")
async def export_application(request: Request, application_id: str, doc: Doc = "resume",
                             format: str = Query("md", pattern="^(md|json|pdf|docx|txt)$"),
                             ctx: AuthContext = Depends(current_user),
                             repo: ApplicationRepository = Depends(get_repo)) -> Response:
    """Download the résumé or the cover letter as PDF, Word, Markdown, plain text or JSON, or the packet (the
    cover letter then the résumé, PDF only)."""
    row, resume = await _resume_or_409(repo, application_id)
    job = {"company": row[1].company, "title": row[1].title}
    kind = {"resume": "Resume", "cover-letter": "Cover-Letter", "packet": "Application"}[doc]
    name = filename(resume, job, kind, format, defaults.preferences(ctx.user).file_name)
    if format == "pdf":
        pdf = await _render_doc(request, repo, application_id, doc)
        return Response(pdf.data, media_type="application/pdf",
                        headers={"Content-Disposition": f'attachment; filename="{name}"'})
    if doc == "packet":
        raise ApiError(422, "The application packet is available as PDF only.")
    content = resume if doc == "resume" else await _letter_or_409(repo, application_id)
    headers = {"Content-Disposition": f'attachment; filename="{name}"'}
    if format == "docx":
        template, theme = stored_design(row[0].template, row[0].theme)
        if doc == "resume":
            data = await asyncio.to_thread(build_resume_docx, content, template, theme, resume_metadata(content, job))
        else:
            data = await asyncio.to_thread(build_letter_docx, content, template, theme, letter_metadata(content, job))
        return Response(data, media_type=DOCX_TYPE, headers=headers)
    if format == "json":
        body, media = json.dumps(content, indent=2, ensure_ascii=False) + "\n", "application/json"
    else:
        body = to_markdown(content) if doc == "resume" else letter_markdown(content)
        media = "text/markdown; charset=utf-8"
        if format == "txt":
            body, media = markdown_to_text(body), "text/plain; charset=utf-8"
    return Response(body, media_type=media, headers=headers)
