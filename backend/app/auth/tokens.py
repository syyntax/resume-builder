"""Single-use tokens (setup, invite, password reset). Raw values are shown once; only hashes are stored."""

from __future__ import annotations

import secrets
from datetime import timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.sessions import hash_token
from app.db.models import AuthToken
from app.db.types import utcnow

SETUP_TTL = timedelta(hours=24)
INVITE_TTL = timedelta(days=7)
RESET_TTL = timedelta(minutes=30)
VERIFY_TTL = timedelta(hours=24)


async def create_token(
    db: AsyncSession,
    purpose: str,
    ttl: timedelta,
    *,
    user_id: str | None = None,
    email: str | None = None,
    created_by: str | None = None,
) -> tuple[str, AuthToken]:
    raw = secrets.token_urlsafe(32)
    now = utcnow()
    token = AuthToken(
        purpose=purpose,
        token_hash=hash_token(raw),
        user_id=user_id,
        email=email,
        created_by=created_by,
        created_at=now,
        expires_at=now + ttl,
    )
    db.add(token)
    await db.flush()
    return raw, token


async def peek_token(db: AsyncSession, purpose: str, raw: str) -> AuthToken | None:
    """Return the token if it is valid (unused and unexpired) without consuming it."""
    if not raw or len(raw) > 200:
        return None
    token = (
        await db.execute(
            select(AuthToken).where(AuthToken.token_hash == hash_token(raw), AuthToken.purpose == purpose)
        )
    ).scalar_one_or_none()
    if token is None or token.used_at is not None or token.expires_at <= utcnow():
        return None
    return token


async def consume_token(db: AsyncSession, token: AuthToken) -> bool:
    """Atomically mark a token used. Returns False if another request consumed it first."""
    now = utcnow()
    result = await db.execute(
        update(AuthToken)
        .where(AuthToken.id == token.id, AuthToken.used_at.is_(None), AuthToken.expires_at > now)
        .values(used_at=now)
    )
    if getattr(result, "rowcount", 0) != 1:
        return False
    token.used_at = now
    return True


async def delete_unused(db: AsyncSession, purpose: str, *, user_id: str | None = None) -> None:
    stmt = delete(AuthToken).where(AuthToken.purpose == purpose, AuthToken.used_at.is_(None))
    if user_id is not None:
        stmt = stmt.where(AuthToken.user_id == user_id)
    await db.execute(stmt)
