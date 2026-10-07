from __future__ import annotations

from fastapi import FastAPI

from tests.conftest import ADMIN_EMAIL, ADMIN_PASSWORD, USER_PASSWORD, Api


def test_first_run_setup_flow(app: FastAPI) -> None:
    api = Api(app)
    assert api.get("/api/auth/setup-status").json() == {"needsSetup": True}
    token = app.state.setup_token
    assert token

    body = {"token": "wrong-token-value", "email": ADMIN_EMAIL, "password": ADMIN_PASSWORD, "displayName": "Ada"}
    assert api.post("/api/auth/setup", json=body).status_code == 400

    weak = {**body, "token": token, "password": "password1234"}
    response = api.post("/api/auth/setup", json=weak)
    assert response.status_code == 422
    assert response.json()["errors"][0]["field"] == "password"

    # The token wasn't consumed by the failed attempt.
    response = api.post("/api/auth/setup", json={**body, "token": token})
    assert response.status_code == 201, response.text
    assert response.json()["user"]["role"] == "admin"
    assert api.get("/api/auth/me").status_code == 200

    assert Api(app).post("/api/auth/setup", json={**body, "token": token}).status_code == 409
    assert api.get("/api/auth/setup-status").json() == {"needsSetup": False}


def test_register_blocked_before_setup(app: FastAPI) -> None:
    response = Api(app).post("/api/auth/register", json={
        "email": "early@example.com", "password": USER_PASSWORD, "displayName": "Early"})
    assert response.status_code == 409


def test_setup_requires_same_origin(app: FastAPI) -> None:
    body = {"token": app.state.setup_token, "email": ADMIN_EMAIL, "password": ADMIN_PASSWORD, "displayName": "A"}
    assert Api(app).post("/api/auth/setup", json=body, origin=None).status_code == 403
    assert Api(app).post("/api/auth/setup", json=body, origin="https://evil.example").status_code == 403


def test_login_logout_and_cookie_flags(app: FastAPI, admin: Api) -> None:
    api = Api(app)
    response = api.login(ADMIN_EMAIL, ADMIN_PASSWORD)
    assert response.status_code == 200
    cookie = response.headers["set-cookie"]
    assert cookie.startswith("rt_session=")
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie and "Max-Age" not in cookie
    assert api.get("/api/auth/me").json()["user"]["email"] == ADMIN_EMAIL

    assert api.post("/api/auth/logout").status_code == 204
    assert api.get("/api/auth/me").status_code == 401

    remembered = Api(app).login(ADMIN_EMAIL, ADMIN_PASSWORD, remember=True)
    assert "Max-Age" in remembered.headers["set-cookie"]


def test_login_errors_are_generic(app: FastAPI, admin: Api, make_user) -> None:
    make_user("someone@example.com")
    wrong_password = Api(app).login("someone@example.com", "not-the-password-at-all")
    unknown_email = Api(app).login("nobody@example.com", "not-the-password-at-all")
    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json() == unknown_email.json() == {"detail": "Invalid email or password."}


def test_disabled_user_cannot_sign_in(app: FastAPI, admin: Api, make_user) -> None:
    user = make_user("dee@example.com")
    user_id = user.user["id"]
    assert admin.patch(f"/api/admin/users/{user_id}", json={"status": "disabled"}).status_code == 200
    assert user.get("/api/auth/me").status_code == 401  # existing sessions were revoked
    assert Api(app).login("dee@example.com", USER_PASSWORD).status_code == 401


def test_csrf_and_origin_required_for_authenticated_writes(app: FastAPI, admin: Api) -> None:
    assert admin.get("/api/auth/me", csrf=False).status_code == 200  # reads don't need the token
    assert admin.post("/api/auth/logout", csrf=False).status_code == 403
    assert admin.post("/api/auth/logout", headers={"X-CSRF-Token": "forged"}).status_code == 403
    assert admin.post("/api/auth/logout", origin="https://evil.example").status_code == 403
    assert admin.post("/api/auth/logout", origin=None).status_code == 403
    assert admin.post("/api/auth/logout").status_code == 204


def test_login_rotates_any_presented_session(app: FastAPI, admin: Api) -> None:
    old_cookie = admin.client.cookies.get("rt_session")
    assert admin.login(ADMIN_EMAIL, ADMIN_PASSWORD).status_code == 200
    assert admin.client.cookies.get("rt_session") != old_cookie
    stale = Api(app)
    stale.client.cookies.set("rt_session", old_cookie)
    assert stale.get("/api/auth/me").status_code == 401


def test_account_backoff_after_repeated_failures(app: FastAPI, admin: Api) -> None:
    api = Api(app)
    for _ in range(5):
        assert api.login(ADMIN_EMAIL, "wrong-password-attempt").status_code == 401
    blocked = api.login(ADMIN_EMAIL, ADMIN_PASSWORD)
    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) >= 1


def test_ip_limit_on_failed_logins(app: FastAPI, admin: Api) -> None:
    api = Api(app)
    for i in range(30):
        assert api.login(f"nobody{i}@example.com", "wrong-password-attempt").status_code == 401
    assert api.login("nobody-else@example.com", "wrong-password-attempt").status_code == 429


def test_password_change_signs_out_other_sessions(app: FastAPI, admin: Api, make_user) -> None:
    user = make_user("pat@example.com", name="Patricia Lee")
    other_device = Api(app)
    assert other_device.login("pat@example.com", USER_PASSWORD).status_code == 200

    bad = user.post("/api/auth/password/change",
                    json={"currentPassword": "nope-nope-nope", "newPassword": "a-brand-new-passphrase"})
    assert bad.status_code == 400
    weak = user.post("/api/auth/password/change",
                     json={"currentPassword": USER_PASSWORD, "newPassword": "patricia-password-9"})
    assert weak.status_code == 422  # contains the user's name

    old_csrf = user.csrf
    ok = user.post("/api/auth/password/change",
                   json={"currentPassword": USER_PASSWORD, "newPassword": "a-brand-new-passphrase"})
    assert ok.status_code == 200
    assert user.csrf != old_csrf
    assert user.get("/api/auth/me").status_code == 200
    assert other_device.get("/api/auth/me").status_code == 401
    assert Api(app).login("pat@example.com", "a-brand-new-passphrase").status_code == 200


def test_session_list_and_revoke(app: FastAPI, admin: Api, make_user) -> None:
    user = make_user("sam@example.com")
    laptop = Api(app)
    laptop.login("sam@example.com", USER_PASSWORD)
    sessions = user.get("/api/auth/sessions").json()
    assert len(sessions) == 2
    assert sum(s["current"] for s in sessions) == 1

    other = next(s for s in sessions if not s["current"])
    assert user.delete(f"/api/auth/sessions/{other['id']}").status_code == 204
    assert laptop.get("/api/auth/me").status_code == 401

    admin_sessions = admin.get("/api/auth/sessions").json()
    assert user.delete(f"/api/auth/sessions/{admin_sessions[0]['id']}").status_code == 404

    phone = Api(app)
    phone.login("sam@example.com", USER_PASSWORD)
    assert user.delete("/api/auth/sessions").status_code == 204
    assert phone.get("/api/auth/me").status_code == 401
    assert user.get("/api/auth/me").status_code == 200


def test_admin_reset_link_flow(app: FastAPI, admin: Api, make_user) -> None:
    user = make_user("rory@example.com")
    link = admin.post(f"/api/admin/users/{user.user['id']}/reset-link").json()
    token = link["url"].rsplit("/", 1)[-1]

    anon = Api(app)
    assert anon.get(f"/api/auth/password-reset/{token}").json() == {"valid": True, "email": None}
    response = anon.post("/api/auth/password-reset", json={"token": token, "newPassword": "fresh-start-passphrase"})
    assert response.status_code == 204
    assert user.get("/api/auth/me").status_code == 401  # all sessions revoked
    assert anon.post("/api/auth/password-reset",
                     json={"token": token, "newPassword": "another-new-passphrase"}).status_code == 400
    assert Api(app).login("rory@example.com", "fresh-start-passphrase").status_code == 200
