"""Application settings, read from environment variables (see .env.example)."""

from __future__ import annotations

from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
RegistrationMode = Literal["open", "invite", "closed"]


class ConfigError(RuntimeError):
    """Raised at startup when the configuration is unusable."""


def origin_of(url: str) -> str | None:
    parts = urlsplit(url)
    if not parts.scheme or not parts.netloc:
        return None
    return f"{parts.scheme}://{parts.netloc}".lower()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    app_base_url: str = "http://localhost:8080"
    app_secret_key: SecretStr | None = None
    app_secret_key_file: Path | None = None
    allow_insecure_http: bool = False
    # Extra origins allowed to make state-changing requests (development only, e.g. the Vite dev server).
    allowed_origins: str = ""

    data_dir: Path = Path("/data")
    database_url: str | None = None

    registration_mode: RegistrationMode = "open"
    registration_email_domains: str = ""

    session_idle_days: int = 7
    session_max_days: int = 30

    static_dir: Path | None = None
    enable_api_docs: bool = False
    argon2_profile: Literal["rfc9106_low_memory", "cheapest"] = "rfc9106_low_memory"
    log_level: str = "INFO"

    @field_validator("app_base_url")
    @classmethod
    def _strip_trailing_slash(cls, value: str) -> str:
        return value.rstrip("/")

    # ---- derived values -------------------------------------------------------------------------

    @property
    def base_origin(self) -> str:
        origin = origin_of(self.app_base_url)
        if origin is None:
            raise ConfigError(f"APP_BASE_URL is not a valid URL: {self.app_base_url!r}")
        return origin

    @property
    def base_host(self) -> str:
        return (urlsplit(self.app_base_url).hostname or "").lower()

    @property
    def is_https(self) -> bool:
        return urlsplit(self.app_base_url).scheme == "https"

    @property
    def base_is_local(self) -> bool:
        host = self.base_host
        return host in LOCAL_HOSTS or host.endswith(".localhost")

    @property
    def trusted_origins(self) -> frozenset[str]:
        origins = {self.base_origin}
        if self.base_is_local:
            # localhost, 127.0.0.1 and [::1] are the same machine; accept any of them on the same port.
            parts = urlsplit(self.app_base_url)
            port = f":{parts.port}" if parts.port else ""
            for host in ("localhost", "127.0.0.1", "[::1]"):
                origins.add(f"{parts.scheme}://{host}{port}")
        for extra in self.allowed_origins.split(","):
            if extra.strip():
                origin = origin_of(extra.strip())
                if origin:
                    origins.add(origin)
        return frozenset(origins)

    @property
    def email_domain_allowlist(self) -> list[str]:
        return [d.strip().lower().lstrip("@") for d in self.registration_email_domains.split(",") if d.strip()]

    @property
    def db_url_async(self) -> str:
        url = self.database_url or f"sqlite:///{self.data_dir / 'app.db'}"
        if url.startswith("sqlite:///"):
            return url.replace("sqlite:///", "sqlite+aiosqlite:///", 1)
        if url.startswith(("postgresql://", "postgres://")):
            return "postgresql+psycopg://" + url.split("://", 1)[1]
        return url

    @property
    def db_url_sync(self) -> str:
        url = self.db_url_async
        if url.startswith("sqlite+aiosqlite:///"):
            return url.replace("sqlite+aiosqlite:///", "sqlite:///", 1)
        return url  # psycopg 3 works for both sync and async under the same dialect name

    @property
    def is_sqlite(self) -> bool:
        return self.db_url_async.startswith("sqlite")

    def secret_key(self) -> bytes:
        if self.app_secret_key_file is not None:
            try:
                raw = self.app_secret_key_file.read_text(encoding="utf-8").strip()
            except OSError as exc:
                raise ConfigError(f"Cannot read APP_SECRET_KEY_FILE: {exc}") from exc
        elif self.app_secret_key is not None:
            raw = self.app_secret_key.get_secret_value().strip()
        else:
            raise ConfigError(
                "APP_SECRET_KEY (or APP_SECRET_KEY_FILE) is required. Generate one with: openssl rand -base64 32"
            )
        if len(raw) < 32:
            raise ConfigError("APP_SECRET_KEY must be at least 32 characters long.")
        return raw.encode("utf-8")

    def validate_for_startup(self) -> None:
        """Fail fast on configurations that would be unsafe or unusable."""
        self.secret_key()
        _ = self.base_origin
        if not self.base_is_local and not self.is_https and not self.allow_insecure_http:
            raise ConfigError(
                f"APP_BASE_URL ({self.app_base_url}) is not local, so it must use https://. "
                "Use the 'https' compose profile, or set ALLOW_INSECURE_HTTP=true for LAN testing only."
            )
        if self.session_idle_days < 1 or self.session_max_days < self.session_idle_days:
            raise ConfigError("SESSION_MAX_DAYS must be at least SESSION_IDLE_DAYS, and both must be >= 1.")
