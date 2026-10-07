"""Engine/session factories and programmatic Alembic migrations."""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from fastapi import Request
from sqlalchemy import event
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.config import Settings

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
log = logging.getLogger("resume_tailor.db")


def _sqlite_pragmas(dbapi_conn: Any, _record: Any) -> None:
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


def build_engine(settings: Settings) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(settings.db_url_async, pool_pre_ping=not settings.is_sqlite)
    if settings.is_sqlite:
        event.listen(engine.sync_engine, "connect", _sqlite_pragmas)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def alembic_config(sync_url: str) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    cfg.set_main_option("sqlalchemy.url", sync_url.replace("%", "%%"))
    return cfg


def run_migrations(sync_url: str, *, wait_seconds: float = 0, retry_every: float = 2.0) -> None:
    """Upgrade the database to the latest schema. Blocking; call from a thread inside async code.

    ``wait_seconds`` keeps retrying while the database is unreachable (e.g. PostgreSQL still starting)."""
    deadline = time.monotonic() + wait_seconds
    while True:
        try:
            command.upgrade(alembic_config(sync_url), "head")
            return
        except OperationalError as exc:
            if time.monotonic() + retry_every > deadline:
                raise
            log.warning("Database not reachable yet (%s); retrying in %.0fs", exc.orig or exc, retry_every)
            time.sleep(retry_every)


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.sessionmaker() as session:
        yield session
