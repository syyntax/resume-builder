"""Defaults for a user's new applications and exports: their own preferences, then the instance's."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User
from app.models.api import DefaultDesign, Preferences
from app.render.service import stored_design
from app.services import settings_store


def preferences(user: User) -> Preferences:
    try:
        return Preferences.model_validate(user.preferences or {})
    except ValueError:  # stored before a field changed: fall back rather than fail
        return Preferences()


async def instance_design(db: AsyncSession) -> DefaultDesign:
    stored = await settings_store.get_value(db, settings_store.DEFAULT_DESIGN, {}) or {}
    template, theme = stored_design(stored.get("template"), stored.get("theme"))
    return DefaultDesign(template=template, theme=theme)


async def design_for(db: AsyncSession, user: User) -> DefaultDesign:
    own = preferences(user).design
    if own is not None:
        template, theme = stored_design(own.template, own.theme.model_dump(mode="json", by_alias=True))
        return DefaultDesign(template=template, theme=theme)
    return await instance_design(db)
