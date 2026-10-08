"""Résumé import: upload or paste, progress, review, accept as a new master (DESIGN.md §4.5, §10)."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.common import file_response, read_body
from app.api.masters import _invalid, master_out, version_meta
from app.auth.deps import current_user, get_settings
from app.auth.sessions import AuthContext
from app.config import Settings
from app.db.engine import get_db
from app.db.models import AiCall, ImportJob, MasterResumeVersion, UploadedFile, User
from app.db.types import utcnow
from app.errors import ApiError
from app.importers.extract import Extraction, extract
from app.importers.sniff import MAX_FILE_BYTES, ImportRejected, sniff
from app.keys import service as keys
from app.masters import merge
from app.masters.normalize import MAX_DOCUMENT_BYTES, content_sha256, diff_documents, normalize
from app.masters.repository import MasterRepository
from app.models.api import (
    ImportAcceptIn,
    ImportDetailOut,
    ImportOut,
    ImportPreviewOut,
    ImportReviewIn,
    ImportReviewOut,
    ImportTextIn,
    MasterSaveOut,
    MergeIn,
    MergeItemOut,
    MergePlanIn,
    MergePlanOut,
)
from app.pipeline import usage
from app.pipeline.importer import ACTIVE, run_import
from app.services import settings_store

router = APIRouter(prefix="/api/imports", tags=["imports"])
KEEPALIVE_SECONDS = 15.0


class ImportRepository:
    """Owner-scoped access to imports and uploaded files."""

    def __init__(self, db: AsyncSession, owner_id: str) -> None:
        self.db, self.owner_id = db, owner_id

    async def get(self, import_id: str) -> ImportJob:
        job = (await self.db.execute(select(ImportJob).where(
            ImportJob.id == import_id, ImportJob.owner_id == self.owner_id))).scalar_one_or_none()
        if job is None:
            raise ApiError(404, "Import not found.")
        return job

    async def list(self) -> list[ImportJob]:
        stmt = select(ImportJob).where(ImportJob.owner_id == self.owner_id).order_by(ImportJob.created_at.desc())
        return list((await self.db.execute(stmt)).scalars())

    async def file(self, file_id: str | None) -> UploadedFile | None:
        if file_id is None:
            return None
        return (await self.db.execute(select(UploadedFile).where(
            UploadedFile.id == file_id, UploadedFile.owner_id == self.owner_id))).scalar_one_or_none()

    async def cost(self, import_id: str) -> float:
        stmt = select(func.coalesce(func.sum(AiCall.est_cost_usd), 0.0)).where(
            AiCall.import_job_id == import_id, AiCall.owner_id == self.owner_id)
        return float((await self.db.execute(stmt)).scalar_one())

    async def file_in_use(self, file_id: str) -> bool:
        stmt = select(func.count()).select_from(MasterResumeVersion).where(
            MasterResumeVersion.source_file_id == file_id, MasterResumeVersion.owner_id == self.owner_id)
        return bool((await self.db.execute(stmt)).scalar_one())


def get_repo(ctx: AuthContext = Depends(current_user), db: AsyncSession = Depends(get_db)) -> ImportRepository:
    return ImportRepository(db, ctx.user.id)


def _out(job: ImportJob) -> dict[str, Any]:
    return {"id": job.id, "status": job.status, "error": job.error, "source_kind": job.source_kind,
            "source_name": job.source_name, "model": job.model, "result_master_id": job.result_master_id,
            "created_at": job.created_at, "updated_at": job.updated_at}


def _rejected(exc: ImportRejected) -> ApiError:
    status = 413 if exc.code == "too_large" else 422
    return ApiError(status, exc.message, extra={"code": exc.code})


async def _start(request: Request, db: AsyncSession, user: User, settings: Settings, *, kind: str, name: str,
                 extraction: Extraction, data: bytes | None) -> ImportJob:
    """Check the key and cap, store the file, create the job and queue it."""
    key = await keys.resolve(db, user, settings)  # fails early with "add your key" instead of mid-job
    model = (await settings_store.model_policy(db)).choose(user.preferred_model)
    await usage.ensure_within_cap(db, user, key.source, settings,
                                  usage.estimate_job_cost(model, settings, stages=("import",)))
    file_id = None
    if data is not None:
        storage_key = request.app.state.files.save(user.id, data)
        file = UploadedFile(owner_id=user.id, kind=kind, original_name=name, size=len(data),
                            sha256=hashlib.sha256(data).hexdigest(), storage_key=storage_key, created_at=utcnow())
        db.add(file)
        await db.flush()
        file_id = file.id
    now = utcnow()
    job = ImportJob(owner_id=user.id, file_id=file_id, source_kind=kind, source_name=name, status="queued",
                    model=model, extraction=extraction.as_json(), flags=[], created_at=now, updated_at=now)
    db.add(job)
    await db.commit()
    app = request.app
    app.state.jobs.submit(user.id, lambda: run_import(app, job.id))
    return job


def _clean_name(name: str | None, fallback: str) -> str:
    cleaned = "".join(c for c in (name or "") if c.isprintable() and c not in '/\\"').strip()
    return cleaned[-255:] or fallback


@router.post("", response_model=ImportOut, status_code=202)
async def upload_resume(
    request: Request,
    filename: str | None = Query(default=None, max_length=255, description="The original file name, for display."),
    ctx: AuthContext = Depends(current_user), db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ImportOut:
    """Upload a PDF or DOCX résumé (the raw file is the request body; up to 5 MB and 10 pages)."""
    data = await read_body(request, MAX_FILE_BYTES, "The file is larger than 5 MB.")
    try:
        kind = sniff(data)
        await keys.resolve(db, ctx.user, settings)  # before spending time on extraction
        extraction = await extract(kind, data)
    except ImportRejected as exc:
        raise _rejected(exc) from None
    if kind == "docx" and not extraction.text.strip():
        raise ApiError(422, "We couldn't find any text in this Word file.", extra={"code": "empty"})
    name = _clean_name(filename, f"résumé.{kind}")
    job = await _start(request, db, ctx.user, settings, kind=kind, name=name, extraction=extraction, data=data)
    return ImportOut(**_out(job))


@router.post("/text", response_model=ImportOut, status_code=202)
async def import_text(body: ImportTextIn, request: Request, ctx: AuthContext = Depends(current_user),
                      db: AsyncSession = Depends(get_db), settings: Settings = Depends(get_settings)) -> ImportOut:
    """Import a résumé from pasted plain text."""
    extraction = Extraction(kind="text", text=body.text)
    job = await _start(request, db, ctx.user, settings, kind="text", name=_clean_name(body.name, "Pasted text"),
                       extraction=extraction, data=None)
    return ImportOut(**_out(job))


@router.get("", response_model=list[ImportOut])
async def list_imports(repo: ImportRepository = Depends(get_repo)) -> list[ImportOut]:
    return [ImportOut(**_out(job)) for job in await repo.list()]


@router.get("/{import_id}", response_model=ImportDetailOut)
async def get_import(import_id: str, repo: ImportRepository = Depends(get_repo)) -> ImportDetailOut:
    job = await repo.get(import_id)
    review = job.review or {}
    return ImportDetailOut(
        **_out(job), pages=job.extraction.get("pages"), has_text_layer=bool(job.extraction.get("hasTextLayer", True)),
        draft=job.draft, document=review.get("document") or job.draft, flags=job.flags or [],
        resolved=review.get("resolved") or {}, cost_usd=round(await repo.cost(job.id), 4),
        fidelity={k: v for k, v in job.fidelity.items() if k != "mismatches"} if job.fidelity else None,
    )


@router.get("/{import_id}/preview", response_model=ImportPreviewOut)
async def preview(import_id: str, repo: ImportRepository = Depends(get_repo)) -> ImportPreviewOut:
    """What the review screen shows beside the draft. PDFs are shown from ``/source``."""
    job = await repo.get(import_id)
    extraction = job.extraction or {}
    return ImportPreviewOut(kind=job.source_kind, html=extraction.get("html"), text=extraction.get("text") or None,  # type: ignore[arg-type]
                            pages=extraction.get("pages"))


@router.get("/{import_id}/source")
async def download_source(import_id: str, request: Request, repo: ImportRepository = Depends(get_repo)) -> Response:
    """The original uploaded file."""
    job = await repo.get(import_id)
    file = await repo.file(job.file_id)
    if file is None:
        raise ApiError(404, "This import has no file (it was pasted text, or the file was deleted).")
    return file_response(request, file)


def _document_size_ok(document: dict[str, Any]) -> None:
    if len(json.dumps(document, ensure_ascii=False).encode()) > MAX_DOCUMENT_BYTES:
        raise ApiError(413, "The document is larger than 1 MB.")


@router.put("/{import_id}/review", response_model=ImportReviewOut)
async def save_review(import_id: str, body: ImportReviewIn,
                      repo: ImportRepository = Depends(get_repo)) -> ImportReviewOut:
    """Autosave the review: the edited document and which flags were accepted or dismissed."""
    job = await repo.get(import_id)
    if job.status != "ready":
        raise ApiError(409, "This import isn't ready for review.")
    _document_size_ok(body.document)
    job.review = {"document": body.document, "resolved": body.resolved}
    job.updated_at = utcnow()
    await repo.db.commit()
    return ImportReviewOut(updated_at=job.updated_at)


@router.post("/{import_id}/accept", response_model=MasterSaveOut, status_code=201)
async def accept_import(import_id: str, body: ImportAcceptIn,
                        repo: ImportRepository = Depends(get_repo)) -> MasterSaveOut:
    """Save the reviewed document as a new master résumé. The original file stays attached to its version."""
    job = await repo.get(import_id)
    if job.status != "ready":
        raise ApiError(409, "This import isn't ready to save." if job.status != "accepted"
                       else "This import was already saved as a master résumé.")
    _document_size_ok(body.document)
    document = {**body.document, "meta": {**(body.document.get("meta") or {}), "label": body.label}}
    result = normalize(document)
    if not result.ok or result.document is None:
        raise _invalid(result)
    _, warnings = result.issues_as_dicts()
    masters = MasterRepository(repo.db, repo.owner_id)
    master, version = await masters.create(body.label, result.document, content_sha256(result.document), warnings)
    version.source_file_id = job.file_id
    job.status, job.result_master_id, job.updated_at = "accepted", master.id, utcnow()
    await repo.db.commit()
    file = await repo.file(job.file_id)
    return MasterSaveOut(master=master_out(master, 1, version), version=version_meta(version, file),
                         created_new_version=True)


async def _merge_inputs(repo: ImportRepository, import_id: str, body: MergePlanIn) -> tuple[Any, Any, Any, Any]:
    """The import (ready), the reviewed document normalized, the target master and its current version."""
    job = await repo.get(import_id)
    if job.status != "ready":
        raise ApiError(409, "This import isn't ready to save." if job.status != "accepted"
                       else "This import was already saved.")
    _document_size_ok(body.document)
    result = normalize(body.document)
    if not result.ok or result.document is None:
        raise _invalid(result)
    masters = MasterRepository(repo.db, repo.owner_id)
    master = await masters.get(body.master_id)
    version = await masters.current_version(master) if master else None
    if master is None or version is None:
        raise ApiError(404, "Master résumé not found.")
    return job, result.document, master, version


@router.post("/{import_id}/merge-plan", response_model=MergePlanOut)
async def merge_plan(import_id: str, body: MergePlanIn, repo: ImportRepository = Depends(get_repo)) -> MergePlanOut:
    """What merging into an existing master would add (IMP-6): new items, and new bullets for ones it has."""
    _, document, master, version = await _merge_inputs(repo, import_id, body)
    items = [MergeItemOut(key=p.key, section=p.section, title=p.title, detail=p.detail, status=p.status,  # type: ignore[arg-type]
                          bullets=p.bullets, similar_to=p.similar_to) for p in merge.plan(document, version.content)]
    return MergePlanOut(master_id=master.id, base_version_id=version.id, items=items)


@router.post("/{import_id}/merge", response_model=MasterSaveOut, status_code=201)
async def merge_import(import_id: str, body: MergeIn, repo: ImportRepository = Depends(get_repo)) -> MasterSaveOut:
    """Add what was picked from the plan to the master, as a new version. Nothing already there changes."""
    job, document, master, version = await _merge_inputs(repo, import_id, body)
    if version.id != body.base_version_id:
        raise ApiError(409, "That master résumé changed since this comparison. Compare again.")
    merged = normalize(merge.apply(document, version.content, body.selections))
    if not merged.ok or merged.document is None:
        raise _invalid(merged)
    _, warnings = merged.issues_as_dicts()
    masters = MasterRepository(repo.db, repo.owner_id)
    sha = content_sha256(merged.document)
    if sha == version.sha256:
        raise ApiError(422, "Nothing was picked to add.")
    new_version = await masters.add_version(master, merged.document, sha, warnings)
    new_version.source_file_id = job.file_id
    job.status, job.result_master_id, job.updated_at = "accepted", master.id, utcnow()
    await repo.db.commit()
    file = await repo.file(job.file_id)
    return MasterSaveOut(master=master_out(master, await masters.version_count(master.id), new_version),
                         version=version_meta(new_version, file), created_new_version=True,
                         changes=diff_documents(version.content, merged.document))


@router.post("/{import_id}/retry", response_model=ImportOut, status_code=202)
async def retry_import(import_id: str, request: Request, ctx: AuthContext = Depends(current_user),
                       settings: Settings = Depends(get_settings),
                       repo: ImportRepository = Depends(get_repo)) -> ImportOut:
    job = await repo.get(import_id)
    if job.status != "failed":
        raise ApiError(409, "Only failed imports can be retried.")
    key = await keys.resolve(repo.db, ctx.user, settings)
    await usage.ensure_within_cap(repo.db, ctx.user, key.source, settings,
                                  usage.estimate_job_cost(job.model, settings, stages=("import",)))
    job.status, job.error, job.updated_at = "queued", None, utcnow()
    await repo.db.commit()
    app = request.app
    app.state.jobs.submit(ctx.user.id, lambda: run_import(app, job.id))
    return ImportOut(**_out(job))


@router.delete("/{import_id}", status_code=204)
async def delete_import(import_id: str, request: Request, repo: ImportRepository = Depends(get_repo)) -> Response:
    """Discard an import. Its file is deleted too, unless a saved master version still uses it."""
    job = await repo.get(import_id)
    if job.status in ACTIVE:
        raise ApiError(409, "This import is still running. Wait for it to finish, then delete it.")
    file = await repo.file(job.file_id)
    await repo.db.delete(job)
    if file is not None and not await repo.file_in_use(file.id):
        await repo.db.delete(file)
        request.app.state.files.delete(file.storage_key)
    await repo.db.commit()
    return Response(status_code=204)


# ---- progress events (SSE) -------------------------------------------------------------------------------


def _sse(event: dict[str, Any]) -> str:
    return f"event: {event['type']}\ndata: {json.dumps(event)}\n\n"


@router.get("/{import_id}/events")
async def import_events(import_id: str, request: Request,
                        repo: ImportRepository = Depends(get_repo)) -> StreamingResponse:
    await repo.get(import_id)  # ownership check
    bus = request.app.state.events
    queue = bus.subscribe(import_id)

    async def stream() -> AsyncIterator[str]:
        try:
            async with request.app.state.sessionmaker() as db:
                current = await db.get(ImportJob, import_id)
            if current is None:
                return
            yield _sse({"type": "status", "status": current.status})
            if current.status in ("ready", "accepted"):
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
            bus.unsubscribe(import_id, queue)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})
