"""Setup, registration, sign-in, sessions and password reset (DESIGN.md §8)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.common import (
    dummy_verify,
    enforce_backoff,
    enforce_window,
    hash_password,
    me_out,
    require_password_policy,
    verify_password,
)
from app.auth import tokens
from app.auth.audit import audit
from app.auth.deps import current_user, get_limits, get_settings, origin_guard, session_stage, signing_in
from app.auth.ratelimit import Limits
from app.auth.sessions import (
    AuthContext,
    clear_session_cookie,
    client_ip,
    create_session,
    revoke_all,
    revoke_presented_session,
    set_session_cookie,
)
from app.config import Settings
from app.db.engine import get_db
from app.db.models import User, UserSession
from app.db.types import utcnow
from app.errors import ApiError
from app.models.api import (
    ForgotPasswordIn,
    LoginIn,
    MeOut,
    PasswordChangeIn,
    PasswordResetIn,
    RegisterIn,
    RegistrationInfoOut,
    SessionOut,
    SetupIn,
    SetupStatusOut,
    TokenCheckOut,
    VerificationSentOut,
    VerifyEmailIn,
)
from app.services import mail, settings_store
from app.services.users import count_users, find_by_email, is_valid_email, normalize_email

router = APIRouter(prefix="/api/auth", tags=["auth"])

INVALID_LOGIN = "Invalid email or password."


def _check_email(email: str) -> str:
    normalized = normalize_email(email)
    if not is_valid_email(normalized):
        raise ApiError(422, "Enter a valid email address.", errors=[{"field": "email", "message": "invalid"}])
    return normalized


async def _start_session(
    db: AsyncSession, user: User, request: Request, response: Response, settings: Settings, *, remember: bool,
    stage: str = "active",
) -> UserSession:
    await revoke_presented_session(db, request, settings)
    raw, session = await create_session(db, user, request, settings, remember=remember, stage=stage)
    # a pending session's cookie ends with the browser session; "remember me" applies once sign-in completes
    set_session_cookie(response, raw, remember=remember and stage == "active", settings=settings)
    return session


async def _send_verification(db: AsyncSession, user: User, request: Request, settings: Settings) -> None:
    # Earlier links keep working: they went to the same inbox, and people often click the first email after a
    # sign-in attempt has sent another. Confirming the address clears the rest.
    raw, _ = await tokens.create_token(db, "email_verify", tokens.VERIFY_TTL, user_id=user.id, email=user.email)
    mail.send_later(request.app.state.mailer, mail.verify_address(user.email,
                                                                  f"{settings.app_base_url}/verify-email/{raw}"))


# ---- first-run setup ---------------------------------------------------------------------------------


@router.get("/setup-status", response_model=SetupStatusOut)
async def setup_status(db: AsyncSession = Depends(get_db)) -> SetupStatusOut:
    return SetupStatusOut(needs_setup=await count_users(db) == 0)


@router.post("/setup", response_model=MeOut, status_code=201, dependencies=[Depends(origin_guard)])
async def setup(
    body: SetupIn,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    limits: Limits = Depends(get_limits),
) -> MeOut:
    enforce_window(limits.setup_ip, request, "Too many setup attempts. Try again later.")
    if await count_users(db) > 0:
        raise ApiError(409, "Setup is already complete. Sign in instead.")
    token = await tokens.peek_token(db, "setup", body.token)
    if token is None:
        raise ApiError(400, "That setup token is invalid or has expired. Restart the app to get a new one.")
    email = _check_email(body.email)
    require_password_policy(body.password, email=email, display_name=body.display_name)
    if not await tokens.consume_token(db, token):
        raise ApiError(409, "That setup token was just used.")
    user = User(email=email, display_name=body.display_name, password_hash=await hash_password(body.password),
                role="admin", status="active", created_at=utcnow(), last_login_at=utcnow(),
                email_verified_at=utcnow())
    db.add(user)
    await db.flush()
    session = await _start_session(db, user, request, response, settings, remember=False)
    await audit(db, "auth.setup", request, actor_id=user.id, target_id=user.id)
    await db.commit()
    return await me_out(db, user, session, settings)


# ---- registration ---------------------------------------------------------------------------------


@router.get("/registration", response_model=RegistrationInfoOut)
async def registration_info(db: AsyncSession = Depends(get_db),
                            settings: Settings = Depends(get_settings)) -> RegistrationInfoOut:
    policy = await settings_store.registration_policy(db)
    return RegistrationInfoOut(
        needs_setup=await count_users(db) == 0, mode=policy.mode, domain_restricted=bool(policy.domains),  # type: ignore[arg-type]
        email_enabled=settings.smtp_enabled,
    )


@router.get("/invites/{token}", response_model=TokenCheckOut)
async def check_invite(
    token: str, request: Request, db: AsyncSession = Depends(get_db), limits: Limits = Depends(get_limits)
) -> TokenCheckOut:
    enforce_window(limits.token_ip, request, "Too many requests. Try again later.")
    invite = await tokens.peek_token(db, "invite", token)
    return TokenCheckOut(valid=invite is not None, email=invite.email if invite else None)


@router.post("/register", response_model=MeOut | VerificationSentOut, status_code=201,
             dependencies=[Depends(origin_guard)])
async def register(
    body: RegisterIn,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    limits: Limits = Depends(get_limits),
) -> MeOut | VerificationSentOut:
    """Create an account. With SMTP configured, an open sign-up confirms its address first (AUTH-10): the
    answer is then 202 "check your email", whether or not the address already has an account (§8.4)."""
    enforce_window(limits.register_ip, request, "Too many sign-up attempts from this network. Try again later.")
    if await count_users(db) == 0:
        raise ApiError(409, "Finish first-run setup before registering accounts.")
    policy = await settings_store.registration_policy(db)
    if policy.mode == "closed":
        raise ApiError(403, "Registration is closed. Ask an admin for an account.")
    email = _check_email(body.email)
    invite = None
    if body.invite_token:
        invite = await tokens.peek_token(db, "invite", body.invite_token)
        if invite is None:
            raise ApiError(400, "This invite link is invalid or has expired.")
        if invite.email and invite.email != email:
            raise ApiError(400, "This invite is for a different email address.")
    elif policy.mode == "invite":
        raise ApiError(403, "Registration requires an invite. Ask an admin for an invite link.")
    elif not policy.allows_domain(email):
        raise ApiError(403, "Registration is limited to approved email domains.")
    verify = settings.smtp_enabled and invite is None  # an invite link already went to (or for) the address
    require_password_policy(body.password, email=email, display_name=body.display_name)
    if await find_by_email(db, email) is not None:
        if not verify:
            raise ApiError(409, "An account with this email already exists. Sign in instead.")
        await hash_password(body.password)  # the same work as a real sign-up, so timing tells nothing
        mail.send_later(request.app.state.mailer, mail.already_registered(
            email, f"{settings.app_base_url}/login", f"{settings.app_base_url}/forgot-password"))
        await audit(db, "user.register.duplicate", request, email=email)
        await db.commit()
        response.status_code = 202
        return VerificationSentOut(email=email)
    if invite is not None and not await tokens.consume_token(db, invite):
        raise ApiError(400, "This invite link has already been used.")

    now = utcnow()
    user = User(email=email, display_name=body.display_name, password_hash=await hash_password(body.password),
                role="user", status="active", created_at=now, last_login_at=None if verify else now,
                email_verified_at=None if verify else now)
    db.add(user)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise ApiError(409, "An account with this email already exists. Sign in instead.") from None
    if verify:
        await _send_verification(db, user, request, settings)
        await audit(db, "user.register", request, actor_id=user.id, target_id=user.id, via="open", verify=True)
        await db.commit()
        response.status_code = 202
        return VerificationSentOut(email=email)
    session = await _start_session(db, user, request, response, settings, remember=False)
    await audit(db, "user.register", request, actor_id=user.id, target_id=user.id, via="invite" if invite else "open")
    if invite is not None:
        await audit(db, "user.invite.accept", request, actor_id=user.id, target_id=user.id, invite_id=invite.id)
    await db.commit()
    return await me_out(db, user, session, settings)


# ---- sign-in ----------------------------------------------------------------------------------------


@router.post("/login", response_model=MeOut, dependencies=[Depends(origin_guard)])
async def login(
    body: LoginIn,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    limits: Limits = Depends(get_limits),
) -> MeOut:
    ip = client_ip(request) or "unknown"
    email = normalize_email(body.email)
    if limits.login_ip.count(ip) >= limits.login_ip.limit:
        wait = limits.login_ip.retry_after(ip)
        raise ApiError(429, "Too many failed sign-in attempts from this network. Try again later.",
                       headers={"Retry-After": str(wait)})
    enforce_backoff(limits.login_account, email)

    user = await find_by_email(db, email)
    upgraded: str | None = None
    if user is None:
        await dummy_verify(body.password)
        ok = False
    else:
        ok, upgraded = await verify_password(user.password_hash, body.password)
    if not ok or user is None or user.status != "active":
        limits.login_ip.hit(ip)
        limits.login_account.failure(email)
        await audit(db, "auth.login.failure", request, target_id=user.id if user else None, email=email)
        await db.commit()
        raise ApiError(401, INVALID_LOGIN)

    limits.login_account.reset(email)
    if upgraded:
        user.password_hash = upgraded
    if user.email_verified_at is None:
        if limits.email_ip.allow(ip):
            await _send_verification(db, user, request, settings)
        await db.commit()
        raise ApiError(403, f"Confirm your email first: we've sent a link to {user.email}.",
                       extra={"code": "email_unverified"})
    # With two-step verification on, the password only opens a short pending session for the code (§8.2).
    policy = getattr(request.app.state, "mfa_policy", "none")
    stage = "mfa" if user.mfa_enabled else "enroll" if settings_store.mfa_required(user.role, policy) else "active"
    session = await _start_session(db, user, request, response, settings, remember=body.remember, stage=stage)
    if stage == "active":
        user.last_login_at = utcnow()
        await audit(db, "auth.login.success", request, actor_id=user.id, target_id=user.id)
    else:
        await audit(db, "auth.login.password_ok", request, actor_id=user.id, target_id=user.id, next=stage)
    await db.commit()
    return await me_out(db, user, session, settings, stage)


@router.post("/logout", status_code=204)
async def logout(
    request: Request,
    ctx: AuthContext = Depends(signing_in),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Response:
    await db.delete(ctx.session)
    await audit(db, "auth.logout", request, actor_id=ctx.user.id, target_id=ctx.user.id)
    await db.commit()
    response = Response(status_code=204)
    clear_session_cookie(response, settings)
    return response


@router.get("/me", response_model=MeOut)
async def me(
    request: Request,
    ctx: AuthContext = Depends(signing_in),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> MeOut:
    """Who's signed in, and what's left of signing in (a code, or setting up two-step verification)."""
    return await me_out(db, ctx.user, ctx.session, settings, session_stage(request, ctx))


# ---- passwords -------------------------------------------------------------------------------------


@router.post("/password/change", response_model=MeOut)
async def change_password(
    body: PasswordChangeIn,
    request: Request,
    response: Response,
    ctx: AuthContext = Depends(current_user),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    limits: Limits = Depends(get_limits),
) -> MeOut:
    user = ctx.user
    enforce_backoff(limits.password_check, user.id)
    ok, _ = await verify_password(user.password_hash, body.current_password)
    if not ok:
        limits.password_check.failure(user.id)
        raise ApiError(400, "Your current password is incorrect.",
                       errors=[{"field": "currentPassword", "message": "incorrect"}])
    limits.password_check.reset(user.id)
    require_password_policy(body.new_password, email=user.email, display_name=user.display_name,
                            field="newPassword")
    user.password_hash = await hash_password(body.new_password)
    await revoke_all(db, user.id)  # every session, including this one
    session = await _start_session(db, user, request, response, settings, remember=ctx.session.remember)
    await audit(db, "auth.password.change", request, actor_id=user.id, target_id=user.id)
    await db.commit()
    return await me_out(db, user, session, settings)


@router.get("/password-reset/{token}", response_model=TokenCheckOut)
async def check_reset_token(
    token: str, request: Request, db: AsyncSession = Depends(get_db), limits: Limits = Depends(get_limits)
) -> TokenCheckOut:
    enforce_window(limits.token_ip, request, "Too many requests. Try again later.")
    return TokenCheckOut(valid=await tokens.peek_token(db, "password_reset", token) is not None)


@router.post("/password-reset", status_code=204, dependencies=[Depends(origin_guard)])
async def reset_password(
    body: PasswordResetIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    limits: Limits = Depends(get_limits),
) -> Response:
    enforce_window(limits.token_ip, request, "Too many requests. Try again later.")
    token = await tokens.peek_token(db, "password_reset", body.token)
    user = await db.get(User, token.user_id) if token and token.user_id else None
    if token is None or user is None:
        raise ApiError(400, "This reset link is invalid or has expired. Ask for a new one.")
    require_password_policy(body.new_password, email=user.email, display_name=user.display_name,
                            field="newPassword")
    if not await tokens.consume_token(db, token):
        raise ApiError(400, "This reset link has already been used.")
    user.password_hash = await hash_password(body.new_password)
    await revoke_all(db, user.id)
    await tokens.delete_unused(db, "password_reset", user_id=user.id)
    await audit(db, "auth.password.reset", request, target_id=user.id)
    await db.commit()
    response = Response(status_code=204)
    clear_session_cookie(response, settings)
    return response


@router.post("/password/forgot", status_code=202, dependencies=[Depends(origin_guard)])
async def forgot_password(
    body: ForgotPasswordIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    limits: Limits = Depends(get_limits),
) -> Response:
    """Email a reset link (AUTH-7, when SMTP is configured). Always 202, whether or not the account exists."""
    if not settings.smtp_enabled:
        raise ApiError(404, "Password resets by email aren't set up here. Ask an admin for a reset link.")
    enforce_window(limits.email_ip, request, "Too many requests from this network. Try again later.")
    user = await find_by_email(db, normalize_email(body.email))
    if user is not None and user.status == "active":
        await tokens.delete_unused(db, "password_reset", user_id=user.id)
        raw, _ = await tokens.create_token(db, "password_reset", tokens.RESET_TTL, user_id=user.id)
        mail.send_later(request.app.state.mailer, mail.password_reset(user.email,
                                                                      f"{settings.app_base_url}/reset-password/{raw}"))
        await audit(db, "auth.password.forgot", request, target_id=user.id)
        await db.commit()
    return Response(status_code=202)


@router.post("/verify-email", status_code=204, dependencies=[Depends(origin_guard)])
async def verify_email(
    body: VerifyEmailIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    limits: Limits = Depends(get_limits),
) -> Response:
    """Confirm an address from the emailed link (AUTH-10). Then sign in as usual."""
    enforce_window(limits.token_ip, request, "Too many requests. Try again later.")
    token = await tokens.peek_token(db, "email_verify", body.token)
    user = await db.get(User, token.user_id) if token and token.user_id else None
    if token is None or user is None or token.email != user.email:
        raise ApiError(400, "This link is invalid or has expired. Sign in to get a new one.")
    if not await tokens.consume_token(db, token):
        raise ApiError(400, "This link has already been used, so your email is confirmed. You can sign in.")
    user.email_verified_at = utcnow()
    await tokens.delete_unused(db, "email_verify", user_id=user.id)
    await audit(db, "user.email.verified", request, target_id=user.id)
    await db.commit()
    return Response(status_code=204)


# ---- sessions --------------------------------------------------------------------------------------


@router.get("/sessions", response_model=list[SessionOut])
async def list_sessions(
    ctx: AuthContext = Depends(current_user), db: AsyncSession = Depends(get_db)
) -> list[SessionOut]:
    rows = (
        await db.execute(
            select(UserSession).where(UserSession.user_id == ctx.user.id).order_by(UserSession.last_seen_at.desc())
        )
    ).scalars()
    return [
        SessionOut(id=s.id, created_at=s.created_at, last_seen_at=s.last_seen_at,
                   expires_at=min(s.idle_expires_at, s.absolute_expires_at), ip=s.ip, user_agent=s.user_agent,
                   current=s.id == ctx.session.id)
        for s in rows
    ]


@router.delete("/sessions/{session_id}", status_code=204)
async def revoke_session(
    session_id: str, request: Request, ctx: AuthContext = Depends(current_user), db: AsyncSession = Depends(get_db)
) -> Response:
    session = (
        await db.execute(
            select(UserSession).where(UserSession.id == session_id, UserSession.user_id == ctx.user.id)
        )
    ).scalar_one_or_none()
    if session is None:
        raise ApiError(404, "Session not found.")
    await db.delete(session)
    await audit(db, "session.revoke", request, actor_id=ctx.user.id, target_id=ctx.user.id, session_id=session_id)
    await db.commit()
    return Response(status_code=204)


@router.delete("/sessions", status_code=204)
async def revoke_other_sessions(
    request: Request, ctx: AuthContext = Depends(current_user), db: AsyncSession = Depends(get_db)
) -> Response:
    count = await revoke_all(db, ctx.user.id, except_session_id=ctx.session.id)
    await audit(db, "session.revoke", request, actor_id=ctx.user.id, target_id=ctx.user.id, others=count)
    await db.commit()
    return Response(status_code=204)
