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
    assert response.headers["cross-origin-resource-policy"] == "same-origin"  # ZAP baseline 90004
    assert response.headers["cross-origin-opener-policy"] == "same-origin"
    assert response.headers["referrer-policy"] == "same-origin" and response.headers["x-frame-options"] == "DENY"
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
        asset = client.get("/assets/app.js")
        assert asset.text == "console.log('hi')"
        assert asset.headers["cache-control"] == "public, max-age=31536000, immutable"  # content-hashed names
        assert client.get("/masters/abc").headers["cache-control"] == "no-cache"  # the page: new releases at once
        assert client.get("/assets/missing.js").status_code == 404
        missing_api = client.get("/api/does-not-exist")
        assert missing_api.status_code == 404 and missing_api.headers["content-type"] == "application/json"


def test_cli_keys_rotate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    from sqlalchemy import select

    from app.auth import mfa, totp
    from app.db.models import User, UserApiKey
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
        secret = admin.post("/api/auth/mfa/setup", json={"password": USER_PASSWORD}).json()["secret"]
        code = totp.code_at(secret, totp.current_step())
        assert admin.post("/api/auth/mfa/enable", json={"code": code}).status_code == 200

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("APP_SECRET_KEY", new_secret)
    assert run_cli(monkeypatch, ["keys", "rotate"]) == 2  # needs the previous secret
    monkeypatch.setenv("APP_SECRET_KEY_PREVIOUS", old_secret)
    assert run_cli(monkeypatch, ["keys", "rotate"]) == 0
    assert "Re-encrypted 1 API key(s) and 1 two-step verification secret(s)" in capsys.readouterr().out

    rotated = Settings(app_secret_key=new_secret, data_dir=tmp_path)  # type: ignore[arg-type]
    application = create_app(rotated.model_copy(update={"allow_insecure_http": True, "app_base_url": BASE}))
    with TestClient(application, base_url=BASE) as main:
        async def load() -> tuple[str, str | None]:
            async with application.state.sessionmaker() as db:
                row = (await db.execute(select(UserApiKey))).scalar_one()
                user = (await db.execute(select(User))).scalar_one()
                return decrypt(row, rotated), mfa.read_secret(user, rotated)

        assert main.portal.call(load) == (TEST_KEY, secret)


def test_cli_backup_and_restore(cli_env: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    import stat
    import tarfile

    pw = "a sturdy admin passphrase\n"
    assert run_cli(monkeypatch, ["admin", "create", "--email", "root@example.com", "--name", "Root",
                                 "--password-stdin"], pw) == 0
    upload = cli_env / "uploads" / "usr_1" / "cv.pdf"
    upload.parent.mkdir(parents=True)
    upload.write_bytes(b"%PDF-original")
    capsys.readouterr()
    assert run_cli(monkeypatch, ["backup"]) == 0
    archive = Path(capsys.readouterr().out.splitlines()[0].removeprefix("wrote "))
    assert archive.parent == cli_env / "backups" and stat.S_IMODE(archive.stat().st_mode) == 0o600
    with tarfile.open(archive) as tar:
        assert {"manifest.json", "app.db", "uploads/usr_1/cv.pdf"} <= set(tar.getnames())

    # after the backup: another account, and a changed file
    assert run_cli(monkeypatch, ["admin", "create", "--email", "second@example.com", "--name", "Second",
                                 "--password-stdin"], pw) == 0
    upload.write_bytes(b"%PDF-changed")
    assert run_cli(monkeypatch, ["restore", str(archive)]) == 2  # needs --yes
    assert run_cli(monkeypatch, ["restore", str(archive), "--yes"]) == 0
    assert "restored the database" in capsys.readouterr().out
    assert upload.read_bytes() == b"%PDF-original"
    assert any(p.name.startswith("app.db.before-restore-") for p in cli_env.iterdir())
    assert any(p.name.startswith("uploads.before-restore-") for p in cli_env.iterdir())
    assert run_cli(monkeypatch, ["admin", "list"]) == 0
    listed = capsys.readouterr().out
    assert "root@example.com" in listed and "second@example.com" not in listed

    # an archive that tries to write outside the data directory is refused
    evil = cli_env / "evil.tar.gz"
    with tarfile.open(evil, "w:gz") as tar:
        info = tarfile.TarInfo("../escape.txt")
        info.size = 2
        tar.addfile(info, io.BytesIO(b"hi"))
    assert run_cli(monkeypatch, ["restore", str(evil), "--yes"]) == 1
    assert "unexpected entry" in capsys.readouterr().err and not (cli_env.parent / "escape.txt").exists()
