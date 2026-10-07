from __future__ import annotations

import io
import json
import zipfile

from fastapi import FastAPI

from tests.conftest import Api

JSON_RESUME = {
    "basics": {"name": "Casey Jones", "email": "casey@example.com", "location": {"city": "Boise"}},
    "work": [{"name": "Globex", "position": "Engineer", "startDate": "2020-01-15",
              "highlights": ["Shipped things.", "Fixed other things."]}],
    "certificates": [{"name": "CKA", "issuer": "CNCF", "date": "2022-02"}],
    "skills": [{"name": "Web Development", "level": "Master", "keywords": ["HTML", "CSS"]}],
}


def test_validate_reports_paths_and_normalizes(app: FastAPI, admin: Api, example) -> None:
    ok = admin.post("/api/master-resumes/validate", json=example).json()
    assert ok["valid"] is True and ok["errors"] == [] and ok["warnings"] == []
    assert ok["summary"]["counts"]["work"] == 4
    assert ok["normalized"]["work"][0]["highlights"][3]["id"] == "acme.b4"

    bad = json.loads(json.dumps(example))
    bad["work"][1]["startDate"] = "March 2021"
    bad["skills"].append({"name": "Go"})
    result = admin.post("/api/master-resumes/validate", json=bad).json()
    assert result["valid"] is False
    assert result["errors"] == [{"path": "work[1].startDate",
                                 "message": 'expected YYYY, YYYY-MM, or YYYY-MM-DD, got "March 2021"'}]

    syntax = admin.post("/api/master-resumes/validate", content=b'{"basics": {',
                        headers={"content-type": "application/json"}).json()
    assert syntax["errors"][0]["path"] == "(document)"
    assert syntax["errors"][0]["message"].startswith("invalid JSON at line 1")


def test_json_resume_files_are_accepted(app: FastAPI, admin: Api) -> None:
    created = admin.post("/api/master-resumes", json=JSON_RESUME)
    assert created.status_code == 201, created.text
    master_id = created.json()["master"]["id"]
    content = admin.get(f"/api/master-resumes/{master_id}").json()["content"]
    assert content["work"][0]["company"] == "Globex"
    assert content["certifications"][0]["name"] == "CKA"
    assert [h["id"] for h in content["work"][0]["highlights"]] == ["work-1.b1", "work-1.b2"]
    assert content["meta"] == {"schemaVersion": "1.0", "label": "Master résumé"}


def test_create_version_and_download_lifecycle(app: FastAPI, admin: Api, example) -> None:
    created = admin.post("/api/master-resumes", json=example)
    assert created.status_code == 201
    body = created.json()
    master_id, v1 = body["master"]["id"], body["version"]["id"]
    assert body["master"]["label"] == "Engineering master" and body["version"]["versionNumber"] == 1

    same = admin.put(f"/api/master-resumes/{master_id}", json=example).json()
    assert same["createdNewVersion"] is False and same["version"]["id"] == v1

    example["work"][0]["highlights"][0]["text"] += " Extra detail."
    example["projects"] = []
    changed = admin.put(f"/api/master-resumes/{master_id}", json=example).json()
    assert changed["createdNewVersion"] is True and changed["version"]["versionNumber"] == 2
    assert "acme-b1" in changed["changes"]["changed"]
    assert {"tf-guard", "tf-guard.b1"} <= set(changed["changes"]["removed"])

    versions = admin.get(f"/api/master-resumes/{master_id}/versions").json()
    assert [v["versionNumber"] for v in versions] == [2, 1]
    old = admin.get(f"/api/master-resumes/{master_id}/versions/{v1}").json()
    assert old["content"]["projects"][0]["id"] == "tf-guard"  # versions are immutable

    download = admin.get(f"/api/master-resumes/{master_id}/versions/{v1}/normalized")
    assert download.headers["content-disposition"] == 'attachment; filename="engineering-master-v1.json"'
    assert json.loads(download.content)["basics"]["name"] == "Jordan Rivera"

    renamed = admin.patch(f"/api/master-resumes/{master_id}", json={"label": "Platform roles"}).json()
    assert renamed["label"] == "Platform roles" and renamed["versionCount"] == 2
    listed = admin.get("/api/master-resumes").json()
    assert [m["id"] for m in listed] == [master_id]

    assert admin.delete(f"/api/master-resumes/{master_id}").status_code == 204
    assert admin.get(f"/api/master-resumes/{master_id}").status_code == 404
    assert admin.get(f"/api/master-resumes/{master_id}/versions/{v1}").status_code == 404


def test_invalid_uploads_are_rejected(app: FastAPI, admin: Api, example) -> None:
    response = admin.post("/api/master-resumes", json={"basics": {"name": "No Work"}})
    assert response.status_code == 422
    assert response.json()["errors"] == [{"path": "work", "message": "add at least one work or projects entry"}]

    too_big = b'{"basics": {"name": "' + b"x" * 1_100_000 + b'"}}'
    big = admin.post("/api/master-resumes", content=too_big, headers={"content-type": "application/json"})
    assert big.status_code == 413


def test_account_export_contains_masters(app: FastAPI, admin: Api, example) -> None:
    master_id = admin.post("/api/master-resumes", json=example).json()["master"]["id"]
    export = admin.get("/api/account/export")
    assert export.status_code == 200 and export.headers["content-type"] == "application/zip"
    names = zipfile.ZipFile(io.BytesIO(export.content)).namelist()
    assert "account.json" in names
    assert f"master-resumes/{master_id}/v1.json" in names
    account = json.loads(zipfile.ZipFile(io.BytesIO(export.content)).read("account.json"))
    assert "passwordHash" not in json.dumps(account)


def test_schema_and_example_are_public(app: FastAPI) -> None:
    anon = Api(app)
    schema = anon.get("/schema/master-resume.schema.json")
    assert schema.status_code == 200 and schema.headers["content-type"].startswith("application/schema+json")
    assert schema.json()["title"] == "Resume Tailor master résumé"
    assert anon.get("/api/schema/master-resume").json() == schema.json()
    assert anon.get("/api/schema/master-resume/example").json()["basics"]["name"] == "Jordan Rivera"
    assert anon.get("/api/health").json()["status"] == "ok"
