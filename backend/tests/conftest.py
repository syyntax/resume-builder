from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import jsonschema
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx2 import Response

from app.ai.fake import FakeLLM
from app.ai.llm import LLMRequest, LLMResult
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
        # Share the lifespan's event loop so background jobs and loop-bound resources behave as in production.
        self.client.portal = getattr(app.state, "test_portal", None)
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


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests must not see the host's or container's configuration (an env file, Dockerfile ENV lines).

    Settings() reads environment variables, so without this a test like "a missing APP_SECRET_KEY is an
    error" fails wherever a real APP_SECRET_KEY is set. Tests that need a variable set it explicitly."""
    for name in Settings.model_fields:
        monkeypatch.delenv(name.upper(), raising=False)


@pytest.fixture(autouse=True)
def schema_checked_fake(monkeypatch: pytest.MonkeyPatch) -> None:
    """The fake model's answers must be ones the real model could give: valid against the exact schema sent.

    Structured outputs constrain the real model to `request.schema`, so a schema that disagrees with the
    Pydantic models fails every real run while the fake (which ignores the schema) passes."""
    complete = FakeLLM.complete

    async def checked(self: FakeLLM, request: LLMRequest) -> LLMResult:
        result = await complete(self, request)
        jsonschema.validate(result.data, request.schema)
        return result

    monkeypatch.setattr(FakeLLM, "complete", checked)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        app_base_url=BASE,
        app_secret_key="test-secret-key-that-is-long-enough-123",  # type: ignore[arg-type]
        allow_insecure_http=True,
        data_dir=tmp_path,
        argon2_profile="cheapest",
        log_level="WARNING",
        ai_provider="fake",
    )


@pytest.fixture
def app(settings: Settings) -> Iterator[FastAPI]:
    application = create_app(settings)
    with TestClient(application, base_url=BASE) as main:  # runs the lifespan (migrations, setup token)
        application.state.test_portal = main.portal
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


TEST_KEY = "sk-ant-api03-test-key-0123456789abcdefWXYZ"


def drain(app: FastAPI) -> None:
    """Wait until every background generation job has finished."""
    app.state.test_portal.call(app.state.jobs.drain)


@pytest.fixture
def keyed_user(app: FastAPI, make_user: Callable[..., Api]) -> Api:
    user = make_user("keyed@example.com", name="Kim Keyed")
    response = user.put("/api/account/api-key", json={"apiKey": TEST_KEY, "password": USER_PASSWORD})
    assert response.status_code == 200, response.text
    return user


POSTING = """Staff Platform Engineer at Globex
Globex is building an internal developer platform used by 400 engineers.
- 7+ years building distributed systems with Go or Python
- Deep experience running Kubernetes in production on AWS
- Infrastructure as code with Terraform
- Nice to have: experience with GCP
- Strong mentoring and written communication
"""
