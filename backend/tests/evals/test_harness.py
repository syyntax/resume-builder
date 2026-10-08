"""The eval harness itself, offline: graders, the judge's request, and a small run against the fake model."""

from __future__ import annotations

from typing import Any

import anyio
import jsonschema
import pytest

from app.ai.llm import LLMRequest, LLMResult, Usage
from tests import corpus
from tests.evals import cases as data
from tests.evals import grade, judge
from tests.evals.__main__ import main
from tests.evals.harness import Options, markdown, run, summarize


def resume(**extra: Any) -> dict[str, Any]:
    return {
        "headline": {"text": "Senior Platform Engineer"},
        "summary": {"text": ""},
        "sections": [
            {"type": "experience", "items": [{"sourceId": "acme", "bullets": [
                {"id": "b1", "text": "Led the migration of 40 services to Kubernetes."},
                {"id": "b2", "text": "Cut costs by 45% with Rust."},
            ]}]},
            {"type": "skills", "groups": [{"name": "Cloud", "items": [{"skillId": "aws", "display": "AWS"}]}]},
        ],
        "analysis": {"notices": [], "warnings": []},
        **extra,
    }


def test_guardrail_errors_and_fidelity_rate() -> None:
    doc = resume(analysis={
        "notices": [{"targetId": "draft", "code": "REFERENCE_DROPPED", "message": "work: 'x' isn't visible"},
                    {"targetId": "go", "code": "SKILL_DISPLAY_REPLACED", "message": "used the skill's name"},
                    {"targetId": "b1", "code": "PINNED_ADDED", "message": "added a pinned bullet"}],
        "warnings": [{"targetId": "b2", "code": "NUMBER_NOT_IN_SOURCE", "message": "Mentions 45"},
                     {"targetId": "b2", "code": "TERM_NOT_IN_SOURCE", "message": 'Mentions "Rust"'},
                     {"targetId": "b1", "code": "BULLET_TOO_LONG", "message": "too long"}],
    })
    letter = {"paragraphs": [{"id": "p1", "text": "Hello"}], "highlights": [{"value": "45%", "label": "faster"}],
              "analysis": {"warnings": [{"targetId": "p1", "code": "TERM_NOT_IN_SOURCE", "message": "Mentions Go"}]}}
    assert [e["guardrail"] for e in grade.guardrail_errors(doc)] == ["G2", "G5"]
    assert grade.items(doc, letter) == ["b1", "b2", "headline", "letter:p1", "letter:highlight:0"]  # no empty summary
    assert grade.flagged(doc, letter) == {"b2": ["G3: Mentions 45", 'G4: Mentions "Rust"'],
                                          "letter:p1": ["G4: Mentions Go"]}
    text = grade.plain_text(doc, letter)
    assert "AWS" in text and "Hello" in text
    assert grade.planted(text, ("Rust", "PhD")) == ["Rust"]


def test_coverage_and_page_checks() -> None:
    assert grade.coverage_check(0.8, None).passed is None
    assert grade.coverage_check(0.79, 0.8).passed is True  # within the tolerance
    assert grade.coverage_check(0.7, 0.8).passed is False
    assert grade.page_check("résumé pages", 1, 1).passed and not grade.page_check("résumé pages", 2, 1).passed
    assert grade.page_check("letter pages", None, 1).passed is False


def test_import_fidelity_counts_each_fact() -> None:
    document = {
        "basics": {"name": corpus.NAME, "email": corpus.CONTACT[1], "phone": "555.010.0199",
                   "summary": corpus.SUMMARY.replace(" ", "  ")},  # whitespace doesn't matter
        "work": [{"company": c, "position": p, "startDate": d, "highlights": []}
                 for c, (p, d) in data.IMPORT_WORK.items()],
        "skills": [{"name": "Kubernetes"}, {"name": "Terraform"}, {"name": "AWS"}],
    }
    linkedin = next(i for i in data.IMPORTS if i.id == "linkedin-pdf")
    score, missing = grade.import_fidelity(document, text=linkedin.text(), phone=linkedin.phone,
                                           skills=linkedin.skills, work=data.IMPORT_WORK)
    # no bullets, education or certification: 8 of the 11 text facts missing; everything else found
    assert len(missing) == 8 and all(m.startswith("text: ") for m in missing)
    assert score == round(1 - 8 / (11 + 0 + 3 + 9), 4)
    text_pdf = data.IMPORTS[0]
    _, missing = grade.import_fidelity(document, text=[], phone=text_pdf.phone, skills=text_pdf.skills, work={})
    assert missing == ["skill: Python", "skill: Go", "skill: SQL"]  # and the phone matched by its digits


def test_a_scan_only_has_to_recover_what_is_visible() -> None:
    scan = next(i for i in data.IMPORTS if i.line_limit)
    long_bullet = corpus.WORK[0][5][0]
    visible = next(t for t in scan.text() if long_bullet.startswith(t))
    assert visible != long_bullet and len("- " + visible) <= 110 and long_bullet[len(visible)] == " "


class StubJudge:
    def __init__(self) -> None:
        self.requests: list[LLMRequest] = []

    async def complete(self, request: LLMRequest) -> LLMResult:
        self.requests.append(request)
        data = {"relevance": {"score": 4, "reason": "Leads with Kubernetes."},
                "letter": {"score": 3, "reason": "Generic opening."}, "problems": ["The opening is generic."]}
        jsonschema.validate(data, request.schema)  # what the real API would enforce
        return LLMResult(data=data, usage=Usage(input_tokens=1000, output_tokens=100), model=request.model)


def test_the_judge_sends_everything_and_reads_a_valid_verdict() -> None:
    llm = StubJudge()
    verdict, usage, model = anyio.run(lambda: judge.judge(
        llm, model="claude-opus-5-5", master={"basics": {"name": "Jordan"}}, posting="Platform Engineer at Globex",
        resume_md="# Jordan", letter_md="Dear Hiring Team,"))
    assert verdict.relevance.score == 4 and verdict.problems == ["The opening is generic."]
    assert usage.output_tokens == 100 and model == "claude-opus-5-5"
    sent = "\n".join(b.text for b in llm.requests[0].blocks)
    assert all(part in sent for part in ("Jordan", "Platform Engineer at Globex", "Dear Hiring Team", "relevance:"))
    schema = llm.requests[0].schema
    assert schema["additionalProperties"] is False and "maxItems" not in str(schema)  # what structured outputs accept


def test_the_summary_applies_the_bars() -> None:
    def case(relevance: int, letter: int, flagged: int) -> dict[str, Any]:
        return {"id": "c", "items": 20, "flagged": {f"b{i}": ["G3"] for i in range(flagged)}, "costUsd": 0.5,
                "judge": {"relevance": {"score": relevance}, "letter": {"score": letter}}, "checks": []}

    passing = summarize({"cases": [case(4, 4, 0), case(4, 3, 1)], "imports": []})
    assert passing["passed"] and passing["costUsd"] == 1.0
    failing = summarize({"cases": [case(4, 2, 1), case(3, 4, 2)], "imports": []})
    assert not failing["passed"]
    assert any(f.startswith("G3/G4 rate") for f in failing["failed"])  # 3 of 40 items is 7.5%
    assert any(f.startswith("judge: letter") for f in failing["failed"])  # a 2 is below the lowest allowed


def test_an_offline_run_end_to_end() -> None:
    cases = [c for c in data.CASES if c.id in ("initrode-platform-injection", "pinecrest-senior-data-analyst")]
    imports = [i for i in data.IMPORTS if i.id in ("text-pdf", "docx")]
    report = run(Options(provider="fake", api_key="sk-ant-api03-offline-eval-0123456789abcdefWXYZ",
                         model="claude-opus-5-5", judge_model=None, cases=cases, imports=imports,
                         baseline={"pinecrest-senior-data-analyst": 0.5}))
    by_id = {c["id"]: c for c in report["cases"]}
    for c in report["cases"]:
        checks = {k["name"]: k["passed"] for k in c["checks"]}
        assert checks["completed"] and checks["G2/G5 errors"], c
        assert c["items"] > 5 and c["pages"]["resume"] >= 1 and c["pages"]["letter"] == 1
    assert {k["name"]: k["passed"] for k in by_id["initrode-platform-injection"]["checks"]}["ignored the injection"]
    assert {k["name"]: k["passed"] for k in by_id["pinecrest-senior-data-analyst"]["checks"]}["coverage"] is True
    assert [i["fidelity"] for i in report["imports"]] == [1.0, 1.0]
    text = markdown(report)
    assert "| initrode-platform-injection |" in text and "| docx | 100% |" in text and "judge: letter: –" in text


def test_live_runs_need_their_own_key(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.delenv("EVAL_ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-not-for-evals")  # never used: evals have their own variable
    with pytest.raises(SystemExit):
        main(["--live"])
    assert "EVAL_ANTHROPIC_API_KEY" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        main(["--update-baseline"])
