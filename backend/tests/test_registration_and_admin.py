from __future__ import annotations

from fastapi import FastAPI

from tests.conftest import ADMIN_EMAIL, ADMIN_PASSWORD, USER_PASSWORD, Api


def register(app: FastAPI, email: str, invite: str | None = None, password: str = USER_PASSWORD):
    body = {"email": email, "password": password, "displayName": "New Person"}
    if invite:
        body["inviteToken"] = invite
    api = Api(app)
    return api, api.post("/api/auth/register", json=body)


def invite_token(admin: Api, email: str | None = None) -> str:
    response = admin.post("/api/admin/invites", json={"email": email} if email else {})
    assert response.status_code == 201, response.text
    return response.json()["url"].rsplit("/", 1)[-1]


def test_open_registration_is_the_default(app: FastAPI, admin: Api) -> None:
    info = Api(app).get("/api/auth/registration").json()
    assert info == {"needsSetup": False, "mode": "open", "domainRestricted": False}
    api, response = register(app, "Open.User@Example.com")
    assert response.status_code == 201
    assert response.json()["user"] | {"id": None, "createdAt": None, "lastLoginAt": None} == {
        "id": None, "email": "open.user@example.com", "displayName": "New Person", "role": "user",
        "status": "active", "createdAt": None, "lastLoginAt": None}
    assert register(app, "open.user@example.com")[1].status_code == 409
    assert register(app, "weak@example.com", password="password1234")[1].status_code == 422


def test_domain_allowlist(app: FastAPI, admin: Api) -> None:
    admin.put("/api/admin/settings", json={"registrationEmailDomains": ["@Acme.com"]})
    assert Api(app).get("/api/auth/registration").json()["domainRestricted"] is True
    assert register(app, "x@other.com")[1].status_code == 403
    assert register(app, "x@acme.com")[1].status_code == 201


def test_invite_only_mode(app: FastAPI, admin: Api) -> None:
    admin.put("/api/admin/settings", json={"registrationMode": "invite"})
    assert register(app, "nope@example.com")[1].status_code == 403

    token = invite_token(admin)
    assert Api(app).get(f"/api/auth/invites/{token}").json() == {"valid": True, "email": None}
    assert register(app, "invited@example.com", invite=token)[1].status_code == 201
    assert register(app, "again@example.com", invite=token)[1].status_code == 400  # single use
    assert Api(app).get(f"/api/auth/invites/{token}").json()["valid"] is False

    bound = invite_token(admin, "bound@example.com")
    assert register(app, "someone-else@example.com", invite=bound)[1].status_code == 400
    assert register(app, "bound@example.com", invite=bound)[1].status_code == 201

    revoked = invite_token(admin)
    invite_id = next(i["id"] for i in admin.get("/api/admin/invites").json())
    assert admin.delete(f"/api/admin/invites/{invite_id}").status_code == 204
    assert register(app, "late@example.com", invite=revoked)[1].status_code == 400


def test_closed_mode(app: FastAPI, admin: Api) -> None:
    admin.put("/api/admin/settings", json={"registrationMode": "closed"})
    assert register(app, "closed@example.com")[1].status_code == 403
    token = invite_token(admin)
    assert register(app, "closed@example.com", invite=token)[1].status_code == 403


def test_admin_routes_require_admin(app: FastAPI, admin: Api, make_user) -> None:
    user = make_user("plain@example.com")
    for method, url in [("GET", "/api/admin/users"), ("GET", "/api/admin/settings"),
                        ("PUT", "/api/admin/settings"), ("GET", "/api/admin/audit-log"),
                        ("POST", "/api/admin/invites"), ("GET", "/api/admin/invites")]:
        assert user.request(method, url, json={}).status_code == 403, url
    assert Api(app).get("/api/admin/users").status_code == 401


def test_role_changes_and_last_admin_protection(app: FastAPI, admin: Api, make_user) -> None:
    admin_id = admin.user["id"]
    assert admin.patch(f"/api/admin/users/{admin_id}", json={"role": "user"}).status_code == 409
    assert admin.patch(f"/api/admin/users/{admin_id}", json={"status": "disabled"}).status_code == 409
    assert admin.delete("/api/account", json={"password": ADMIN_PASSWORD}).status_code == 409

    user = make_user("promote@example.com")
    response = admin.patch(f"/api/admin/users/{user.user['id']}", json={"role": "admin"})
    assert response.json()["role"] == "admin"
    assert user.get("/api/auth/me").status_code == 401  # role change signs the user out
    user.login("promote@example.com", USER_PASSWORD)
    assert user.get("/api/admin/users").status_code == 200

    # With two admins, the first can step down.
    assert admin.patch(f"/api/admin/users/{admin_id}", json={"role": "user"}).status_code == 200


def test_delete_user_removes_their_content(app: FastAPI, admin: Api, make_user, example) -> None:
    user = make_user("leaver@example.com")
    assert user.post("/api/master-resumes", json=example).status_code == 201
    assert admin.delete(f"/api/admin/users/{admin.user['id']}").status_code == 409  # not via admin API
    assert admin.delete(f"/api/admin/users/{user.user['id']}").status_code == 204
    assert user.get("/api/auth/me").status_code == 401
    emails = [u["email"] for u in admin.get("/api/admin/users").json()]
    assert "leaver@example.com" not in emails


def test_exposed_open_registration_notice(app: FastAPI, admin: Api) -> None:
    # The test server's base URL (http://testserver) isn't local, so open registration is flagged.
    assert "open-registration-exposed" in admin.get("/api/auth/me").json()["notices"]
    settings = admin.put("/api/admin/settings", json={"registrationMode": "invite"}).json()
    assert settings["openRegistrationExposed"] is False
    assert admin.get("/api/auth/me").json()["notices"] == []


def test_audit_log_records_security_events(app: FastAPI, admin: Api, make_user) -> None:
    make_user("audited@example.com")
    Api(app).login(ADMIN_EMAIL, "definitely-wrong-password")
    events = [e["event"] for e in admin.get("/api/admin/audit-log").json()]
    for expected in ("auth.setup", "user.register", "auth.login.failure"):
        assert expected in events
    auth_only = admin.get("/api/admin/audit-log", params={"event": "auth."}).json()
    assert auth_only and all(e["event"].startswith("auth.") for e in auth_only)


def test_profile_update_and_account_deletion(app: FastAPI, admin: Api, make_user) -> None:
    user = make_user("profile@example.com")
    assert user.patch("/api/account/profile", json={"displayName": "Renamed"}).json()["displayName"] == "Renamed"
    assert user.patch("/api/account/profile", json={"email": "new@example.com"}).status_code == 400
    assert user.patch("/api/account/profile", json={"email": ADMIN_EMAIL,
                                                    "currentPassword": USER_PASSWORD}).status_code == 409
    changed = user.patch("/api/account/profile", json={"email": "new@example.com", "currentPassword": USER_PASSWORD})
    assert changed.json()["email"] == "new@example.com"

    assert user.delete("/api/account", json={"password": "wrong-password-here"}).status_code == 400
    assert user.delete("/api/account", json={"password": USER_PASSWORD}).status_code == 204
    assert Api(app).login("new@example.com", USER_PASSWORD).status_code == 401
