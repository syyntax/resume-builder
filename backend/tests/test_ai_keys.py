from __future__ import annotations

import io
import logging
import zipfile

import pytest
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy import select

from app.config import Settings
from app.db.models import UserApiKey
from app.main import create_app
from app.secrets import DecryptionError, Sealed, SecretBox
from tests.conftest import BASE, TEST_KEY, USER_PASSWORD, Api


def key_row(app: FastAPI, user_id: str) -> UserApiKey:
    async def load() -> UserApiKey:
        async with app.state.sessionmaker() as db:
            return (await db.execute(select(UserApiKey).where(UserApiKey.user_id == user_id))).scalar_one()

    return app.state.test_portal.call(load)


def test_add_test_and_remove_a_key(app: FastAPI, admin: Api, make_user) -> None:
    user = make_user("kai@example.com")
    assert user.get("/api/account/api-key").json() == {
        "hasKey": False, "hint": None, "status": None, "verifiedAt": None, "lastUsedAt": None,
        "sharedKeyAvailable": False, "using": None}

    def put(key: str, password: str = USER_PASSWORD):
        return user.put("/api/account/api-key", json={"apiKey": key, "password": password})

    assert put(TEST_KEY, password="wrong-password-xyz").status_code == 400
    assert put("not-a-key-at-all-1234").status_code == 422
    rejected = put("sk-ant-invalid-key-000000000000")
    assert rejected.status_code == 400 and rejected.json()["code"] == "key_rejected"

    saved = put(TEST_KEY).json()
    assert saved["hasKey"] and saved["hint"] == "WXYZ" and saved["status"] == "valid" and saved["using"] == "own"
    assert user.post("/api/account/api-key/test").json()["status"] == "valid"

    assert user.delete("/api/account/api-key", json={"password": "nope-nope-nope"}).status_code == 400
    assert user.delete("/api/account/api-key", json={"password": USER_PASSWORD}).status_code == 204
    assert user.get("/api/account/api-key").json()["hasKey"] is False

    events = [e["event"] for e in admin.get("/api/admin/audit-log", params={"event": "account.apikey"}).json()]
    assert events.count("account.apikey.add") == 1 and "account.apikey.remove" in events


def test_key_is_encrypted_and_never_disclosed(app: FastAPI, admin: Api, keyed_user: Api,
                                              caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    row = key_row(app, keyed_user.user["id"])
    assert TEST_KEY.encode() not in row.ciphertext and row.hint == "WXYZ"

    responses = [
        keyed_user.get("/api/account/api-key"), keyed_user.get("/api/auth/me"),
        keyed_user.get("/api/account/ai-settings"), keyed_user.get("/api/account/usage"),
        admin.get("/api/admin/users"), admin.get("/api/admin/usage"), admin.get("/api/admin/audit-log"),
    ]
    for response in responses:
        assert TEST_KEY not in response.text, response.url
    export = keyed_user.get("/api/account/export")
    for name in (archive := zipfile.ZipFile(io.BytesIO(export.content))).namelist():
        assert TEST_KEY.encode() not in archive.read(name)
    assert TEST_KEY not in caplog.text
    assert any(u["hasApiKey"] for u in admin.get("/api/admin/users").json())


def test_ciphertext_is_bound_to_its_owner() -> None:
    box = SecretBox(b"s" * 40, "user-api-key")
    sealed = box.seal(TEST_KEY, bound_to="usr_alice")
    assert box.open(sealed, bound_to="usr_alice") == TEST_KEY
    with pytest.raises(DecryptionError):
        box.open(sealed, bound_to="usr_bob")  # copied onto another user's row
    with pytest.raises(DecryptionError):
        SecretBox(b"t" * 40, "user-api-key").open(sealed, bound_to="usr_alice")  # wrong server secret


def test_previous_secret_still_decrypts_during_rotation() -> None:
    old = SecretBox(b"old-secret-" * 4, "user-api-key")
    sealed = old.seal(TEST_KEY, bound_to="usr_a")
    rotated = SecretBox(b"new-secret-" * 4, "user-api-key", previous=b"old-secret-" * 4)
    assert rotated.open(sealed, bound_to="usr_a") == TEST_KEY
    resealed = rotated.seal(TEST_KEY, bound_to="usr_a")
    assert resealed.key_fingerprint == rotated.current_fingerprint != sealed.key_fingerprint
    assert isinstance(resealed, Sealed)


def test_shared_key_fallback(tmp_path, settings: Settings) -> None:
    from fastapi.testclient import TestClient

    shared = settings.model_copy(update={"anthropic_api_key": SecretStr("sk-ant-shared-deployment-key-0000000000"),
                                         "data_dir": tmp_path / "shared"})
    application = create_app(shared)
    with TestClient(application, base_url=BASE) as main:
        application.state.test_portal = main.portal
        admin = Api(application)
        admin.post("/api/auth/setup", json={"token": application.state.setup_token, "email": "a@example.com",
                                            "password": "correct horse battery staple", "displayName": "Ad Min"})
        user = Api(application)
        user.post("/api/auth/register", json={"email": "u@example.com", "password": USER_PASSWORD,
                                              "displayName": "Una User"})
        status = user.get("/api/account/api-key").json()
        assert status["using"] is None and status["sharedKeyAvailable"] is False  # off by default

        ai = admin.get("/api/admin/ai-settings").json()
        assert ai["sharedKeyConfigured"] is True and ai["allowSharedKey"] is False
        assert admin.put("/api/admin/ai-settings", json={"allowSharedKey": True}).json()["allowSharedKey"] is True
        assert user.get("/api/account/api-key").json()["using"] == "shared"
        assert admin.post("/api/admin/ai-settings/test-connection").status_code == 204
        assert "sk-ant-shared" not in admin.get("/api/admin/ai-settings").text


def test_enabling_shared_key_requires_one(app: FastAPI, admin: Api) -> None:
    response = admin.put("/api/admin/ai-settings", json={"allowSharedKey": True})
    assert response.status_code == 409


def test_ai_settings_and_model_policy(app: FastAPI, admin: Api, keyed_user: Api) -> None:
    settings = keyed_user.get("/api/account/ai-settings").json()
    assert settings["model"] == "claude-opus-5-5" and settings["monthlyCapUsd"] is None
    assert settings["defaultCapUsd"] == 20.0
    assert keyed_user.put("/api/account/ai-settings", json={"model": "claude-haiku-4-5"}).status_code == 422

    admin.put("/api/admin/ai-settings", json={"allowedModels": ["claude-opus-5-5", "claude-sonnet-5-5"]})
    assert admin.put("/api/admin/ai-settings", json={"defaultModel": "claude-haiku-4-5"}).status_code == 422
    chosen = keyed_user.put("/api/account/ai-settings", json={"model": "claude-sonnet-5-5", "monthlyCapUsd": 5})
    assert chosen.json()["model"] == "claude-sonnet-5-5" and chosen.json()["monthlyCapUsd"] == 5
    reset = keyed_user.put("/api/account/ai-settings", json={"resetCap": True}).json()
    assert reset["monthlyCapUsd"] is None
