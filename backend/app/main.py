"""Application factory. Run with: uvicorn --factory app.main:create_app"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import __version__
from app.api import account, admin, auth, masters, meta
from app.auth import passwords
from app.auth.bootstrap import announce_setup_token, ensure_setup_token
from app.auth.ratelimit import Limits
from app.auth.sessions import purge_expired
from app.config import Settings
from app.db.engine import build_engine, run_migrations
from app.errors import install_error_handlers
from app.services import settings_store
from app.web import SecurityHeaders, SinglePageApp

log = logging.getLogger("resume_tailor")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    settings.validate_for_startup()
    passwords.configure(settings.argon2_profile)
    if settings.is_sqlite:
        settings.data_dir.mkdir(parents=True, exist_ok=True)
    await asyncio.to_thread(run_migrations, settings.db_url_sync, wait_seconds=0 if settings.is_sqlite else 60)

    engine, sessionmaker = build_engine(settings)
    app.state.engine, app.state.sessionmaker = engine, sessionmaker
    async with sessionmaker() as db:
        await settings_store.init_defaults(db, settings)
        await purge_expired(db)
        await db.commit()
        token = await ensure_setup_token(db)
        policy = await settings_store.registration_policy(db)
    app.state.setup_token = token  # in memory only, so tests and the CLI banner can read it
    if token:
        announce_setup_token(token, settings)
    if policy.mode == "open" and not policy.domains and not settings.base_is_local:
        log.warning("Registration is OPEN and %s is not a local address. Anyone who can reach the app can "
                    "create an account. Consider invite-only mode or an email-domain allowlist.",
                    settings.app_base_url)
    log.info("Resume Tailor %s ready at %s", __version__, settings.app_base_url)
    try:
        yield
    finally:
        await engine.dispose()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    logging.basicConfig(level=settings.log_level.upper(), format="%(levelname)s [%(name)s] %(message)s")
    docs = settings.enable_api_docs
    app = FastAPI(
        title="Resume Tailor",
        version=__version__,
        lifespan=lifespan,
        docs_url="/api/docs" if docs else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if docs else None,
    )
    app.state.settings = settings
    app.state.limits = Limits()
    app.state.setup_token = None
    install_error_handlers(app)
    app.add_middleware(SecurityHeaders, settings=settings)
    for module in (meta, auth, account, admin, masters):
        app.include_router(module.router)
    if settings.static_dir and settings.static_dir.is_dir():
        app.mount("/", SinglePageApp(settings.static_dir), name="spa")
    return app

