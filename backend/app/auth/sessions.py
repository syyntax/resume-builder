"""Server-side sessions: an opaque 256-bit token in an HttpOnly cookie; only its SHA-256 is stored."""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import timedelta

from fastapi import Request, Response
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import User, UserSession
from app.db.types import utcnow

SHORT_IDLE = timedelta(hours=12)  # sessions without "remember me"
_SLIDE_EVERY = timedelta(minutes=1)


@dataclass
class AuthContext:
    user: User
    session: UserSession


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def cookie_name(settings: Settings) -> str:
    # The __Host- prefix requires Secure, Path=/ and no Domain, which pins the cookie to this origin.
    return "__Host-rt_session" if settings.is_https else "rt_session"


def client_ip(request: Request) -> str | None:
    # Uvicorn rewrites request.client from X-Forwarded-For only for TRUSTED_PROXIES (--forwarded-allow-ips).
    return request.client.host if request.client else None


def user_agent(request: Request) -> str | None:
    ua = request.headers.get("user-agent")
    return ua[:300] if ua else None


def _idle_ttl(remember: bool, settings: Settings) -> timedelta:
    return timedelta(days=settings.session_idle_days) if remember else SHORT_IDLE


async def create_session(
    db: AsyncSession, user: User, request: Request, settings: Settings, *, remember: bool
) -> tuple[str, UserSession]:
    raw = secrets.token_urlsafe(32)
    now = utcnow()
    absolute = now + timedelta(days=settings.session_max_days)
    session = UserSession(
        user_id=user.id,
        token_hash=hash_token(raw),
        csrf_token=secrets.token_urlsafe(32),
        remember=remember,
        created_at=now,
        last_seen_at=now,
        idle_expires_at=min(now + _idle_ttl(remember, settings), absolute),
        absolute_expires_at=absolute,
        ip=client_ip(request),
        user_agent=user_agent(request),
    )
    db.add(session)
    return raw, session


async def resolve_session(db: AsyncSession, raw: str, settings: Settings) -> AuthContext | None:
    row = (
        await db.execute(
            select(UserSession, User).join(User, User.id == UserSession.user_id).where(
                UserSession.token_hash == hash_token(raw)
            )
        )
    ).first()
    if row is None:
        return None
    session, user = row
    now = utcnow()
    if session.idle_expires_at <= now or session.absolute_expires_at <= now or user.status != "active":
        await db.delete(session)
        await db.commit()
        return None
    if now - session.last_seen_at >= _SLIDE_EVERY:
        session.last_seen_at = now
        session.idle_expires_at = min(now + _idle_ttl(session.remember, settings), session.absolute_expires_at)
        await db.commit()
    return AuthContext(user=user, session=session)


def set_session_cookie(response: Response, raw: str, *, remember: bool, settings: Settings) -> None:
    response.set_cookie(
        cookie_name(settings),
        raw,
        max_age=settings.session_max_days * 86400 if remember else None,
        httponly=True,
        secure=settings.is_https,
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(cookie_name(settings), path="/", secure=settings.is_https, httponly=True)


async def revoke_presented_session(db: AsyncSession, request: Request, settings: Settings) -> None:
    """On login, drop whatever session the browser already holds (prevents session fixation)."""
    raw = request.cookies.get(cookie_name(settings))
    if raw:
        await db.execute(delete(UserSession).where(UserSession.token_hash == hash_token(raw)))


async def revoke_all(db: AsyncSession, user_id: str, *, except_session_id: str | None = None) -> int:
    stmt = delete(UserSession).where(UserSession.user_id == user_id)
    if except_session_id:
        stmt = stmt.where(UserSession.id != except_session_id)
    result = await db.execute(stmt)
    return int(getattr(result, "rowcount", 0) or 0)


async def purge_expired(db: AsyncSession) -> None:
    now = utcnow()
    await db.execute(
        delete(UserSession).where((UserSession.idle_expires_at <= now) | (UserSession.absolute_expires_at <= now))
    )
