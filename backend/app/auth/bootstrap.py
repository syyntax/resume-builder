"""First-run setup: while no users exist, a one-time token (printed to the logs) is needed to create the
first admin. Each restart replaces any unused token, so a lost token is recovered by restarting."""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import tokens
from app.config import Settings
from app.services.users import count_users

log = logging.getLogger("resume_tailor.setup")


async def ensure_setup_token(db: AsyncSession) -> str | None:
    """Return a fresh setup token if setup is still pending, else None (and clear leftovers)."""
    await tokens.delete_unused(db, "setup")
    if await count_users(db) > 0:
        await db.commit()
        return None
    raw, _ = await tokens.create_token(db, "setup", tokens.SETUP_TTL)
    await db.commit()
    return raw


def announce_setup_token(token: str, settings: Settings) -> None:
    bar = "=" * 72
    log.warning(
        "\n%s\n Resume Tailor first-run setup\n Open %s/setup and create the admin account.\n"
        " Setup token: %s\n (valid for 24 hours; restart the app to get a new one)\n%s",
        bar, settings.app_base_url, token, bar,
    )
