"""FastAPI dependencies for authentication, CSRF and origin checks."""

from __future__ import annotations

import hmac

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.ratelimit import Limits
from app.auth.sessions import AuthContext, cookie_name, resolve_session
from app.config import Settings, origin_of
from app.db.engine import get_db
from app.errors import ApiError

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
CSRF_HEADER = "x-csrf-token"


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_limits(request: Request) -> Limits:
    return request.app.state.limits


def check_origin(request: Request, settings: Settings) -> None:
    """Reject state-changing requests that don't come from this app's own origin."""
    origin = request.headers.get("origin")
    if origin is None:
        referer = request.headers.get("referer")
        origin = origin_of(referer) if referer else None
    if not origin or origin.lower() not in settings.trusted_origins:
        raise ApiError(403, "Request blocked: it did not come from this app.")


async def origin_guard(request: Request, settings: Settings = Depends(get_settings)) -> None:
    """For public endpoints that change state (login, register, setup, password reset)."""
    if request.method not in SAFE_METHODS:
        check_origin(request, settings)


async def optional_auth(
    request: Request, db: AsyncSession = Depends(get_db), settings: Settings = Depends(get_settings)
) -> AuthContext | None:
    raw = request.cookies.get(cookie_name(settings))
    if not raw or len(raw) > 200:
        return None
    return await resolve_session(db, raw, settings)


async def current_user(
    request: Request,
    ctx: AuthContext | None = Depends(optional_auth),
    settings: Settings = Depends(get_settings),
) -> AuthContext:
    if ctx is None:
        raise ApiError(401, "You're not signed in.")
    if request.method not in SAFE_METHODS:
        check_origin(request, settings)
        sent = request.headers.get(CSRF_HEADER, "")
        if not hmac.compare_digest(sent.encode(), ctx.session.csrf_token.encode()):
            raise ApiError(403, "Missing or invalid CSRF token. Reload the page and try again.")
    return ctx


async def require_admin(ctx: AuthContext = Depends(current_user)) -> AuthContext:
    if ctx.user.role != "admin":
        raise ApiError(403, "This action is limited to admins.")
    return ctx
