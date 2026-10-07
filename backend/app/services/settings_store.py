"""Admin-editable system settings, stored in the database and seeded from the environment."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.models import SystemSetting
from app.db.types import utcnow

REGISTRATION_MODE = "registration_mode"
REGISTRATION_DOMAINS = "registration_email_domains"
ALLOW_SHARED_KEY = "allow_shared_key"
DEFAULT_MODEL = "default_model"
ALLOWED_MODELS = "allowed_models"


@dataclass
class RegistrationPolicy:
    mode: str
    domains: list[str]

    def allows_domain(self, email: str) -> bool:
        if not self.domains:
            return True
        return email.rsplit("@", 1)[-1].lower() in self.domains


async def init_defaults(db: AsyncSession, settings: Settings) -> None:
    defaults: dict[str, Any] = {
        REGISTRATION_MODE: settings.registration_mode,
        REGISTRATION_DOMAINS: settings.email_domain_allowlist,
        ALLOW_SHARED_KEY: settings.allow_shared_key,
        DEFAULT_MODEL: settings.anthropic_model,
        ALLOWED_MODELS: sorted({*settings.allowed_model_list, settings.anthropic_model}),
    }
    for key, value in defaults.items():
        if await db.get(SystemSetting, key) is None:
            db.add(SystemSetting(key=key, value=value, updated_at=utcnow()))
    await db.commit()


async def get_value(db: AsyncSession, key: str, default: Any = None) -> Any:
    row = await db.get(SystemSetting, key)
    return default if row is None else row.value


async def set_value(db: AsyncSession, key: str, value: Any, *, updated_by: str | None) -> None:
    row = await db.get(SystemSetting, key)
    if row is None:
        db.add(SystemSetting(key=key, value=value, updated_by=updated_by, updated_at=utcnow()))
    else:
        row.value, row.updated_by, row.updated_at = value, updated_by, utcnow()


async def registration_policy(db: AsyncSession) -> RegistrationPolicy:
    return RegistrationPolicy(
        mode=str(await get_value(db, REGISTRATION_MODE, "open")),
        domains=list(await get_value(db, REGISTRATION_DOMAINS, [])),
    )


@dataclass
class ModelPolicy:
    default: str
    allowed: list[str]

    def choose(self, preferred: str | None) -> str:
        return preferred if preferred in self.allowed else self.default


async def model_policy(db: AsyncSession) -> ModelPolicy:
    default = str(await get_value(db, DEFAULT_MODEL, "claude-opus-5-5"))
    allowed = list(await get_value(db, ALLOWED_MODELS, [default]))
    return ModelPolicy(default=default, allowed=allowed if default in allowed else [default, *allowed])
