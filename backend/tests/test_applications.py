from __future__ import annotations

import json
from typing import Any

from fastapi import FastAPI

from app.ai.fake import FakeLLM
from app.ai.llm import LLMError, LLMRequest, LLMResult, Usage
from app.db.models import Application
from app.pipeline.run import mark_interrupted
from tests.conftest import POSTING, Api, drain


def create(api: Api, master_id: str, **options: Any):
    body = {"masterId": master_id, "job": {"text": POSTING, "url": "https://globex.example/jobs/42"}}
    if options:
        body["options"] = options
    return api.post("/api/applications", json=body)


def new_master(api: Api, example: dict[str, Any]) -> str:
    return api.post("/api/master-resumes", json=example).json()["master"]["id"]


def test_requires_a_usable_key(app: FastAPI, admin: Api, make_user, example) -> None:
    user = make_user("nokey@example.com")
    response = create(user, new_master(user, example))
    assert response.status_code == 409 and response.json()["code"] == "no_api_key"


def test_full_generation_flow(app: FastAPI, admin: Api, keyed_user: Api, example) -> None:
    master_id = new_master(keyed_user, example)
    created = create(keyed_user, master_id, pageLimit=1, tone="confident")
    assert created.status_code == 202, created.text
    app_id = created.json()["id"]
    assert created.json()["status"] == "queued"
    drain(app)

    detail = keyed_user.get(f"/api/applications/{app_id}").json()
    assert detail["status"] == "done", detail["error"]
    assert detail["job"] == {"id": detail["job"]["id"], "company": "Globex", "title": "Staff Platform Engineer",
                             "url": "https://globex.example/jobs/42"}
    assert detail["master"]["label"] == "Engineering master" and detail["master"]["versionNumber"] == 1
    analysis = detail["analysis"]
    terms = {k["term"] for k in analysis["keywords"]}
    assert {"Kubernetes", "Terraform", "GCP"} <= terms

    resume = detail["resume"]
    assert resume["basics"]["name"] == "Jordan Rivera"
    assert "workAuthorization" not in resume["basics"]  # preferences.showWorkAuthorization is false
    assert resume["headline"] == {"text": "Senior Platform Engineer", "sourceIds": ["h-platform"], "edited": False,
                                  "aiText": "Senior Platform Engineer"}
    experience = next(s for s in resume["sections"] if s["type"] == "experience")
    acme = experience["items"][0]
    assert acme["company"] == "Acme Payments" and acme["startDate"] == "2021-03"
    assert all(b["sourceIds"] and b["id"].startswith("tb-") for b in acme["bullets"])
    assert resume["meta"]["master"]["versionId"] == detail["master"]["versionId"]
    coverage = resume["analysis"]["coverage"]
    assert "GCP" in coverage["gaps"] and "Kubernetes" in coverage["matched"]
    assert detail["coverageScore"] == coverage["score"] and 0 < coverage["score"] < 1
    assert any(n["type"] == "gap" and "GCP" in n["text"] for n in resume["analysis"]["notes"])
    assert detail["costUsd"] > 0

    usage = keyed_user.get("/api/account/usage").json()
    assert {s["stage"] for s in usage["byStage"]} == {"analyze", "tailor", "letter", "audit"}
    assert usage["own"]["spentUsd"] > 0 and usage["own"]["capUsd"] == 20.0 and usage["shared"] is None

    listed = keyed_user.get("/api/applications").json()
    assert [a["id"] for a in listed] == [app_id]


def test_exports(app: FastAPI, admin: Api, keyed_user: Api, example) -> None:
    app_id = create(keyed_user, new_master(keyed_user, example)).json()["id"]
    drain(app)
    md = keyed_user.get(f"/api/applications/{app_id}/export", params={"format": "md"})
    assert md.headers["content-disposition"] == \
        'attachment; filename="Jordan-Rivera_Globex_Staff-Platform-Engineer_Resume.md"'
    assert md.text.startswith("# Jordan Rivera\n**Senior Platform Engineer**")
    assert "## Experience" in md.text and "### Senior Software Engineer, Platform · Acme Payments" in md.text
    data = keyed_user.get(f"/api/applications/{app_id}/export", params={"format": "json"}).json()
    assert data["meta"]["applicationId"] == app_id
    assert keyed_user.get(f"/api/applications/{app_id}/export", params={"format": "docx"}).status_code == 422  # M6


def test_progress_events_stream(app: FastAPI, admin: Api, keyed_user: Api, example) -> None:
    app_id = create(keyed_user, new_master(keyed_user, example)).json()["id"]
    drain(app)
    with keyed_user.client.stream("GET", f"/api/applications/{app_id}/events") as response:
        assert response.headers["content-type"].startswith("text/event-stream")
        body = "".join(response.iter_text())
    assert 'event: status\ndata: {"type": "status", "status": "done"}' in body
    assert "event: done" in body


def test_spending_cap_blocks_generation(app: FastAPI, admin: Api, keyed_user: Api, example) -> None:
    keyed_user.put("/api/account/ai-settings", json={"monthlyCapUsd": 0.05})
    response = create(keyed_user, new_master(keyed_user, example))
    assert response.status_code == 409 and response.json()["code"] == "cap_reached"
    keyed_user.put("/api/account/ai-settings", json={"monthlyCapUsd": 0})  # 0 = unlimited
    assert create(keyed_user, new_master(keyed_user, example)).status_code == 202
    drain(app)


class FailingLLM(FakeLLM):
    """Fails the tailor stage with a billed error the first time, like a refusal or out-of-credit response."""

    calls: list[str] = []
    error = LLMError("out_of_credit", "This API key's Anthropic account is out of credit.")

    async def complete(self, request: LLMRequest) -> LLMResult:
        FailingLLM.calls.append(request.stage)
        if request.stage == "tailor" and FailingLLM.error is not None:
            error, FailingLLM.error = FailingLLM.error, None
            error.usage = Usage(input_tokens=1000, output_tokens=10)
            raise error
        return await super().complete(request)


def test_failure_then_retry(app: FastAPI, admin: Api, keyed_user: Api, example) -> None:
    app.state.llm_factory = FailingLLM
    app_id = create(keyed_user, new_master(keyed_user, example)).json()["id"]
    drain(app)
    failed = keyed_user.get(f"/api/applications/{app_id}").json()
    assert failed["status"] == "failed"
    assert failed["error"]["code"] == "out_of_credit"
    assert failed["costUsd"] > 0  # the billed failure still counts toward the cap

    assert keyed_user.post(f"/api/applications/{app_id}/retry").status_code == 202
    drain(app)
    assert keyed_user.get(f"/api/applications/{app_id}").json()["status"] == "done"
    assert keyed_user.post(f"/api/applications/{app_id}/retry").status_code == 409  # only failed ones


class RejectingLLM(FakeLLM):
    async def complete(self, request: LLMRequest) -> LLMResult:
        raise LLMError("key_rejected", "Anthropic rejected this API key.")


def test_rejected_key_is_marked_invalid(app: FastAPI, admin: Api, keyed_user: Api, example) -> None:
    app.state.llm_factory = RejectingLLM
    app_id = create(keyed_user, new_master(keyed_user, example)).json()["id"]
    drain(app)
    assert keyed_user.get(f"/api/applications/{app_id}").json()["error"]["code"] == "key_rejected"
    status = keyed_user.get("/api/account/api-key").json()
    assert status["status"] == "invalid" and status["using"] is None


def test_delete_application_keeps_usage(app: FastAPI, admin: Api, keyed_user: Api, example) -> None:
    master_id = new_master(keyed_user, example)
    app_id = create(keyed_user, master_id).json()["id"]
    drain(app)
    spent = keyed_user.get("/api/account/usage").json()["own"]["spentUsd"]

    in_use = keyed_user.delete(f"/api/master-resumes/{master_id}")
    assert in_use.status_code == 409 and in_use.json()["code"] == "in_use"

    assert keyed_user.delete(f"/api/applications/{app_id}").status_code == 204
    assert keyed_user.get(f"/api/applications/{app_id}").status_code == 404
    assert keyed_user.get("/api/account/usage").json()["own"]["spentUsd"] == spent
    assert keyed_user.delete(f"/api/master-resumes/{master_id}").status_code == 204


def test_master_cascade_delete(app: FastAPI, admin: Api, keyed_user: Api, example) -> None:
    master_id = new_master(keyed_user, example)
    app_id = create(keyed_user, master_id).json()["id"]
    drain(app)
    assert keyed_user.delete(f"/api/master-resumes/{master_id}", params={"cascade": "true"}).status_code == 204
    assert keyed_user.get(f"/api/applications/{app_id}").status_code == 404


def test_interrupted_jobs_are_marked_failed(app: FastAPI, admin: Api, keyed_user: Api, example) -> None:
    app_id = create(keyed_user, new_master(keyed_user, example)).json()["id"]
    drain(app)

    async def simulate_crash() -> int:
        async with app.state.sessionmaker() as db:
            row = await db.get(Application, app_id)
            row.status = "tailoring"
            await db.commit()
            return await mark_interrupted(db)

    assert app.state.test_portal.call(simulate_crash) == 1
    error = keyed_user.get(f"/api/applications/{app_id}").json()["error"]
    assert error["code"] == "interrupted"


def test_admin_usage_dashboard(app: FastAPI, admin: Api, keyed_user: Api, example) -> None:
    create(keyed_user, new_master(keyed_user, example))
    drain(app)
    rows = {r["email"]: r for r in admin.get("/api/admin/usage").json()}
    kim = rows["keyed@example.com"]
    # analyze, tailor, cover letter, claim audit
    assert kim["hasApiKey"] and kim["ownSpendUsd"] > 0 and kim["calls"] == 4 and kim["applications"] == 1
    assert json.dumps(rows).count("Jordan") == 0  # totals only, never content
    patched = admin.patch(f"/api/admin/users/{kim['userId']}", json={"sharedCapUsd": 3.5}).json()
    assert patched["sharedCapUsd"] == 3.5
