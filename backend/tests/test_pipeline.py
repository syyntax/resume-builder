from __future__ import annotations

import json
from typing import Any

import anthropic
import httpx2
import pytest
from fastapi import FastAPI

from app.ai import llm as llm_module
from app.ai import stages as ai_stages
from app.ai.fake import FakeLLM
from app.ai.llm import AnthropicLLM, Block, LLMError, LLMRequest, LLMResult, Usage, _map_api_error
from app.ai.schemas import JobAnalysis, TailorDraft, strict_schema
from app.masters.normalize import normalize
from app.pipeline.hydrate import hydrate
from app.pipeline.validators import coverage, validate
from tests.conftest import POSTING, Api, drain

# ---- helpers ----------------------------------------------------------------------------------------


@pytest.fixture
def master(example) -> dict[str, Any]:
    return normalize(example).document


def analysis(**overrides: Any) -> JobAnalysis:
    base = {
        "company": "Globex", "title": "Staff Platform Engineer", "seniority": "staff", "location": None,
        "employmentType": None, "roleSummary": "Own the platform.", "requirements": [], "responsibilities": [],
        "keywords": [
            {"term": "Kubernetes", "aliases": ["K8s"], "importance": 3, "category": "technology", "mustInclude": False},
            {"term": "GCP", "aliases": ["Google Cloud"], "importance": 2, "category": "technology",
             "mustInclude": False},
            {"term": "Backstage", "aliases": [], "importance": 1, "category": "technology", "mustInclude": False},
        ],
        "companySignals": [], "match": [], "fit": {"rating": "strong", "rationale": "ok"}, "suggestedEmphasis": [],
    }
    return JobAnalysis.model_validate({**base, **overrides})


def draft(**overrides: Any) -> TailorDraft:
    base: dict[str, Any] = {
        "headline": {"text": "Senior Platform Engineer", "sourceIds": ["h-platform"]},
        "summary": {"text": "Platform engineer with 9 years of experience.", "sourceIds": ["s-platform"]},
        "sectionOrder": ["summary", "experience", "skills", "certifications"],
        "experience": [{"workId": "acme", "bullets": [
            {"text": "Migrated 40 payment services to Kubernetes, cutting p99 latency 45%.",
             "sourceIds": ["acme-b1"], "relevance": 5, "keywords": ["Kubernetes"]},
        ]}],
        "earlierExperienceIds": ["hooli"],
        "projects": [],
        "skills": [{"group": "Cloud", "skills": [{"skillId": "kubernetes", "display": "K8s"}]}],
        "include": {"education": [], "certifications": ["cka"], "awards": [], "publications": [], "volunteer": [],
                    "languages": [], "customSections": []},
        "notes": [],
    }
    base.update(overrides)
    return TailorDraft.model_validate(base)


# ---- hydration (G1, G2, G5) --------------------------------------------------------------------------


def test_hydration_copies_facts_from_the_master(master) -> None:
    result = hydrate(draft(), master)
    assert result.problems == []
    exp = result.resume["sections"][0]
    assert exp["type"] == "experience"
    acme = exp["items"][0]
    assert (acme["company"], acme["position"], acme["startDate"]) == ("Acme Payments",
                                                                       "Senior Software Engineer, Platform", "2021-03")
    assert result.resume["sections"][1]["type"] == "earlier-experience"
    assert result.resume["sections"][1]["items"][0]["company"] == "Hooli"
    assert [s["type"] for s in result.resume["sections"]] == ["experience", "earlier-experience", "skills",
                                                              "certifications"]
    assert result.resume["sections"][2]["groups"][0]["items"] == [{"skillId": "kubernetes", "display": "K8s"}]


def test_pinned_bullets_are_always_included(master) -> None:
    result = hydrate(draft(experience=[{"workId": "acme", "bullets": []}]), master)
    bullets = result.resume["sections"][0]["items"][0]["bullets"]
    assert [(b["sourceIds"], b["origin"]) for b in bullets] == [(["acme-b1"], "master")]
    assert result.notices[0]["code"] == "PINNED_ADDED"


def test_bad_references_are_reported_and_dropped(master) -> None:
    master["work"][1]["highlights"][0]["hidden"] = True  # initech-2.b1
    bad = draft(
        experience=[
            {"workId": "acme", "bullets": [
                {"text": "Rebuilt the build on Bazel.", "sourceIds": ["initech-2.b2"], "relevance": 3,
                 "keywords": []},
                {"text": "Ok", "sourceIds": ["acme-b1"], "relevance": 5, "keywords": []},
            ]},
            {"workId": "initech-2", "bullets": [
                {"text": "Hidden fact.", "sourceIds": ["initech-2.b1"], "relevance": 3, "keywords": []},
            ]},
            {"workId": "made-up-employer", "bullets": []},
        ],
        skills=[{"group": "X", "skills": [{"skillId": "cobol", "display": "COBOL"},
                                           {"skillId": "go", "display": "Golang"},
                                           {"skillId": "python", "display": "Snake language"}]}],
    )
    result = hydrate(bad, master)
    text = " | ".join(result.problems)
    assert "'initech-2.b2'" in text and "'initech-2.b1'" in text and "'made-up-employer'" in text
    assert "'cobol'" in text
    items = result.resume["sections"][0]["items"]
    assert [i["sourceId"] for i in items] == ["acme", "initech-2"]
    assert [b["sourceIds"] for b in items[0]["bullets"]] == [["acme-b1"]]
    assert items[1]["bullets"] == []
    skills = next(s for s in result.resume["sections"] if s["type"] == "skills")["groups"][0]["items"]
    assert skills == [{"skillId": "go", "display": "Golang"}, {"skillId": "python", "display": "Python"}]
    assert any(n["code"] == "SKILL_DISPLAY_REPLACED" for n in result.notices)


# ---- validators (G3, G4) and coverage -----------------------------------------------------------------


def test_validators_flag_unsupported_numbers_and_terms(master) -> None:
    d = draft(experience=[{"workId": "acme", "bullets": [
        {"text": "Migrated 40 services to K8s on GCP, cutting latency 50%.", "sourceIds": ["acme-b1"],
         "relevance": 5, "keywords": []},
        {"text": "Built an SLO-driven canary pipeline that cut failed releases by 60%.", "sourceIds": ["acme-b3"],
         "relevance": 4, "keywords": []},
    ]}])
    resume = hydrate(d, master).resume
    warnings = validate(resume, master, analysis())
    bullets = resume["sections"][0]["items"][0]["bullets"]
    first = {w["code"]: w["message"] for w in bullets[0]["warnings"]}
    assert "50" in first["NUMBER_NOT_IN_SOURCE"] and "45" not in first["NUMBER_NOT_IN_SOURCE"]
    assert '"GCP"' in first["TERM_NOT_IN_SOURCE"]
    assert "K8s" not in json.dumps(first)  # an alias of a skill its source mentions is fine
    assert bullets[1]["warnings"] == []
    assert {w["targetId"] for w in warnings} == {bullets[0]["id"]}


def test_coverage_score_and_suggestions(master) -> None:
    resume = hydrate(draft(), master).resume
    cover = coverage(resume, master, analysis())
    assert cover["matched"] == ["Kubernetes"]
    assert cover["gaps"] == ["GCP"]
    assert cover["available"][0]["term"] == "Backstage" and "acme-b2" in cover["available"][0]["ids"]
    assert cover["score"] == round(3 / 6, 3)


# ---- repair pass ----------------------------------------------------------------------------------------


class RepairingLLM(FakeLLM):
    """First tailor answer cites another role's bullet; the repair answer is clean."""

    stages: list[str] = []

    async def complete(self, request: LLMRequest) -> LLMResult:
        RepairingLLM.stages.append(request.stage)
        result = await super().complete(request)
        if request.stage == "tailor":
            result.data["experience"][0]["bullets"][0]["sourceIds"] = ["initech-2.b1"]
        if request.stage == "tailor_repair":
            assert "<repair>" in request.blocks[2].text and "initech-2.b1" in request.blocks[2].text
        return result


def test_unresolved_references_trigger_one_repair(app: FastAPI, admin: Api, keyed_user: Api, example) -> None:
    RepairingLLM.stages = []
    app.state.llm_factory = RepairingLLM
    master_id = keyed_user.post("/api/master-resumes", json=example).json()["master"]["id"]
    app_id = keyed_user.post("/api/applications", json={"masterId": master_id, "job": {"text": POSTING}}).json()["id"]
    drain(app)
    detail = keyed_user.get(f"/api/applications/{app_id}").json()
    assert detail["status"] == "done"
    assert RepairingLLM.stages == ["analyze", "tailor", "tailor_repair"]
    stages = {s["stage"] for s in keyed_user.get("/api/account/usage").json()["byStage"]}
    assert stages == {"analyze", "tailor", "tailor_repair"}


# ---- structured-output schemas -----------------------------------------------------------------------------


def _property_sets(schema: dict[str, Any]) -> dict[str, list[str]]:
    defs = schema.get("$defs", {})
    return {"(root)": list(schema["properties"]), **{name: list(d["properties"]) for name, d in defs.items()}}


@pytest.mark.parametrize("model", [JobAnalysis, TailorDraft])
def test_strict_schema_keeps_every_field(model: type[JobAnalysis] | type[TailorDraft]) -> None:
    # A field named like a schema keyword ("title", "default", "pattern") is a field, not a keyword to strip.
    original = model.model_json_schema(by_alias=True, mode="validation")
    strict = strict_schema(model)
    assert _property_sets(strict) == _property_sets(original)
    for props in [strict["properties"], *(d["properties"] for d in strict.get("$defs", {}).values())]:
        for field in props.values():
            assert not {"title", "default", "minLength"} & set(field)


def test_strict_schema_requires_every_field_and_closes_objects() -> None:
    def objects(node: Any) -> list[dict[str, Any]]:
        if isinstance(node, list):
            return [o for n in node for o in objects(n)]
        if not isinstance(node, dict):
            return []
        own = [node] if node.get("type") == "object" else []
        return own + [o for v in node.values() for o in objects(v)]

    for model in (JobAnalysis, TailorDraft):
        for obj in objects(strict_schema(model)):
            assert obj["additionalProperties"] is False
            assert obj["required"] == list(obj["properties"])


def test_enum_values_are_matched_case_insensitively() -> None:
    # Structured outputs may change an enum value's capitalization; accept it and store the canonical form.
    result = analysis(
        seniority="Senior",
        requirements=[{"id": "r1", "text": "Kubernetes", "kind": "Required", "category": "Skill", "keywords": []}],
        match=[{"requirementId": "r1", "status": "MET", "evidenceIds": [], "note": ""}],
        fit={"rating": "Strong", "rationale": "ok"},
    )
    assert (result.seniority, result.requirements[0].kind, result.requirements[0].category) == (
        "senior", "required", "skill")
    assert (result.match[0].status, result.fit.rating) == ("met", "strong")
    draft = TailorDraft.model_validate({
        "headline": {"text": "", "sourceIds": []}, "summary": {"text": "", "sourceIds": []},
        "sectionOrder": ["Summary", "EXPERIENCE"], "experience": [], "earlierExperienceIds": [], "projects": [],
        "skills": [], "include": {"education": [], "certifications": [], "awards": [], "publications": [],
                                  "volunteer": [], "languages": [], "customSections": []},
        "notes": [{"type": "Gap", "text": "No Rust."}],
    })
    assert draft.section_order == ["summary", "experience"] and draft.notes[0].type == "gap"
    with pytest.raises(ValueError):
        analysis(seniority="wizard")


def test_invalid_output_is_logged_without_content(caplog: pytest.LogCaptureFixture) -> None:
    result = LLMResult(data={"company": "Secret Corp candidate text"}, usage=Usage(), model="m", request_id="req_1")
    with caplog.at_level("WARNING", logger="resume_tailor.ai"), pytest.raises(LLMError) as raised:
        ai_stages._validate("analyze", JobAnalysis, result)
    assert raised.value.code == "bad_output"
    assert "analyze output from m failed validation (request req_1)" in caplog.text
    assert "roleSummary: Field required" in caplog.text and "Secret Corp" not in caplog.text


# ---- the Anthropic client ---------------------------------------------------------------------------------


def _response(status: int, headers: dict[str, str] | None = None) -> httpx2.Response:
    return httpx2.Response(status, headers=headers or {}, request=httpx2.Request("POST", "https://api.anthropic.com"))


@pytest.mark.parametrize(("exc", "code"), [
    (anthropic.AuthenticationError("bad key", response=_response(401), body=None), "key_rejected"),
    (anthropic.PermissionDeniedError("nope", response=_response(403), body=None), "key_rejected"),
    (anthropic.RateLimitError("slow", response=_response(429, {"retry-after": "30"}), body=None), "rate_limited"),
    (anthropic.NotFoundError("model", response=_response(404), body=None), "model_unavailable"),
    (anthropic.BadRequestError("Your credit balance is too low", response=_response(400), body=None),
     "out_of_credit"),
    (anthropic.BadRequestError("schema invalid", response=_response(400), body=None), "bad_request"),
    (anthropic.InternalServerError("boom", response=_response(500), body=None), "provider_unavailable"),
    (anthropic.APIConnectionError(request=httpx2.Request("POST", "https://api.anthropic.com")),
     "provider_unavailable"),
])
def test_api_errors_map_to_user_facing_codes(exc: Exception, code: str) -> None:
    error = _map_api_error(exc)
    assert error.code == code
    if code == "rate_limited":
        assert error.retry_after == 30


class _Message:
    def __init__(self, stop_reason: str, text: str) -> None:
        self.stop_reason, self.model, self.stop_details = stop_reason, "claude-opus-5-5", None
        self.content = [type("T", (), {"type": "thinking"})(), type("T", (), {"type": "text", "text": text})()]
        self.usage = type("U", (), {"input_tokens": 1200, "output_tokens": 300, "cache_read_input_tokens": 900,
                                    "cache_creation_input_tokens": 0})()


class _Stream:
    request_id = "req_123"

    def __init__(self, message: _Message) -> None:
        self.message = message

    async def __aenter__(self) -> _Stream:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def get_final_message(self) -> _Message:
        return self.message


def _request(model: str = "claude-opus-5-5") -> LLMRequest:
    return LLMRequest(stage="analyze", model=model, system="sys", blocks=[Block("master", cache=True), Block("task")],
                      schema={"type": "object"}, effort="medium", max_tokens=1000)


@pytest.mark.anyio
async def test_anthropic_request_shape_and_result(monkeypatch: pytest.MonkeyPatch) -> None:
    client = AnthropicLLM("sk-ant-test-0000000000000000")
    seen: dict[str, Any] = {}

    def fake_stream(**kwargs: Any) -> _Stream:
        seen.update(kwargs)
        return _Stream(_Message("end_turn", '{"ok": true}'))

    monkeypatch.setattr(client._client.beta.messages, "stream", fake_stream)
    result = await client.complete(_request())
    assert result.data == {"ok": True} and result.request_id == "req_123"
    assert (result.usage.input_tokens, result.usage.cache_read_tokens) == (1200, 900)
    assert seen["output_config"] == {"format": {"type": "json_schema", "schema": {"type": "object"}},
                                     "effort": "medium"}
    assert seen["betas"] == [llm_module.FALLBACK_BETA] and seen["fallbacks"] == "default"
    assert seen["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert seen["messages"][0]["content"][0]["cache_control"] == {"type": "ephemeral"}
    assert "cache_control" not in seen["messages"][0]["content"][1]
    assert "thinking" not in seen  # always on for this model; depth comes from effort

    seen.clear()
    await client.complete(_request("claude-haiku-4-5"))
    assert "effort" not in seen["output_config"] and "fallbacks" not in seen


@pytest.mark.anyio
@pytest.mark.parametrize(("stop", "code"), [("refusal", "refused"), ("max_tokens", "truncated")])
async def test_anthropic_billed_failures_carry_usage(monkeypatch: pytest.MonkeyPatch, stop: str, code: str) -> None:
    client = AnthropicLLM("sk-ant-test-0000000000000000")
    monkeypatch.setattr(client._client.beta.messages, "stream", lambda **_: _Stream(_Message(stop, "{")))
    with pytest.raises(LLMError) as info:
        await client.complete(_request())
    assert info.value.code == code and info.value.usage is not None and info.value.usage.output_tokens == 300
