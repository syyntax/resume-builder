from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx2 import Response

from app.config import Settings
from app.main import create_app

BASE = "http://testserver"
ADMIN_EMAIL = "admin@example.com"
ADMIN_PASSWORD = "correct horse battery staple"
USER_PASSWORD = "violet-lantern-orbit-42"
EXAMPLE = Path(__file__).resolve().parents[1] / "app" / "masters" / "example_master.json"


class Api:
    """A browser-like client: its own cookie jar, plus Origin and CSRF headers like the SPA sends."""

    def __init__(self, app: FastAPI) -> None:
        self.client = TestClient(app, base_url=BASE)
        self.csrf: str | None = None
        self.user: dict[str, Any] | None = None

    def request(self, method: str, url: str, *, csrf: bool = True, origin: str | None = BASE,
                **kwargs: Any) -> Response:
        headers = dict(kwargs.pop("headers", None) or {})
        if origin is not None:
            headers.setdefault("Origin", origin)
        if csrf and self.csrf:
            headers.setdefault("X-CSRF-Token", self.csrf)
        response = self.client.request(method, url, headers=headers, **kwargs)
        if response.headers.get("content-type", "").startswith("application/json"):
            body = response.json()
            if isinstance(body, dict) and "csrfToken" in body:
                self.csrf, self.user = body["csrfToken"], body["user"]
        return response

    def get(self, url: str, **kw: Any) -> Response:
        return self.request("GET", url, **kw)

    def post(self, url: str, **kw: Any) -> Response:
        return self.request("POST", url, **kw)

    def put(self, url: str, **kw: Any) -> Response:
        return self.request("PUT", url, **kw)

    def patch(self, url: str, **kw: Any) -> Response:
        return self.request("PATCH", url, **kw)

    def delete(self, url: str, **kw: Any) -> Response:
        return self.request("DELETE", url, **kw)

    def login(self, email: str, password: str, remember: bool = False) -> Response:
        return self.post("/api/auth/login", json={"email": email, "password": password, "remember": remember})


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        app_base_url=BASE,
        app_secret_key="test-secret-key-that-is-long-enough-123",  # type: ignore[arg-type]
        allow_insecure_http=True,
        data_dir=tmp_path,
        argon2_profile="cheapest",
        log_level="WARNING",
    )


@pytest.fixture
def app(settings: Settings) -> Iterator[FastAPI]:
    application = create_app(settings)
    with TestClient(application, base_url=BASE):  # runs the lifespan (migrations, setup token)
        yield application


@pytest.fixture
def admin(app: FastAPI) -> Api:
    api = Api(app)
    response = api.post("/api/auth/setup", json={
        "token": app.state.setup_token, "email": ADMIN_EMAIL, "password": ADMIN_PASSWORD,
        "displayName": "Ada Admin",
    })
    assert response.status_code == 201, response.text
    return api


@pytest.fixture
def make_user(app: FastAPI, admin: Api) -> Callable[..., Api]:
    def _make(email: str, name: str = "Test User", password: str = USER_PASSWORD) -> Api:
        api = Api(app)
        response = api.post("/api/auth/register", json={"email": email, "password": password, "displayName": name})
        assert response.status_code == 201, response.text
        return api

    return _make


@pytest.fixture
def example() -> dict[str, Any]:
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))
