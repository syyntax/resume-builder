"""Account self-service: profile, data export and account deletion (AUTH-8)."""

from __future__ import annotations

import io
import json
import zipfile

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.common import enforce_backoff, user_out, verify_password
from app.auth.audit import audit
from app.auth.deps import current_user, get_limits, get_settings
from app.auth.ratelimit import Limits
from app.auth.sessions import AuthContext, clear_session_cookie
from app.config import Settings
from app.db.engine import get_db
from app.db.models import UploadedFile
from app.db.types import utcnow
from app.errors import ApiError
from app.masters.repository import MasterRepository
from app.models.api import DeleteAccountIn, ProfileIn, UserOut
from app.services.users import find_by_email, is_valid_email, normalize_email, would_remove_last_admin

router = APIRouter(prefix="/api/account", tags=["account"])


async def _confirm_password(ctx: AuthContext, password: str | None, limits: Limits, field: str) -> None:
    enforce_backoff(limits.password_check, ctx.user.id)
    ok = bool(password) and (await verify_password(ctx.user.password_hash, password or ""))[0]
    if not ok:
        limits.password_check.failure(ctx.user.id)
        raise ApiError(400, "Your password is incorrect.", errors=[{"field": field, "message": "incorrect"}])
    limits.password_check.reset(ctx.user.id)


@router.patch("/profile", response_model=UserOut)
async def update_profile(
    body: ProfileIn,
    request: Request,
    ctx: AuthContext = Depends(current_user),
    db: AsyncSession = Depends(get_db),
    limits: Limits = Depends(get_limits),
) -> UserOut:
    user = ctx.user
    changed: list[str] = []
    if body.email is not None and normalize_email(body.email) != user.email:
        new_email = normalize_email(body.email)
        if not is_valid_email(new_email):
            raise ApiError(422, "Enter a valid email address.", errors=[{"field": "email", "message": "invalid"}])
        await _confirm_password(ctx, body.current_password, limits, "currentPassword")
        if await find_by_email(db, new_email) is not None:
            raise ApiError(409, "Another account already uses that email.")
        user.email = new_email
        changed.append("email")
    if body.display_name is not None and body.display_name != user.display_name:
        user.display_name = body.display_name
        changed.append("displayName")
    if changed:
        await audit(db, "account.profile.change", request, actor_id=user.id, target_id=user.id, fields=changed)
        await db.commit()
    return user_out(user)


@router.get("/export")
async def export_account(
    request: Request, ctx: AuthContext = Depends(current_user), db: AsyncSession = Depends(get_db)
) -> Response:
    """A ZIP of everything the account owns. API keys and password hashes are never included."""
    user = ctx.user
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        profile = user_out(user).model_dump(mode="json", by_alias=True)
        archive.writestr("account.json", json.dumps({"exportedAt": utcnow().isoformat(), "user": profile}, indent=2))
        for master, versions in await MasterRepository(db, user.id).all_with_versions():
            folder = f"master-resumes/{master.id}"
            archive.writestr(f"{folder}/master.json", json.dumps(
                {"id": master.id, "label": master.label, "currentVersionId": master.current_version_id}, indent=2))
            for version in versions:
                archive.writestr(f"{folder}/v{version.version_number}.json",
                                 json.dumps(version.content, indent=2, ensure_ascii=False))
        files = (await db.execute(select(UploadedFile).where(UploadedFile.owner_id == user.id))).scalars()
        for file in files:
            data = request.app.state.files.read(file.storage_key)
            archive.writestr(f"uploads/{file.id}-{file.original_name.replace('/', '_')}", data)
    await audit(db, "account.export", request, actor_id=user.id, target_id=user.id)
    await db.commit()
    stamp = utcnow().strftime("%Y%m%d")
    return Response(
        buffer.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="resume-tailor-export-{stamp}.zip"'},
    )


@router.delete("", status_code=204)
async def delete_account(
    body: DeleteAccountIn,
    request: Request,
    ctx: AuthContext = Depends(current_user),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    limits: Limits = Depends(get_limits),
) -> Response:
    await _confirm_password(ctx, body.password, limits, "password")
    user = ctx.user
    if await would_remove_last_admin(db, user, new_role=None, new_status=None, deleting=True):
        raise ApiError(409, "You're the only admin. Make someone else an admin before deleting your account.")
    await audit(db, "account.delete", request, target_id=None, email=user.email, user_id=user.id)
    await db.delete(user)  # cascades to sessions, tokens and all owned content
    await db.commit()
    request.app.state.files.delete_owner(user.id)  # and the uploaded résumés on disk
    response = Response(status_code=204)
    clear_session_cookie(response, settings)
    return response
