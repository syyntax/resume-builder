"""Master résumé upload, validation, versions and download (DESIGN.md §4.4, MST-1…MST-5)."""

from __future__ import annotations

import json
import re

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import current_user
from app.auth.sessions import AuthContext
from app.db.engine import get_db
from app.db.models import MasterResume, MasterResumeVersion
from app.errors import ApiError
from app.masters.normalize import (
    MAX_DOCUMENT_BYTES,
    NormalizeResult,
    content_sha256,
    diff_documents,
    normalize_raw,
    summarize,
)
from app.masters.repository import MasterRepository
from app.models.api import (
    IssueOut,
    MasterDetailOut,
    MasterOut,
    MasterPatchIn,
    MasterSaveOut,
    MasterSummary,
    ValidationOut,
    VersionMeta,
    VersionOut,
)

router = APIRouter(prefix="/api/master-resumes", tags=["master-resumes"])


def get_repo(ctx: AuthContext = Depends(current_user), db: AsyncSession = Depends(get_db)) -> MasterRepository:
    return MasterRepository(db, ctx.user.id)


async def read_document(request: Request) -> bytes:
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_DOCUMENT_BYTES:
        raise ApiError(413, "The file is larger than 1 MB.")
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_DOCUMENT_BYTES:
            raise ApiError(413, "The file is larger than 1 MB.")
    return bytes(body)


def _invalid(result: NormalizeResult) -> ApiError:
    errors, warnings = result.issues_as_dicts()
    return ApiError(422, "The master résumé has problems. Fix them and upload again.", errors=errors,
                    extra={"warnings": warnings})


def version_meta(version: MasterResumeVersion) -> VersionMeta:
    return VersionMeta(
        id=version.id,
        version_number=version.version_number,
        sha256=version.sha256,
        created_at=version.created_at,
        summary=MasterSummary.model_validate(summarize(version.content)),
        warnings=[IssueOut.model_validate(w) for w in version.warnings or []],
    )


def master_out(master: MasterResume, count: int, current: MasterResumeVersion | None) -> MasterOut:
    return MasterOut(id=master.id, label=master.label, created_at=master.created_at, updated_at=master.updated_at,
                     version_count=count, current_version=version_meta(current) if current else None)


@router.post("/validate", response_model=ValidationOut)
async def validate_master(request: Request, _: MasterRepository = Depends(get_repo)) -> ValidationOut:
    """Validate and normalize without saving."""
    result = normalize_raw(await read_document(request))
    errors, warnings = result.issues_as_dicts()
    return ValidationOut(
        valid=result.ok,
        errors=[IssueOut.model_validate(e) for e in errors],
        warnings=[IssueOut.model_validate(w) for w in warnings],
        summary=MasterSummary.model_validate(summarize(result.document)) if result.document else None,
        normalized=result.document,
    )


@router.post("", response_model=MasterSaveOut, status_code=201)
async def create_master(
    request: Request,
    label: str | None = Query(default=None, min_length=1, max_length=100),
    repo: MasterRepository = Depends(get_repo),
) -> MasterSaveOut:
    result = normalize_raw(await read_document(request))
    if not result.ok or result.document is None:
        raise _invalid(result)
    _, warnings = result.issues_as_dicts()
    doc = result.document
    name = label or (doc.get("meta") or {}).get("label") or "Master résumé"
    master, version = await repo.create(name[:100], doc, content_sha256(doc), warnings)
    await repo.db.commit()
    return MasterSaveOut(master=master_out(master, 1, version), version=version_meta(version),
                         created_new_version=True)


@router.get("", response_model=list[MasterOut])
async def list_masters(repo: MasterRepository = Depends(get_repo)) -> list[MasterOut]:
    return [master_out(m, n, v) for m, n, v in await repo.list()]


async def _master_or_404(repo: MasterRepository, master_id: str) -> MasterResume:
    master = await repo.get(master_id)
    if master is None:
        raise ApiError(404, "Master résumé not found.")
    return master


@router.get("/{master_id}", response_model=MasterDetailOut)
async def get_master(master_id: str, repo: MasterRepository = Depends(get_repo)) -> MasterDetailOut:
    master = await _master_or_404(repo, master_id)
    current = await repo.current_version(master)
    base = master_out(master, await repo.version_count(master.id), current)
    return MasterDetailOut(**base.model_dump(), content=current.content if current else None)


@router.put("/{master_id}", response_model=MasterSaveOut)
async def save_new_version(
    master_id: str, request: Request, repo: MasterRepository = Depends(get_repo)
) -> MasterSaveOut:
    master = await _master_or_404(repo, master_id)  # ownership first, before reading the body
    result = normalize_raw(await read_document(request))
    if not result.ok or result.document is None:
        raise _invalid(result)
    _, warnings = result.issues_as_dicts()
    doc = result.document
    sha = content_sha256(doc)
    current = await repo.current_version(master)
    if current is not None and current.sha256 == sha:
        return MasterSaveOut(master=master_out(master, await repo.version_count(master.id), current),
                             version=version_meta(current), created_new_version=False)
    changes = diff_documents(current.content, doc) if current else None
    version = await repo.add_version(master, doc, sha, warnings)
    await repo.db.commit()
    return MasterSaveOut(master=master_out(master, await repo.version_count(master.id), version),
                         version=version_meta(version), created_new_version=True, changes=changes)


@router.patch("/{master_id}", response_model=MasterOut)
async def rename_master(master_id: str, body: MasterPatchIn, repo: MasterRepository = Depends(get_repo)) -> MasterOut:
    master = await _master_or_404(repo, master_id)
    master.label = body.label
    await repo.db.commit()
    return master_out(master, await repo.version_count(master.id), await repo.current_version(master))


@router.delete("/{master_id}", status_code=204)
async def delete_master(master_id: str, repo: MasterRepository = Depends(get_repo)) -> Response:
    master = await _master_or_404(repo, master_id)
    await repo.delete(master)
    await repo.db.commit()
    return Response(status_code=204)


@router.get("/{master_id}/versions", response_model=list[VersionMeta])
async def list_versions(master_id: str, repo: MasterRepository = Depends(get_repo)) -> list[VersionMeta]:
    await _master_or_404(repo, master_id)
    return [version_meta(v) for v in await repo.list_versions(master_id)]


async def _version_or_404(repo: MasterRepository, master_id: str, version_id: str) -> MasterResumeVersion:
    version = await repo.get_version(master_id, version_id)
    if version is None:
        raise ApiError(404, "Version not found.")
    return version


@router.get("/{master_id}/versions/{version_id}", response_model=VersionOut)
async def get_version(master_id: str, version_id: str, repo: MasterRepository = Depends(get_repo)) -> VersionOut:
    version = await _version_or_404(repo, master_id, version_id)
    return VersionOut(**version_meta(version).model_dump(), content=version.content)


@router.get("/{master_id}/versions/{version_id}/normalized")
async def download_normalized(
    master_id: str, version_id: str, repo: MasterRepository = Depends(get_repo)
) -> Response:
    master = await _master_or_404(repo, master_id)
    version = await _version_or_404(repo, master_id, version_id)
    slug = re.sub(r"[^A-Za-z0-9]+", "-", master.label).strip("-").lower() or "master"
    return Response(
        json.dumps(version.content, indent=2, ensure_ascii=False) + "\n",
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{slug}-v{version.version_number}.json"'},
    )
