from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import cli
from app.api.meta import example_master
from app.config import Settings
from app.main import create_app
from app.models.master import json_schema
from tests.conftest import BASE, Api

REPO_SCHEMA = Path(__file__).resolve().parents[2] / "schema"


@pytest.fixture
def cli_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ARGON2_PROFILE", "cheapest")
    return tmp_path


def run_cli(monkeypatch: pytest.MonkeyPatch, args: list[str], stdin: str = "") -> int:
    monkeypatch.setattr("sys.stdin", io.StringIO(stdin))
    return cli.main(args)


def test_cli_admin_lifecycle(cli_env: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    assert run_cli(monkeypatch, ["setup-token"]) == 0
    assert "Setup token:" in capsys.readouterr().out

    pw = "a sturdy admin passphrase\n"
    assert run_cli(monkeypatch, ["admin", "create", "--email", "Root@Example.com", "--name", "Root",
                                 "--password-stdin"], pw) == 0
    assert run_cli(monkeypatch, ["admin", "create", "--email", "root@example.com", "--name", "Root",
                                 "--password-stdin"], pw) == 1
    assert run_cli(monkeypatch, ["setup-token"]) == 1  # setup is complete once a user exists
    assert run_cli(monkeypatch, ["admin", "disable", "--email", "root@example.com"]) == 1  # last admin
    with pytest.raises(SystemExit, match="Password rejected"):
        run_cli(monkeypatch, ["admin", "reset-password", "--email", "root@example.com", "--password-stdin"],
                "short\n")
    assert run_cli(monkeypatch, ["admin", "reset-password", "--email", "root@example.com", "--password-stdin"],
                   "another sturdy passphrase\n") == 0
    capsys.readouterr()
    assert run_cli(monkeypatch, ["admin", "list"]) == 0
    assert "root@example.com" in capsys.readouterr().out

    settings = Settings(app_base_url=BASE, app_secret_key="k" * 40, data_dir=cli_env,  # type: ignore[arg-type]
                        allow_insecure_http=True, argon2_profile="cheapest")
    application = create_app(settings)
    with TestClient(application, base_url=BASE):
        assert application.state.setup_token is None
        assert Api(application).login("root@example.com", "another sturdy passphrase").status_code == 200


def test_committed_schema_files_are_current() -> None:
    """Regenerate with: resume-tailor schema"""
    schema = json.loads((REPO_SCHEMA / "master-resume.schema.json").read_text(encoding="utf-8"))
    example = json.loads((REPO_SCHEMA / "examples" / "master-resume.example.json").read_text(encoding="utf-8"))
    assert schema == json_schema()
    assert example == example_master()


def test_committed_openapi_is_current() -> None:
    """The frontend's TypeScript types are generated from this file. Regenerate with: make api-types"""
    committed = json.loads((REPO_SCHEMA / "openapi.json").read_text(encoding="utf-8"))
    settings = Settings(enable_api_docs=True, app_secret_key="x" * 32)  # type: ignore[arg-type]
    assert committed == create_app(settings).openapi()


def test_security_headers(app, admin: Api) -> None:
    response = admin.get("/api/auth/me")
    assert "default-src 'self'" in response.headers["content-security-policy"]
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "no-store"
    assert "strict-transport-security" not in response.headers  # plain-HTTP test server


def test_spa_fallback_and_api_404(tmp_path: Path, settings: Settings) -> None:
    static = tmp_path / "static"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text("<!doctype html><title>Resume Tailor</title>")
    (static / "assets" / "app.js").write_text("console.log('hi')")
    application = create_app(settings.model_copy(update={"static_dir": static}))
    with TestClient(application, base_url=BASE) as client:
        assert client.get("/").text.startswith("<!doctype html>")
        assert client.get("/masters/abc").text.startswith("<!doctype html>")  # client-side route
        assert client.get("/assets/app.js").text == "console.log('hi')"
        assert client.get("/assets/missing.js").status_code == 404
        missing_api = client.get("/api/does-not-exist")
        assert missing_api.status_code == 404 and missing_api.headers["content-type"] == "application/json"


def test_cli_keys_rotate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    from sqlalchemy import select

    from app.db.models import UserApiKey
    from app.keys.service import decrypt
    from tests.conftest import TEST_KEY, USER_PASSWORD

    old_secret, new_secret = "old-secret-value-" * 3, "new-secret-value-" * 3
    settings = Settings(app_base_url=BASE, app_secret_key=old_secret, data_dir=tmp_path,  # type: ignore[arg-type]
                        allow_insecure_http=True, argon2_profile="cheapest", ai_provider="fake")
    application = create_app(settings)
    with TestClient(application, base_url=BASE) as main:
        application.state.test_portal = main.portal
        admin = Api(application)
        admin.post("/api/auth/setup", json={"token": application.state.setup_token, "email": "a@example.com",
                                            "password": USER_PASSWORD, "displayName": "Ad Min"})
        saved = admin.put("/api/account/api-key", json={"apiKey": TEST_KEY, "password": USER_PASSWORD})
        assert saved.status_code == 200

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("APP_SECRET_KEY", new_secret)
    assert run_cli(monkeypatch, ["keys", "rotate"]) == 2  # needs the previous secret
    monkeypatch.setenv("APP_SECRET_KEY_PREVIOUS", old_secret)
    assert run_cli(monkeypatch, ["keys", "rotate"]) == 0
    assert "Re-encrypted 1 API key(s)" in capsys.readouterr().out

    rotated = Settings(app_secret_key=new_secret, data_dir=tmp_path)  # type: ignore[arg-type]
    application = create_app(rotated.model_copy(update={"allow_insecure_http": True, "app_base_url": BASE}))
    with TestClient(application, base_url=BASE) as main:
        async def load() -> str:
            async with application.state.sessionmaker() as db:
                row = (await db.execute(select(UserApiKey))).scalar_one()
                return decrypt(row, rotated)

        assert main.portal.call(load) == TEST_KEY
