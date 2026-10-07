"""Users' own API keys and the optional shared key (DESIGN.md §8.6)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import User, UserApiKey
from app.db.types import utcnow
from app.errors import ApiError
from app.secrets import DecryptionError, Sealed, SecretBox
from app.services import settings_store

PURPOSE = "user-api-key"
KEY_PATTERN = re.compile(r"^sk-ant-[A-Za-z0-9_\-]{16,300}$")


def secret_box(settings: Settings) -> SecretBox:
    return SecretBox(settings.secret_key(), PURPOSE, previous=settings.previous_secret_key())


def check_format(raw: str) -> str:
    key = raw.strip()
    if not KEY_PATTERN.match(key):
        raise ApiError(422, "That doesn't look like an Anthropic API key. Keys start with \"sk-ant-\".",
                       errors=[{"field": "apiKey", "message": "invalid format"}])
    return key


async def get_row(db: AsyncSession, user_id: str) -> UserApiKey | None:
    return (await db.execute(select(UserApiKey).where(UserApiKey.user_id == user_id))).scalar_one_or_none()


async def store(db: AsyncSession, user: User, key: str, settings: Settings) -> UserApiKey:
    sealed = secret_box(settings).seal(key, bound_to=user.id)
    row = await get_row(db, user.id)
    if row is None:
        row = UserApiKey(user_id=user.id, created_at=utcnow())
        db.add(row)
    row.ciphertext, row.nonce, row.key_fingerprint = sealed.ciphertext, sealed.nonce, sealed.key_fingerprint
    row.hint = key[-4:]
    row.status, row.verified_at = "valid", utcnow()
    return row


def decrypt(row: UserApiKey, settings: Settings) -> str:
    return secret_box(settings).open(Sealed(row.ciphertext, row.nonce, row.key_fingerprint), bound_to=row.user_id)


async def shared_key_enabled(db: AsyncSession, settings: Settings) -> bool:
    allowed = await settings_store.get_value(db, settings_store.ALLOW_SHARED_KEY, False)
    return bool(settings.shared_key) and bool(allowed)


@dataclass
class ResolvedKey:
    api_key: str
    source: Literal["own", "shared"]
    row: UserApiKey | None = None


class NoUsableKey(ApiError):
    def __init__(self, message: str) -> None:
        super().__init__(409, message, extra={"code": "no_api_key"})


async def resolve(db: AsyncSession, user: User, settings: Settings) -> ResolvedKey:
    """The user's own valid key, else the shared key if an admin allows it, else NoUsableKey."""
    row = await get_row(db, user.id)
    if row is not None and row.status == "valid":
        try:
            return ResolvedKey(decrypt(row, settings), "own", row)
        except DecryptionError:
            raise NoUsableKey("Your saved API key can't be read anymore (the server's secret changed). "
                              "Enter it again in Account → AI.") from None
    if await shared_key_enabled(db, settings):
        return ResolvedKey(settings.shared_key or "", "shared")
    if row is not None:
        raise NoUsableKey("Anthropic rejected your API key. Replace it in Account → AI.")
    raise NoUsableKey("Add your Anthropic API key in Account → AI before generating.")
