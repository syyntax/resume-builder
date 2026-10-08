"""Data isolation (DESIGN.md §8.5): every route that takes a resource id must answer 404 when the
resource belongs to someone else. Routes are enumerated from the OpenAPI document, so a new route that
isn't covered here makes this test fail until it is classified."""

from __future__ import annotations

import re
from typing import Any

from fastapi import FastAPI

from tests import corpus
from tests.conftest import POSTING, TEST_KEY, USER_PASSWORD, Api, drain

# Routes whose path parameter is not an owned resource id.
PUBLIC_TOKEN_ROUTES = {"/api/auth/invites/{token}", "/api/auth/password-reset/{token}"}
SHARED_ROUTES = {"/api/templates/{key}/thumbnail.png"}  # the same for everyone: nobody owns it

# Bodies that pass request validation, so the ownership check (not a 422) decides the outcome.
BODIES: dict[tuple[str, str], Any] = {
    ("PATCH", "/api/master-resumes/{master_id}"): {"label": "Hijacked"},
    ("PUT", "/api/master-resumes/{master_id}"): "EXAMPLE",
    ("PUT", "/api/imports/{import_id}/review"): {"document": {}, "resolved": {}},
    ("POST", "/api/imports/{import_id}/accept"): {"label": "Hijacked", "document": {}},
    ("PUT", "/api/applications/{application_id}/design"): {"template": "meridian", "theme": {}},
    ("PUT", "/api/applications/{application_id}/resume"): {"document": {}},
    ("PUT", "/api/applications/{application_id}/cover-letter"): {"document": {}},
    ("POST", "/api/applications/{application_id}/cover-letter"): {},
    ("POST", "/api/applications/{application_id}/resume/refine"): {"scope": "document", "instruction": "Shorter"},
    ("POST", "/api/applications/{application_id}/cover-letter/refine"): {"instruction": "Warmer"},
    ("PUT", "/api/applications/{application_id}/analysis"): {"keywords": []},
    ("POST", "/api/applications/{application_id}/regenerate"): {},
    ("POST", "/api/applications/{application_id}/resume/fit"): {},
    ("POST", "/api/imports/{import_id}/merge-plan"): {"masterId": "mst_x", "document": {}},
    ("POST", "/api/imports/{import_id}/merge"): {"masterId": "mst_x", "document": {}, "baseVersionId": "mv_x",
                                                 "selections": {}},
}


def _routes(app: FastAPI) -> list[tuple[str, str]]:
    routes = []
    for path, operations in app.openapi()["paths"].items():
        for method in operations:
            routes.append((method.upper(), path))
    return routes


def test_users_cannot_reach_each_others_resources(app: FastAPI, admin: Api, make_user, example) -> None:
    alice, bob = make_user("alice@example.com"), make_user("bob@example.com")
    for user in (alice, bob):  # both have keys, so "no key" can't mask a missing ownership check
        user.put("/api/account/api-key", json={"apiKey": TEST_KEY, "password": USER_PASSWORD})
    created = alice.post("/api/master-resumes", json=example).json()
    application = alice.post("/api/applications", json={"masterId": created["master"]["id"],
                                                          "job": {"text": POSTING}}).json()
    upload = alice.post("/api/imports?filename=cv.pdf", content=corpus.text_pdf(),
                        headers={"content-type": "application/pdf"}).json()
    drain(app)
    accepted = alice.post("/api/imports", content=corpus.text_pdf(), headers={"content-type": "application/pdf"})
    drain(app)
    imported = alice.post(f"/api/imports/{accepted.json()['id']}/accept", json={
        "label": "From PDF", "document": alice.get(f"/api/imports/{accepted.json()['id']}").json()["document"]}).json()
    ids = {
        "master_id": created["master"]["id"],
        "version_id": created["version"]["id"],
        "session_id": alice.get("/api/auth/sessions").json()[0]["id"],
        "application_id": application["id"],
        "import_id": upload["id"],
        "revision_id": "rev_00000000000000000000000000",  # restoring someone else's: tests/test_fit.py
    }
    # A version with an original file, so the file routes find something to protect.
    file_ids = {"master_id": imported["master"]["id"], "version_id": imported["version"]["id"]}

    checked = 0
    for method, path in _routes(app):
        params = re.findall(r"{(\w+)}", path)
        if not params or path in PUBLIC_TOKEN_ROUTES | SHARED_ROUTES or path.startswith("/api/admin/"):
            continue
        unknown = [p for p in params if p not in ids]
        assert not unknown, f"{method} {path}: classify parameter(s) {unknown} in tests/test_idor.py"
        url = path.format(**(ids | file_ids if path.endswith("/source") and "master_id" in params else ids))
        body = BODIES.get((method, path))
        kwargs: dict[str, Any] = {}
        if body == "EXAMPLE":
            kwargs["json"] = example
        elif body is not None:
            kwargs["json"] = body
        response = bob.request(method, url, **kwargs)
        assert response.status_code == 404, f"{method} {url} -> {response.status_code}: {response.text[:200]}"
        checked += 1
    assert checked >= 23

    # Alice's data is untouched and still hers.
    detail = alice.get(f"/api/master-resumes/{ids['master_id']}").json()
    assert detail["label"] == "Engineering master" and detail["versionCount"] == 1
    assert bob.get("/api/master-resumes").json() == []
    assert bob.get("/api/applications").json() == []
    assert bob.get("/api/imports").json() == []
    assert alice.get(f"/api/imports/{ids['import_id']}").json()["status"] == "ready"
    source = f"/api/master-resumes/{file_ids['master_id']}/versions/{file_ids['version_id']}/source"
    assert alice.get(source).status_code == 200
    assert alice.get(f"/api/applications/{ids['application_id']}").json()["status"] == "done"
    assert alice.get("/api/auth/me").status_code == 200


def test_non_admins_get_403_on_every_admin_route(app: FastAPI, admin: Api, make_user) -> None:
    user = make_user("curious@example.com")
    target = admin.user["id"]
    for method, path in _routes(app):
        if not path.startswith("/api/admin/"):
            continue
        url = re.sub(r"{\w+}", target, path)
        response = user.request(method, url, json={})
        assert response.status_code == 403, f"{method} {url} -> {response.status_code}"
