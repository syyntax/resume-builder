"""Unit tests for password policy/hashing, rate limiting, settings and migrations."""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine

from app.auth import passwords
from app.auth.ratelimit import FailureBackoff, SlidingWindow
from app.config import ConfigError, Settings
from app.db import models  # noqa: F401
from app.db.base import Base
from app.db.engine import run_migrations

# ---- passwords -------------------------------------------------------------------------------------


@pytest.mark.parametrize(("password", "fragment"), [
    ("short", "at least 12"),
    ("qwertyuiop123", "too common"),
    ("qpqpqpqpqpqpqpqp", "repetitive"),
    ("jordan-loves-skiing", "name or email"),
    ("x" * 129, "at most 128"),
])
def test_password_policy_rejections(password: str, fragment: str) -> None:
    errors = passwords.policy_errors(password, email="jordan@example.com", display_name="Jordan Rivera")
    assert any(fragment in e for e in errors), errors


def test_password_policy_accepts_passphrases() -> None:
    assert passwords.policy_errors("correct horse battery staple", email="a@b.c", display_name="Ann") == []


def test_hashes_are_upgraded_when_parameters_change() -> None:
    try:
        passwords.configure("cheapest")
        weak_hash = passwords.hash_password("a perfectly fine passphrase")
        passwords.configure("rfc9106_low_memory")
        ok, upgraded = passwords.verify_password(weak_hash, "a perfectly fine passphrase")
        assert ok and upgraded and upgraded.startswith("$argon2id$")
        assert passwords.verify_password(upgraded, "a perfectly fine passphrase") == (True, None)
        assert passwords.verify_password(upgraded, "wrong") == (False, None)
        assert passwords.verify_password("not-a-hash", "anything") == (False, None)
    finally:
        passwords.configure("cheapest")


# ---- rate limiting ---------------------------------------------------------------------------------


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_sliding_window() -> None:
    clock = Clock()
    window = SlidingWindow(3, 60, clock=clock)
    assert [window.allow("ip") for _ in range(4)] == [True, True, True, False]
    assert window.retry_after("ip") == 60
    clock.now += 61
    assert window.allow("ip") and window.count("ip") == 1


def test_failure_backoff_grows_and_resets() -> None:
    clock = Clock()
    backoff = FailureBackoff(free=5, max_delay=900, clock=clock)
    for _ in range(4):
        backoff.failure("a@x")
    assert backoff.retry_after("a@x") == 0
    backoff.failure("a@x")
    assert backoff.retry_after("a@x") == 1
    backoff.failure("a@x")
    assert backoff.retry_after("a@x") == 2
    for _ in range(20):
        backoff.failure("a@x")
    assert backoff.retry_after("a@x") == 900  # capped; no permanent lockout
    clock.now += 901
    assert backoff.retry_after("a@x") == 0
    backoff.reset("a@x")
    backoff.failure("a@x")
    assert backoff.retry_after("a@x") == 0


# ---- settings --------------------------------------------------------------------------------------


def _settings(**kw) -> Settings:
    return Settings(app_secret_key="k" * 40, **kw)  # type: ignore[arg-type]


def test_startup_validation() -> None:
    _settings().validate_for_startup()
    with pytest.raises(ConfigError, match="APP_SECRET_KEY"):
        Settings().validate_for_startup()
    with pytest.raises(ConfigError, match="at least 32"):
        Settings(app_secret_key="short").validate_for_startup()  # type: ignore[arg-type]
    with pytest.raises(ConfigError, match="https"):
        _settings(app_base_url="http://resumes.example.com").validate_for_startup()
    _settings(app_base_url="http://resumes.example.com", allow_insecure_http=True).validate_for_startup()
    _settings(app_base_url="https://resumes.example.com").validate_for_startup()


def test_secret_key_file(tmp_path: Path) -> None:
    key_file = tmp_path / "secret"
    key_file.write_text("f" * 44 + "\n")
    assert Settings(app_secret_key_file=key_file).secret_key() == b"f" * 44


def test_trusted_origins_for_local_and_public_urls() -> None:
    local = _settings(app_base_url="http://localhost:8080/")
    assert local.app_base_url == "http://localhost:8080"
    assert {"http://localhost:8080", "http://127.0.0.1:8080", "http://[::1]:8080"} <= local.trusted_origins
    public = _settings(app_base_url="https://cv.example.com", allowed_origins="http://localhost:5173")
    assert public.trusted_origins == {"https://cv.example.com", "http://localhost:5173"}
    assert public.is_https and not public.base_is_local


def test_database_urls(tmp_path: Path) -> None:
    sqlite = _settings(data_dir=tmp_path)
    assert sqlite.db_url_async == f"sqlite+aiosqlite:///{tmp_path}/app.db"
    assert sqlite.db_url_sync == f"sqlite:///{tmp_path}/app.db"
    pg = _settings(database_url="postgres://u:p@db/rt")
    assert pg.db_url_async == pg.db_url_sync == "postgresql+psycopg://u:p@db/rt"


# ---- migrations ------------------------------------------------------------------------------------


def test_migrations_match_models(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'm.db'}"
    run_migrations(url)
    engine = create_engine(url)
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn, opts={"compare_type": True}), Base.metadata)
    engine.dispose()
    assert diff == []


def test_migrations_wait_for_an_unreachable_database(monkeypatch: pytest.MonkeyPatch) -> None:
    from sqlalchemy.exc import OperationalError

    from app.db import engine

    calls = []

    def flaky_upgrade(*_args: object) -> None:
        calls.append(1)
        if len(calls) < 3:
            raise OperationalError("connect", {}, Exception("connection refused"))

    monkeypatch.setattr(engine.command, "upgrade", flaky_upgrade)
    engine.run_migrations("postgresql+psycopg://x@db/x", wait_seconds=5, retry_every=0.01)
    assert len(calls) == 3

    calls.clear()
    with pytest.raises(OperationalError):
        engine.run_migrations("postgresql+psycopg://x@db/x", wait_seconds=0, retry_every=0.01)
    assert len(calls) == 1
