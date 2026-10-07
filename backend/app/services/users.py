"""User lookups and invariants shared by the API and the CLI."""

from __future__ import annotations

import re

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+$")


def normalize_email(email: str) -> str:
    return email.strip().lower()


def is_valid_email(email: str) -> bool:
    # Deliberately lenient: this is a login identifier on a self-hosted app (admin@localhost is fine).
    return len(email) <= 254 and bool(_EMAIL_RE.match(email))


async def count_users(db: AsyncSession) -> int:
    return int((await db.execute(select(func.count()).select_from(User))).scalar_one())


async def find_by_email(db: AsyncSession, email: str) -> User | None:
    return (await db.execute(select(User).where(User.email == normalize_email(email)))).scalar_one_or_none()


async def get_user(db: AsyncSession, user_id: str) -> User | None:
    return await db.get(User, user_id)


async def active_admin_count(db: AsyncSession) -> int:
    stmt = select(func.count()).select_from(User).where(User.role == "admin", User.status == "active")
    return int((await db.execute(stmt)).scalar_one())


async def would_remove_last_admin(db: AsyncSession, user: User, *, new_role: str | None, new_status: str | None,
                                  deleting: bool = False) -> bool:
    """True if the change would leave the deployment without an active admin."""
    if user.role != "admin" or user.status != "active":
        return False
    still_admin = not deleting and (new_role or user.role) == "admin" and (new_status or user.status) == "active"
    return not still_admin and await active_admin_count(db) <= 1
