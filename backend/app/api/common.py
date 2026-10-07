"""Small helpers shared by routers."""

from __future__ import annotations

import asyncio
from urllib.parse import quote

from fastapi import Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import passwords
from app.auth.ratelimit import FailureBackoff, SlidingWindow
from app.auth.sessions import client_ip
from app.config import Settings
from app.db.models import UploadedFile, User, UserSession
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


async def read_body(request: Request, limit: int, too_large: str) -> bytes:
    """The raw request body, refusing (413) anything over ``limit`` bytes without reading it all."""
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > limit:
        raise ApiError(413, too_large)
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > limit:
            raise ApiError(413, too_large)
    return bytes(body)


MEDIA_TYPES = {"pdf": "application/pdf",
               "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}


def file_response(request: Request, file: UploadedFile) -> Response:
    """An uploaded file as a download. The sandbox CSP keeps it inert if a browser renders it anyway."""
    data = request.app.state.files.read(file.storage_key)
    ascii_name = file.original_name.encode("ascii", "replace").decode().replace("?", "_").replace('"', "_")
    return Response(data, media_type=MEDIA_TYPES[file.kind], headers={
        "Content-Disposition": f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(file.original_name)}",
        "Content-Security-Policy": "sandbox; default-src 'none'",
    })


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
