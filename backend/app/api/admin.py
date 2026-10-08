"""Admin console API (DESIGN.md §4.3, §8.1). Nothing here returns users' documents."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.ai.llm import LLMError
from app.ai.pricing import load_prices
from app.api.common import month_range, user_out
from app.auth import mfa, tokens
from app.auth.audit import audit
from app.auth.deps import get_settings, require_admin
from app.auth.sessions import AuthContext, revoke_all
from app.config import Settings
from app.db.engine import get_db
from app.db.models import AiCall, Application, AuditLog, AuthToken, ImportJob, User, UserApiKey
from app.db.types import utcnow
from app.errors import ApiError
from app.keys import service as keys
from app.models.api import (
    AdminAiSettingsIn,
    AdminAiSettingsOut,
    AdminUserOut,
    AdminUserPatchIn,
    AuditEntryOut,
    InviteCreateIn,
    InviteOut,
    LinkOut,
    StageEfforts,
    SystemSettingsIn,
    SystemSettingsOut,
    UserUsageOut,
)
from app.render.theme import TEMPLATES
from app.services import defaults, mail, settings_store
from app.services.users import find_by_email, is_valid_email, normalize_email, would_remove_last_admin

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)])


async def _target(db: AsyncSession, user_id: str) -> User:
    user = await db.get(User, user_id)
    if user is None:
        raise ApiError(404, "User not found.")
    return user


# ---- users -----------------------------------------------------------------------------------------


async def _admin_user(db: AsyncSession, user: User) -> AdminUserOut:
    has_key = await keys.get_row(db, user.id) is not None
    return AdminUserOut(**user_out(user).model_dump(), has_api_key=has_key, shared_cap_usd=user.shared_cap_usd)


@router.get("/users", response_model=list[AdminUserOut])
async def list_users(db: AsyncSession = Depends(get_db)) -> list[AdminUserOut]:
    with_keys = set((await db.execute(select(UserApiKey.user_id))).scalars())
    users = (await db.execute(select(User).order_by(User.created_at))).scalars()
    return [AdminUserOut(**user_out(u).model_dump(), has_api_key=u.id in with_keys, shared_cap_usd=u.shared_cap_usd)
            for u in users]


@router.patch("/users/{user_id}", response_model=AdminUserOut)
async def update_user(
    user_id: str,
    body: AdminUserPatchIn,
    request: Request,
    ctx: AuthContext = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminUserOut:
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
    if body.reset_shared_cap or body.shared_cap_usd is not None:
        user.shared_cap_usd = None if body.reset_shared_cap else body.shared_cap_usd
        await audit(db, "user.shared_cap.change", request, actor_id=ctx.user.id, target_id=user.id,
                    cap=user.shared_cap_usd)
    await db.commit()
    return await _admin_user(db, user)


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
    request.app.state.files.delete_owner(user.id)  # uploaded résumés (rows were removed by the cascade)
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


@router.post("/users/{user_id}/mfa-reset", response_model=AdminUserOut)
async def reset_mfa(user_id: str, request: Request, ctx: AuthContext = Depends(require_admin),
                    db: AsyncSession = Depends(get_db)) -> AdminUserOut:
    """For a user who lost their authenticator and recovery codes: turn two-step verification off and sign
    them out everywhere. If it's required, they set it up again at their next sign-in."""
    user = await _target(db, user_id)
    await mfa.turn_off(db, user)
    await revoke_all(db, user.id)
    await audit(db, "auth.mfa.reset", request, actor_id=ctx.user.id, target_id=user.id)
    await db.commit()
    return await _admin_user(db, user)


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
    url = f"{settings.app_base_url}/invite/{raw}"
    emailed = bool(email and request.app.state.mailer is not None)
    if emailed:
        mail.send_later(request.app.state.mailer, mail.invite(email, url, ctx.user.display_name))  # type: ignore[arg-type]
    await audit(db, "user.invite.create", request, actor_id=ctx.user.id, invite_id=token.id, email=email,
                emailed=emailed)
    await db.commit()
    return _invite_out(token, url=url).model_copy(update={"emailed": emailed})


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
        require_mfa=str(await settings_store.get_value(db, settings_store.REQUIRE_MFA, "none")),  # type: ignore[arg-type]
        email_enabled=settings.smtp_enabled,
        default_design=await defaults.instance_design(db),
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
    if body.require_mfa is not None:
        await settings_store.set_value(db, settings_store.REQUIRE_MFA, body.require_mfa, updated_by=ctx.user.id)
        request.app.state.mfa_policy = body.require_mfa
        changes["requireMfa"] = body.require_mfa
    if body.default_design is not None:
        if body.default_design.template not in TEMPLATES:
            raise ApiError(422, "There's no such template.", errors=[{"field": "defaultDesign.template",
                                                                      "message": "unknown template"}])
        design = body.default_design.model_dump(mode="json", by_alias=True)
        await settings_store.set_value(db, settings_store.DEFAULT_DESIGN, design, updated_by=ctx.user.id)
        changes["defaultDesign"] = design
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
    since: date | None = Query(default=None, description="From this day (UTC)"),
    until: date | None = Query(default=None, description="Up to and including this day (UTC)"),
    before: datetime | None = Query(default=None, description="For paging: entries older than this"),
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
    if since:
        stmt = stmt.where(AuditLog.created_at >= datetime.combine(since, time.min, UTC))
    if until:
        stmt = stmt.where(AuditLog.created_at < datetime.combine(until + timedelta(days=1), time.min, UTC))
    if before:
        stmt = stmt.where(AuditLog.created_at < before)
    rows = (await db.execute(stmt)).all()
    return [
        AuditEntryOut(id=row.id, event=row.event, actor_email=actor_email, target_email=target_email, ip=row.ip,
                      user_agent=row.user_agent, details=row.details or {}, created_at=row.created_at)
        for row, actor_email, target_email in rows
    ]


# ---- AI settings, shared key and usage ---------------------------------------------------------------------


async def _ai_out(db: AsyncSession, settings: Settings) -> AdminAiSettingsOut:
    policy = await settings_store.model_policy(db)
    return AdminAiSettingsOut(
        shared_key_configured=bool(settings.shared_key),
        allow_shared_key=bool(await settings_store.get_value(db, settings_store.ALLOW_SHARED_KEY, False)),
        default_model=policy.default,
        allowed_models=policy.allowed,
        known_models=sorted(load_prices()),
        default_cap_usd=settings.default_monthly_cap_usd,
        effort=StageEfforts.model_validate({stage: getattr(settings, f"ai_effort_{stage}")
                                            for stage in settings_store.EFFORT_STAGES}),
        claim_audit=settings.ai_claim_audit,
    )


@router.get("/ai-settings", response_model=AdminAiSettingsOut)
async def get_ai_settings(db: AsyncSession = Depends(get_db),
                          settings: Settings = Depends(get_settings)) -> AdminAiSettingsOut:
    return await _ai_out(db, settings)


@router.put("/ai-settings", response_model=AdminAiSettingsOut)
async def update_ai_settings(body: AdminAiSettingsIn, request: Request, ctx: AuthContext = Depends(require_admin),
                             db: AsyncSession = Depends(get_db),
                             settings: Settings = Depends(get_settings)) -> AdminAiSettingsOut:
    policy = await settings_store.model_policy(db)
    allowed = sorted(set(body.allowed_models)) if body.allowed_models is not None else policy.allowed
    default = body.default_model or policy.default
    if default not in allowed:
        raise ApiError(422, "The default model must be one of the allowed models.",
                       errors=[{"field": "defaultModel", "message": "not in allowed models"}])
    changes: dict[str, object] = {}
    if body.allow_shared_key is not None:
        if body.allow_shared_key and not settings.shared_key:
            raise ApiError(409, "No shared key is configured. Set ANTHROPIC_API_KEY in the server's env file first.")
        await settings_store.set_value(db, settings_store.ALLOW_SHARED_KEY, body.allow_shared_key,
                                       updated_by=ctx.user.id)
        changes["allowSharedKey"] = body.allow_shared_key
    if body.allowed_models is not None or body.default_model is not None:
        await settings_store.set_value(db, settings_store.ALLOWED_MODELS, allowed, updated_by=ctx.user.id)
        await settings_store.set_value(db, settings_store.DEFAULT_MODEL, default, updated_by=ctx.user.id)
        changes.update(allowedModels=allowed, defaultModel=default)
    if body.effort is not None:
        effort = body.effort.model_dump(by_alias=True)
        await settings_store.set_value(db, settings_store.AI_EFFORT, effort, updated_by=ctx.user.id)
        changes["effort"] = effort
    if body.claim_audit is not None:
        await settings_store.set_value(db, settings_store.CLAIM_AUDIT, body.claim_audit, updated_by=ctx.user.id)
        changes["claimAudit"] = body.claim_audit
    if changes:
        await audit(db, "admin.settings.change", request, actor_id=ctx.user.id, **changes)
        await db.commit()
        request.app.state.mfa_policy = await settings_store.apply_runtime(db, settings)
    return await _ai_out(db, settings)


@router.post("/ai-settings/test-connection", status_code=204)
async def test_shared_key(request: Request, settings: Settings = Depends(get_settings)) -> Response:
    if not settings.shared_key:
        raise ApiError(404, "No shared key is configured.")
    try:
        await request.app.state.llm_factory(settings.shared_key).verify()
    except LLMError as exc:
        raise ApiError(502, f"The shared key didn't work: {exc.message}") from None
    return Response(status_code=204)


@router.get("/usage", response_model=list[UserUsageOut])
async def usage_by_user(db: AsyncSession = Depends(get_db),
                        month: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}$")) -> list[UserUsageOut]:
    """Per person for a month (this one by default): spending by key source, AI calls, applications and imports.
    Totals only (ADM-4)."""
    start, end = month_range(month)
    spend = {
        (owner, source): (float(cost or 0), int(calls))
        for owner, source, cost, calls in (await db.execute(
            select(AiCall.owner_id, AiCall.key_source, func.sum(AiCall.est_cost_usd), func.count())
            .where(and_(AiCall.created_at >= start, AiCall.created_at < end))
            .group_by(AiCall.owner_id, AiCall.key_source)
        )).all()
    }

    async def created(model: type[Application] | type[ImportJob]) -> dict[str, int]:
        return dict((await db.execute(
            select(model.owner_id, func.count())
            .where(and_(model.created_at >= start, model.created_at < end)).group_by(model.owner_id)
        )).all())

    apps, imports = await created(Application), await created(ImportJob)
    with_keys = set((await db.execute(select(UserApiKey.user_id))).scalars())
    out = []
    for user in (await db.execute(select(User).order_by(User.created_at))).scalars():
        own, shared = spend.get((user.id, "own"), (0.0, 0)), spend.get((user.id, "shared"), (0.0, 0))
        out.append(UserUsageOut(user_id=user.id, email=user.email, display_name=user.display_name,
                                has_api_key=user.id in with_keys, own_spend_usd=round(own[0], 4),
                                shared_spend_usd=round(shared[0], 4), calls=own[1] + shared[1],
                                applications=int(apps.get(user.id, 0)), imports=int(imports.get(user.id, 0))))
    return out
