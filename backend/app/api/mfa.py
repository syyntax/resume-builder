"""Two-step verification (DESIGN.md §8.2, AUTH-9): set up, confirm, finish signing in, recovery codes, turn off.

Signing in with it on is two steps: the password opens a pending session (5 minutes) that's only good for
POST /verify, which replaces it with a full session. When an admin requires it and it isn't set up yet, the
password opens an "enroll" session instead, good only for setting it up.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.common import confirm_password, enforce_backoff, enforce_window, me_out
from app.auth import mfa, totp
from app.auth.audit import audit
from app.auth.deps import current_user, get_limits, get_settings, session_stage, signing_in
from app.auth.ratelimit import Limits
from app.auth.sessions import AuthContext, create_session, revoke_all, set_session_cookie
from app.config import Settings
from app.db.engine import get_db
from app.db.types import utcnow
from app.errors import ApiError
from app.models.api import (
    MeOut,
    MfaCodeIn,
    MfaDisableIn,
    MfaEnableOut,
    MfaSetupIn,
    MfaSetupOut,
    MfaStatusOut,
    PasswordConfirmIn,
    RecoveryCodesOut,
)
from app.services import settings_store

router = APIRouter(prefix="/api/auth/mfa", tags=["auth"])
WRONG_CODE = "That code didn't work. Codes change every 30 seconds: check that your phone's clock is right."


def _required(request: Request, ctx: AuthContext) -> bool:
    return settings_store.mfa_required(ctx.user.role, getattr(request.app.state, "mfa_policy", "none"))


async def _full_session(db: AsyncSession, ctx: AuthContext, request: Request, response: Response,
                        settings: Settings) -> MeOut:
    """Replace the session with a new, complete one (a new id whenever the sign-in level changes, §8.3)."""
    remember = ctx.session.remember
    await db.delete(ctx.session)
    raw, session = await create_session(db, ctx.user, request, settings, remember=remember)
    set_session_cookie(response, raw, remember=remember, settings=settings)
    return await me_out(db, ctx.user, session, settings)


@router.get("", response_model=MfaStatusOut)
async def mfa_status(request: Request, ctx: AuthContext = Depends(signing_in),
                     db: AsyncSession = Depends(get_db)) -> MfaStatusOut:
    left = await mfa.recovery_codes_left(db, ctx.user) if ctx.user.mfa_enabled else 0
    return MfaStatusOut(enabled=ctx.user.mfa_enabled, required=_required(request, ctx), recovery_codes_left=left)


@router.post("/setup", response_model=MfaSetupOut)
async def setup(body: MfaSetupIn, request: Request, ctx: AuthContext = Depends(signing_in),
                db: AsyncSession = Depends(get_db), settings: Settings = Depends(get_settings),
                limits: Limits = Depends(get_limits)) -> MfaSetupOut:
    """Start setting it up: a new secret to add to an authenticator app. Nothing changes until it's confirmed."""
    stage = session_stage(request, ctx)
    if stage == "mfa":
        raise ApiError(401, "Finish signing in first.")
    if ctx.user.mfa_enabled:
        raise ApiError(409, "Two-step verification is already on. Turn it off first to move it to a new app.")
    if ctx.session.stage != "enroll":  # a session made by the password moments ago doesn't need it again
        if not body.password:
            raise ApiError(400, "Enter your password to set this up.",
                           errors=[{"field": "password", "message": "required"}])
        await confirm_password(ctx, body.password, limits)
    secret = totp.new_secret()
    mfa.store_secret(ctx.user, secret, settings)
    await db.commit()
    uri = totp.otpauth_uri(secret, ctx.user.email)
    return MfaSetupOut(secret=secret, otpauth_uri=uri, qr_svg=mfa.qr_svg(uri))


@router.post("/enable", response_model=MfaEnableOut)
async def enable(body: MfaCodeIn, request: Request, response: Response, ctx: AuthContext = Depends(signing_in),
                 db: AsyncSession = Depends(get_db), settings: Settings = Depends(get_settings),
                 limits: Limits = Depends(get_limits)) -> MfaEnableOut:
    """Confirm with a code from the app. Turns it on, signs out other sessions, and returns recovery codes."""
    if session_stage(request, ctx) == "mfa":
        raise ApiError(401, "Finish signing in first.")
    if ctx.user.mfa_enabled:
        raise ApiError(409, "Two-step verification is already on.")
    secret = mfa.read_secret(ctx.user, settings)
    if secret is None:
        raise ApiError(409, "Start setting it up first.")
    enforce_backoff(limits.mfa_account, ctx.user.id)
    step = totp.verify(secret, body.code, last_step=None)
    if step is None:
        limits.mfa_account.failure(ctx.user.id)
        raise ApiError(422, WRONG_CODE, errors=[{"field": "code", "message": "didn't match"}])
    limits.mfa_account.reset(ctx.user.id)
    ctx.user.mfa_enabled, ctx.user.totp_last_step = True, step
    codes = await mfa.new_recovery_codes(db, ctx.user)
    if ctx.session.stage == "enroll":
        ctx.user.last_login_at = utcnow()
    await revoke_all(db, ctx.user.id, except_session_id=ctx.session.id)  # they signed in without it
    await audit(db, "auth.mfa.enabled", request, actor_id=ctx.user.id, target_id=ctx.user.id)
    me = await _full_session(db, ctx, request, response, settings)
    await db.commit()
    return MfaEnableOut(recovery_codes=codes, me=me)


@router.post("/verify", response_model=MeOut)
async def verify(body: MfaCodeIn, request: Request, response: Response, ctx: AuthContext = Depends(signing_in),
                 db: AsyncSession = Depends(get_db), settings: Settings = Depends(get_settings),
                 limits: Limits = Depends(get_limits)) -> MeOut:
    """Finish signing in with a code from the authenticator app, or a recovery code."""
    if ctx.session.stage != "mfa":
        raise ApiError(409, "There's no sign-in waiting for a code.")
    enforce_window(limits.mfa_ip, request, "Too many attempts from this network. Try again later.")
    enforce_backoff(limits.mfa_account, ctx.user.id)
    method = await mfa.check_code(db, ctx.user, body.code, settings)
    if method is None:
        limits.mfa_account.failure(ctx.user.id)
        await audit(db, "auth.mfa.failure", request, actor_id=ctx.user.id, target_id=ctx.user.id)
        await db.commit()
        raise ApiError(401, WRONG_CODE)
    limits.mfa_account.reset(ctx.user.id)
    ctx.user.last_login_at = utcnow()
    await audit(db, "auth.login.success", request, actor_id=ctx.user.id, target_id=ctx.user.id, mfa=method)
    me = await _full_session(db, ctx, request, response, settings)
    if method == "recovery":
        me.notices.append("recovery-code-used")
    await db.commit()
    return me


@router.post("/recovery-codes", response_model=RecoveryCodesOut)
async def regenerate_recovery_codes(body: PasswordConfirmIn, request: Request,
                                    ctx: AuthContext = Depends(current_user), db: AsyncSession = Depends(get_db),
                                    limits: Limits = Depends(get_limits)) -> RecoveryCodesOut:
    """Ten new recovery codes; the old ones stop working."""
    if not ctx.user.mfa_enabled:
        raise ApiError(409, "Two-step verification is off.")
    await confirm_password(ctx, body.password, limits)
    codes = await mfa.new_recovery_codes(db, ctx.user)
    await audit(db, "auth.mfa.recovery_codes", request, actor_id=ctx.user.id, target_id=ctx.user.id)
    await db.commit()
    return RecoveryCodesOut(recovery_codes=codes)


@router.post("/disable", response_model=MfaStatusOut)
async def disable(body: MfaDisableIn, request: Request, ctx: AuthContext = Depends(current_user),
                  db: AsyncSession = Depends(get_db), settings: Settings = Depends(get_settings),
                  limits: Limits = Depends(get_limits)) -> MfaStatusOut:
    """Turn it off, with the password and a current code (or a recovery code)."""
    if not ctx.user.mfa_enabled:
        raise ApiError(409, "Two-step verification is already off.")
    if _required(request, ctx):
        raise ApiError(409, "Your administrator requires two-step verification for your account.")
    await confirm_password(ctx, body.password, limits)
    enforce_backoff(limits.mfa_account, ctx.user.id)
    if await mfa.check_code(db, ctx.user, body.code, settings) is None:
        limits.mfa_account.failure(ctx.user.id)
        raise ApiError(422, WRONG_CODE, errors=[{"field": "code", "message": "didn't match"}])
    limits.mfa_account.reset(ctx.user.id)
    await mfa.turn_off(db, ctx.user)
    await audit(db, "auth.mfa.disabled", request, actor_id=ctx.user.id, target_id=ctx.user.id)
    await db.commit()
    return MfaStatusOut(enabled=False, required=False, recovery_codes_left=0)
