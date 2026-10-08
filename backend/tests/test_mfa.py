"""Two-step verification (DESIGN.md §8.2, AUTH-9): TOTP, recovery codes, the two-step sign-in, and policy."""

from __future__ import annotations

from fastapi import FastAPI
from sqlalchemy import select

from app.auth import totp
from app.db.models import AuditLog, UserSession
from tests.conftest import ADMIN_PASSWORD, USER_PASSWORD, Api

# RFC 6238 test vector: SHA-1, secret "12345678901234567890"
RFC_SECRET = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"


def test_totp_matches_the_rfc_and_refuses_replays() -> None:
    assert totp.code_at(RFC_SECRET, 59 // 30) == "287082"
    assert totp.code_at(RFC_SECRET, 1111111109 // 30) == "081804"
    now = 1111111109
    step = totp.verify(RFC_SECRET, "081 804", last_step=None, now=now)
    assert step == now // 30
    assert totp.verify(RFC_SECRET, "081804", last_step=step, now=now) is None  # used: no replay
    assert totp.verify(RFC_SECRET, totp.code_at(RFC_SECRET, step + 1), last_step=step, now=now) == step + 1  # drift
    assert totp.verify(RFC_SECRET, totp.code_at(RFC_SECRET, step + 2), last_step=None, now=now) is None
    assert totp.verify(RFC_SECRET, "12345", last_step=None, now=now) is None
    uri = totp.otpauth_uri("ABC", "jo@example.com")
    assert uri.startswith("otpauth://totp/Resume%20Tailor%3Ajo%40example.com?secret=ABC&issuer=Resume+Tailor")


def test_recovery_codes_are_random_and_forgiving_to_type() -> None:
    codes = totp.new_recovery_codes()
    assert len(codes) == len(set(codes)) == 10 and all(len(c) == 12 and c.count("-") == 2 for c in codes)
    assert totp.hash_recovery_code(codes[0]) == totp.hash_recovery_code(f" {codes[0].upper().replace('-', '')} ")


def turn_on(api: Api, password: str) -> tuple[str, list[str]]:
    """Set it up and confirm it; returns the secret and the recovery codes."""
    setup = api.post("/api/auth/mfa/setup", json={"password": password})
    assert setup.status_code == 200, setup.text
    secret = setup.json()["secret"]
    assert setup.json()["qrSvg"].startswith("<svg") and setup.json()["otpauthUri"].startswith("otpauth://totp/")
    wrong = api.post("/api/auth/mfa/enable", json={"code": "000000"})
    assert wrong.status_code == 422
    enabled = api.post("/api/auth/mfa/enable", json={"code": totp.code_at(secret, totp.current_step())})
    assert enabled.status_code == 200, enabled.text
    return secret, enabled.json()["recoveryCodes"]


def next_code(secret: str) -> str:
    """A code for the next time step: inside the drift window, and never the one just used."""
    return totp.code_at(secret, totp.current_step() + 1)


def test_signing_in_with_two_step_verification(app: FastAPI, admin: Api, make_user) -> None:
    user = make_user("mfa@example.com")
    other = Api(app)
    assert other.login("mfa@example.com", USER_PASSWORD).status_code == 200
    assert user.post("/api/auth/mfa/setup", json={"password": "wrong password!"}).status_code == 400
    secret, codes = turn_on(user, USER_PASSWORD)
    assert len(codes) == 10 and user.get("/api/auth/me").json()["user"]["mfaEnabled"]
    assert other.get("/api/auth/me").status_code == 401  # other sessions were signed in without it: signed out
    assert user.get("/api/auth/mfa").json() == {"enabled": True, "required": False, "recoveryCodesLeft": 10}

    # the password alone opens a pending session that's only good for the code
    browser = Api(app)
    pending = browser.login("mfa@example.com", USER_PASSWORD)
    assert pending.status_code == 200 and pending.json()["stage"] == "mfa"
    blocked = browser.get("/api/master-resumes")
    assert blocked.status_code == 401 and blocked.json()["code"] == "mfa_required"
    assert browser.get("/api/auth/me").json()["stage"] == "mfa"
    assert browser.post("/api/auth/mfa/verify", json={"code": "123456"}).status_code == 401
    code = next_code(secret)
    done = browser.post("/api/auth/mfa/verify", json={"code": code})
    assert done.status_code == 200 and done.json()["stage"] == "active"
    assert browser.get("/api/master-resumes").status_code == 200

    # the same code can't be used again
    again = Api(app)
    again.login("mfa@example.com", USER_PASSWORD)
    assert again.post("/api/auth/mfa/verify", json={"code": code}).status_code == 401

    # a recovery code works once
    rescued = again.post("/api/auth/mfa/verify", json={"code": codes[0]})
    assert rescued.status_code == 200 and "recovery-code-used" in rescued.json()["notices"]
    third = Api(app)
    third.login("mfa@example.com", USER_PASSWORD)
    assert third.post("/api/auth/mfa/verify", json={"code": codes[0]}).status_code == 401
    assert rescued.json()["stage"] == "active"
    assert user.get("/api/auth/mfa").json()["recoveryCodesLeft"] == 9

    # new recovery codes replace the old ones, with the password
    assert user.post("/api/auth/mfa/recovery-codes", json={"password": "nope nope nope"}).status_code == 400
    fresh = user.post("/api/auth/mfa/recovery-codes", json={"password": USER_PASSWORD}).json()["recoveryCodes"]
    assert len(fresh) == 10 and not set(fresh) & set(codes)

    # turning it off takes the password and a code
    assert user.post("/api/auth/mfa/disable", json={"password": USER_PASSWORD, "code": "000000"}).status_code == 422
    off = user.post("/api/auth/mfa/disable", json={"password": USER_PASSWORD, "code": fresh[0]})
    assert off.status_code == 200 and off.json()["enabled"] is False
    plain = Api(app)
    assert plain.login("mfa@example.com", USER_PASSWORD).json()["stage"] == "active"


def test_pending_sessions_are_short_and_hold_no_rights(app: FastAPI, admin: Api, make_user) -> None:
    user = make_user("short@example.com")
    turn_on(user, USER_PASSWORD)
    browser = Api(app)
    pending_login = browser.login("short@example.com", USER_PASSWORD, remember=True)
    assert "max-age" not in pending_login.headers["set-cookie"].lower()  # "remember me" waits for the code
    assert browser.post("/api/auth/mfa/setup", json={"password": USER_PASSWORD}).status_code == 401
    assert browser.put("/api/account/preferences", json={}).status_code == 401

    async def pending() -> UserSession:
        async with app.state.sessionmaker() as db:
            return (await db.execute(select(UserSession).where(UserSession.stage == "mfa"))).scalar_one()

    session = app.state.test_portal.call(pending)
    assert (session.absolute_expires_at - session.created_at).total_seconds() <= 300


def test_admins_can_require_it_and_reset_it(app: FastAPI, admin: Api, make_user) -> None:
    user = make_user("staff@example.com")
    assert admin.put("/api/admin/settings", json={"requireMfa": "admins"}).json()["requireMfa"] == "admins"
    # the admin's own session now has to set it up before anything else
    blocked = admin.get("/api/admin/users")
    assert blocked.status_code == 403 and blocked.json()["code"] == "mfa_enrollment_required"
    assert admin.get("/api/auth/me").json()["stage"] == "enroll"
    assert user.get("/api/master-resumes").status_code == 200  # not required for users
    turn_on(admin, ADMIN_PASSWORD)
    assert admin.get("/api/admin/users").status_code == 200

    # with "all", signing in without it set up opens a session good only for setting it up
    admin.put("/api/admin/settings", json={"requireMfa": "all"})
    browser = Api(app)
    assert browser.login("staff@example.com", USER_PASSWORD).json()["stage"] == "enroll"
    assert browser.get("/api/master-resumes").status_code == 403
    setup = browser.post("/api/auth/mfa/setup", json={})  # the password was just entered
    assert setup.status_code == 200
    secret = setup.json()["secret"]
    enabled = browser.post("/api/auth/mfa/enable", json={"code": totp.code_at(secret, totp.current_step())})
    assert enabled.status_code == 200 and enabled.json()["me"]["stage"] == "active"
    assert browser.get("/api/master-resumes").status_code == 200
    # required: it can't be turned off
    code = next_code(secret)
    refused = browser.post("/api/auth/mfa/disable", json={"password": USER_PASSWORD, "code": code})
    assert refused.status_code == 409

    # an admin resets it for someone who lost their phone: off, and signed out everywhere
    user_id = browser.get("/api/auth/me").json()["user"]["id"]
    reset = admin.post(f"/api/admin/users/{user_id}/mfa-reset")
    assert reset.status_code == 200 and reset.json()["mfaEnabled"] is False
    assert browser.get("/api/auth/me").status_code == 401
    assert Api(app).login("staff@example.com", USER_PASSWORD).json()["stage"] == "enroll"

    async def events() -> list[str]:
        async with app.state.sessionmaker() as db:
            return list((await db.execute(select(AuditLog.event))).scalars())

    logged = app.state.test_portal.call(events)
    assert {"auth.mfa.enabled", "auth.mfa.reset", "auth.login.password_ok"} <= set(logged)
