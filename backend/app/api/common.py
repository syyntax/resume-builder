"""Small helpers shared by routers."""

from __future__ import annotations

import asyncio

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import passwords
from app.auth.ratelimit import FailureBackoff, SlidingWindow
from app.auth.sessions import client_ip
from app.config import Settings
from app.db.models import User, UserSession
from app.errors import ApiError
from app.models.api import MeOut, UserOut
from app.services import settings_store


def user_out(user: User) -> UserOut:
    return UserOut.model_validate(user, from_attributes=True)


async def me_out(db: AsyncSession, user: User, session: UserSession, settings: Settings) -> MeOut:
    notices: list[str] = []
    if user.role == "admin" and not settings.base_is_local:
        policy = await settings_store.registration_policy(db)
        if policy.mode == "open" and not policy.domains:
            notices.append("open-registration-exposed")
    return MeOut(user=user_out(user), csrf_token=session.csrf_token, notices=notices)


def enforce_window(limiter: SlidingWindow, request: Request, message: str) -> None:
    key = client_ip(request) or "unknown"
    if not limiter.allow(key):
        wait = limiter.retry_after(key)
        raise ApiError(429, message, headers={"Retry-After": str(wait)})


def enforce_backoff(limiter: FailureBackoff, key: str) -> None:
    wait = limiter.retry_after(key)
    if wait:
        raise ApiError(429, f"Too many failed attempts. Try again in {wait} seconds.",
                       headers={"Retry-After": str(wait)})


def require_password_policy(password: str, *, email: str, display_name: str, field: str = "password") -> None:
    problems = passwords.policy_errors(password, email=email, display_name=display_name)
    if problems:
        raise ApiError(422, "Choose a stronger password.",
                       errors=[{"field": field, "message": p} for p in problems])


async def hash_password(password: str) -> str:
    return await asyncio.to_thread(passwords.hash_password, password)


async def verify_password(stored_hash: str, password: str) -> tuple[bool, str | None]:
    return await asyncio.to_thread(passwords.verify_password, stored_hash, password)


async def dummy_verify(password: str) -> None:
    await asyncio.to_thread(passwords.dummy_verify, password)
