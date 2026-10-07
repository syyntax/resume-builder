"""Admin console API (DESIGN.md §4.3, §8.1). Nothing here returns users' documents."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.api.common import user_out
from app.auth import tokens
from app.auth.audit import audit
from app.auth.deps import get_settings, require_admin
from app.auth.sessions import AuthContext, revoke_all
from app.config import Settings
from app.db.engine import get_db
from app.db.models import AuditLog, AuthToken, User
from app.db.types import utcnow
from app.errors import ApiError
from app.models.api import (
    AdminUserPatchIn,
    AuditEntryOut,
    InviteCreateIn,
    InviteOut,
    LinkOut,
    SystemSettingsIn,
    SystemSettingsOut,
    UserOut,
)
from app.services import settings_store
from app.services.users import find_by_email, is_valid_email, normalize_email, would_remove_last_admin

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)])


async def _target(db: AsyncSession, user_id: str) -> User:
    user = await db.get(User, user_id)
    if user is None:
        raise ApiError(404, "User not found.")
    return user


# ---- users -----------------------------------------------------------------------------------------


@router.get("/users", response_model=list[UserOut])
async def list_users(db: AsyncSession = Depends(get_db)) -> list[UserOut]:
    users = (await db.execute(select(User).order_by(User.created_at))).scalars()
    return [user_out(u) for u in users]


@router.patch("/users/{user_id}", response_model=UserOut)
async def update_user(
    user_id: str,
    body: AdminUserPatchIn,
    request: Request,
    ctx: AuthContext = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> UserOut:
    user = await _target(db, user_id)
    if await would_remove_last_admin(db, user, new_role=body.role, new_status=body.status):
        raise ApiError(409, "That would leave no active admin. Make someone else an admin first.")
    if body.role and body.role != user.role:
        await audit(db, "user.role.change", request, actor_id=ctx.user.id, target_id=user.id,
                    old=user.role, new=body.role)
        user.role = body.role
        await revoke_all(db, user.id)
    if body.status and body.status != user.status:
        await audit(db, "user.disable" if body.status == "disabled" else "user.enable", request,
                    actor_id=ctx.user.id, target_id=user.id)
        user.status = body.status
        await revoke_all(db, user.id)
    await db.commit()
    return user_out(user)


@router.delete("/users/{user_id}", status_code=204)
async def delete_user(
    user_id: str, request: Request, ctx: AuthContext = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> Response:
    user = await _target(db, user_id)
    if user.id == ctx.user.id:
        raise ApiError(409, "Delete your own account from the Account page.")
    if await would_remove_last_admin(db, user, new_role=None, new_status=None, deleting=True):
        raise ApiError(409, "That would leave no active admin.")
    await audit(db, "user.delete", request, actor_id=ctx.user.id, email=user.email, user_id=user.id)
    await db.delete(user)
    await db.commit()
    return Response(status_code=204)


@router.post("/users/{user_id}/reset-link", response_model=LinkOut)
async def reset_link(
    user_id: str,
    request: Request,
    ctx: AuthContext = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> LinkOut:
    user = await _target(db, user_id)
    await tokens.delete_unused(db, "password_reset", user_id=user.id)
    raw, token = await tokens.create_token(db, "password_reset", tokens.RESET_TTL, user_id=user.id,
                                           created_by=ctx.user.id)
    await audit(db, "auth.password.reset_link", request, actor_id=ctx.user.id, target_id=user.id)
    await db.commit()
    return LinkOut(url=f"{settings.app_base_url}/reset-password/{raw}", expires_at=token.expires_at)


# ---- invites ---------------------------------------------------------------------------------------


def _invite_out(token: AuthToken, url: str | None = None) -> InviteOut:
    return InviteOut(id=token.id, email=token.email, created_at=token.created_at, expires_at=token.expires_at,
                     created_by=token.created_by, url=url)


@router.get("/invites", response_model=list[InviteOut])
async def list_invites(db: AsyncSession = Depends(get_db)) -> list[InviteOut]:
    rows = (
        await db.execute(
            select(AuthToken)
            .where(AuthToken.purpose == "invite", AuthToken.used_at.is_(None), AuthToken.expires_at > utcnow())
            .order_by(AuthToken.created_at.desc())
        )
    ).scalars()
    return [_invite_out(t) for t in rows]


@router.post("/invites", response_model=InviteOut, status_code=201)
async def create_invite(
    body: InviteCreateIn,
    request: Request,
    ctx: AuthContext = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> InviteOut:
    email = normalize_email(body.email) if body.email else None
    if email is not None:
        if not is_valid_email(email):
            raise ApiError(422, "Enter a valid email address.", errors=[{"field": "email", "message": "invalid"}])
        if await find_by_email(db, email) is not None:
            raise ApiError(409, "An account with that email already exists.")
    raw, token = await tokens.create_token(db, "invite", tokens.INVITE_TTL, email=email, created_by=ctx.user.id)
    await audit(db, "user.invite.create", request, actor_id=ctx.user.id, invite_id=token.id, email=email)
    await db.commit()
    return _invite_out(token, url=f"{settings.app_base_url}/invite/{raw}")


@router.delete("/invites/{invite_id}", status_code=204)
async def revoke_invite(
    invite_id: str, request: Request, ctx: AuthContext = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> Response:
    token = await db.get(AuthToken, invite_id)
    if token is None or token.purpose != "invite" or token.used_at is not None:
        raise ApiError(404, "Invite not found.")
    await db.delete(token)
    await audit(db, "user.invite.revoke", request, actor_id=ctx.user.id, invite_id=invite_id)
    await db.commit()
    return Response(status_code=204)


# ---- settings --------------------------------------------------------------------------------------


async def _settings_out(db: AsyncSession, settings: Settings) -> SystemSettingsOut:
    policy = await settings_store.registration_policy(db)
    return SystemSettingsOut(
        registration_mode=policy.mode,  # type: ignore[arg-type]
        registration_email_domains=policy.domains,
        open_registration_exposed=policy.mode == "open" and not policy.domains and not settings.base_is_local,
    )


@router.get("/settings", response_model=SystemSettingsOut)
async def get_system_settings(
    db: AsyncSession = Depends(get_db), settings: Settings = Depends(get_settings)
) -> SystemSettingsOut:
    return await _settings_out(db, settings)


@router.put("/settings", response_model=SystemSettingsOut)
async def update_system_settings(
    body: SystemSettingsIn,
    request: Request,
    ctx: AuthContext = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> SystemSettingsOut:
    changes: dict[str, object] = {}
    if body.registration_mode is not None:
        await settings_store.set_value(db, settings_store.REGISTRATION_MODE, body.registration_mode,
                                       updated_by=ctx.user.id)
        changes["registrationMode"] = body.registration_mode
    if body.registration_email_domains is not None:
        domains = sorted({d.lower().lstrip("@") for d in body.registration_email_domains})
        await settings_store.set_value(db, settings_store.REGISTRATION_DOMAINS, domains, updated_by=ctx.user.id)
        changes["registrationEmailDomains"] = domains
    if changes:
        await audit(db, "admin.settings.change", request, actor_id=ctx.user.id, **changes)
        await db.commit()
    return await _settings_out(db, settings)


# ---- audit log -------------------------------------------------------------------------------------


@router.get("/audit-log", response_model=list[AuditEntryOut])
async def audit_log(
    db: AsyncSession = Depends(get_db),
    event: str | None = Query(default=None, max_length=64, description="Event name or prefix, e.g. 'auth.'"),
    user_id: str | None = Query(default=None, max_length=40, alias="userId"),
    before: datetime | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[AuditEntryOut]:
    actor, target = aliased(User), aliased(User)
    stmt = (
        select(AuditLog, actor.email, target.email)
        .outerjoin(actor, actor.id == AuditLog.actor_user_id)
        .outerjoin(target, target.id == AuditLog.target_user_id)
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .limit(limit)
    )
    if event:
        stmt = stmt.where(AuditLog.event.startswith(event, autoescape=True))
    if user_id:
        stmt = stmt.where(or_(AuditLog.actor_user_id == user_id, AuditLog.target_user_id == user_id))
    if before:
        stmt = stmt.where(AuditLog.created_at < before)
    rows = (await db.execute(stmt)).all()
    return [
        AuditEntryOut(id=row.id, event=row.event, actor_email=actor_email, target_email=target_email, ip=row.ip,
                      user_agent=row.user_agent, details=row.details or {}, created_at=row.created_at)
        for row, actor_email, target_email in rows
    ]
