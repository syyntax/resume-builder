"""Run the evals: the whole app in-process (its API, job queue, renderer) on a throwaway database.

Every case goes through the same requests the web app makes: save the master, create the application with a
cover letter, wait for it, export the PDFs. Imports upload the corpus files. Then grade.py and judge.py score
what came back.
"""

from __future__ import annotations

import io
import json
import os
import secrets
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from functools import partial
from pathlib import Path
from statistics import mean
from typing import Any, Literal

from fastapi.testclient import TestClient
from pypdf import PdfReader

from app.ai.pricing import cost_usd, load_prices
from app.config import Settings
from app.main import create_app
from tests.conftest import BASE, Api, drain
from tests.evals import cases as data
from tests.evals import grade, judge
from tests.evals.grade import Check

EMAIL, PASSWORD = "runner@example.com", secrets.token_urlsafe(18)
BASELINE_FILE = Path(__file__).with_name("baseline.json")


@dataclass
class Options:
    provider: Literal["anthropic", "fake"]
    api_key: str
    model: str
    judge_model: str | None  # None: skip the judge
    cases: list[data.Case] = field(default_factory=lambda: list(data.CASES))
    imports: list[data.ImportCase] = field(default_factory=lambda: list(data.IMPORTS))
    baseline: dict[str, float] = field(default_factory=dict)
    cap_usd: float = 100.0


def log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def _settings(**values: Any) -> Settings:
    """Settings from these values only: the host's environment (a real DATABASE_URL, SMTP) must not leak in."""
    saved = {k: os.environ.pop(k) for k in list(os.environ) if k.lower() in Settings.model_fields}
    try:
        return Settings(**values)
    finally:
        os.environ.update(saved)


def _pages(api: Api, application_id: str, doc: str) -> int | None:
    response = api.get(f"/api/applications/{application_id}/export?doc={doc}&format=pdf")
    return len(PdfReader(io.BytesIO(response.content)).pages) if response.status_code == 200 else None


def run(options: Options) -> dict[str, Any]:
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="rt-evals-") as tmp:
        settings = _settings(
            app_base_url=BASE, app_secret_key=secrets.token_urlsafe(32), allow_insecure_http=True,
            data_dir=Path(tmp), argon2_profile="cheapest", log_level="ERROR", pdf_warmup=False,
            registration_mode="closed",
            ai_provider=options.provider, anthropic_model=options.model, allowed_models=options.model,
            default_monthly_cap_usd=options.cap_usd,
        )
        application = create_app(settings)
        with TestClient(application, base_url=BASE) as main:
            application.state.test_portal = main.portal
            api = Api(application)
            setup = api.post("/api/auth/setup", json={"token": application.state.setup_token, "email": EMAIL,
                                                      "password": PASSWORD, "displayName": "Eval Runner"})
            assert setup.status_code == 201, setup.text
            saved = api.put("/api/account/api-key", json={"apiKey": options.api_key, "password": PASSWORD})
            if saved.status_code != 200:
                raise SystemExit(f"The API key was not accepted: {saved.json().get('detail')}")

            masters: dict[str, str] = {}
            for case in options.cases:
                if case.master not in masters:
                    response = api.post("/api/master-resumes", json=case.master_document())
                    assert response.status_code == 201, response.text
                    masters[case.master] = response.json()["master"]["id"]
            started_cases = {}
            for case in options.cases:
                response = api.post("/api/applications", json={
                    "masterId": masters[case.master],
                    "job": {"text": case.posting_text(), "company": case.company, "title": case.title},
                    "options": {"pageLimit": case.page_limit},
                    "coverLetter": {"generate": True, **case.letter},
                })
                assert response.status_code == 202, response.text
                started_cases[case.id] = response.json()["id"]
            started_imports = {}
            for item in options.imports:
                response = api.post(f"/api/imports?filename={item.filename}", content=item.build(),
                                    headers={"content-type": "application/octet-stream"})
                assert response.status_code == 202, response.text
                started_imports[item.id] = response.json()["id"]
            log(f"Running {len(options.cases)} cases and {len(options.imports)} imports with {options.model} "
                f"({options.provider})…")
            drain(application)
            log("Grading…")

            judge_llm = application.state.llm_factory(options.api_key) if options.judge_model else None
            case_reports = [_grade_case(api, main, case, started_cases[case.id], options, judge_llm)
                            for case in options.cases]
            import_reports = [_grade_import(api, item, started_imports[item.id]) for item in options.imports]

    report = {
        "provider": options.provider, "model": options.model, "judgeModel": options.judge_model,
        "durationSeconds": round(time.monotonic() - started),
        "cases": case_reports, "imports": import_reports,
    }
    report["summary"] = summarize(report)
    return report


def _grade_case(api: Api, main: TestClient, case: data.Case, application_id: str, options: Options,
                judge_llm: Any) -> dict[str, Any]:
    detail = api.get(f"/api/applications/{application_id}").json()
    out: dict[str, Any] = {"id": case.id, "status": detail["status"], "letterStatus": detail["coverLetterStatus"],
                           "costUsd": detail["costUsd"]}
    resume, letter = detail.get("resume"), detail.get("coverLetter")
    if detail["status"] != "done" or not resume:
        out["checks"] = [Check("completed", False, json.dumps(detail.get("error")))]
        return _dump(out)
    checks = [Check("completed", detail["coverLetterStatus"] == "ready",
                    "" if letter else f"letter: {json.dumps(detail.get('coverLetterError'))}")]

    errors = grade.guardrail_errors(resume)
    checks.append(Check("G2/G5 errors", not errors, "; ".join(f"{e['guardrail']}: {e['message']}" for e in errors)))
    flagged = grade.flagged(resume, letter)
    total = len(grade.items(resume, letter))
    out["items"], out["flagged"] = total, flagged
    planted = grade.planted(grade.plain_text(resume, letter), case.must_not_mention)
    if case.must_not_mention:
        checks.append(Check("ignored the injection", not planted, ", ".join(planted)))
    coverage = (resume.get("analysis") or {}).get("coverage") or {}
    out["coverage"], out["baseline"] = coverage.get("score"), options.baseline.get(case.id)
    checks.append(grade.coverage_check(out["coverage"], out["baseline"]))
    out["pages"] = {"resume": _pages(api, application_id, "resume"),
                    "letter": _pages(api, application_id, "cover-letter") if letter else None}
    checks.append(grade.page_check("résumé pages", out["pages"]["resume"], case.page_limit))
    if letter:
        checks.append(grade.page_check("letter pages", out["pages"]["letter"], 1))
    out["claimAudit"] = grade.claim_audit(resume, letter)

    if judge_llm is not None and letter:
        resume_md = api.get(f"/api/applications/{application_id}/export?doc=resume&format=md").text
        letter_md = api.get(f"/api/applications/{application_id}/export?doc=cover-letter&format=md").text
        verdict, usage, model = main.portal.call(partial(
            judge.judge, judge_llm, model=options.judge_model, master=case.master_document(),
            posting=case.posting_text(), resume_md=resume_md, letter_md=letter_md))
        out["judge"] = verdict.model_dump()
        out["judgeCostUsd"] = cost_usd(model, load_prices(), **asdict(usage))
    pages = out["pages"]["resume"]
    if pages is not None and pages > case.page_limit:  # what one click on "Fit to page" would do (after judging)
        fitted = api.post(f"/api/applications/{application_id}/resume/fit", json={}).json()
        removed = len(fitted.get("removed") or [])
        out["fit"] = {"fits": fitted.get("fits"), "pages": fitted.get("pages"), "removed": removed}
        how = f"leaving out {removed} bullet{'s' if removed != 1 else ''}" if removed else "tightening the layout"
        next(c for c in checks if c.name == "résumé pages").detail += (
            f"; Fit to page gets it there by {how}" if fitted.get("fits") else "; Fit to page can't fit it either")
    out["checks"] = checks
    return _dump(out)


def _grade_import(api: Api, item: data.ImportCase, import_id: str) -> dict[str, Any]:
    detail = api.get(f"/api/imports/{import_id}").json()
    out: dict[str, Any] = {"id": item.id, "status": detail["status"], "costUsd": detail.get("costUsd", 0)}
    if detail["status"] != "ready":
        out["checks"] = [Check("completed", False, json.dumps(detail.get("error")))]
        return _dump(out)
    score, missing = grade.import_fidelity(detail["document"], text=item.text(), phone=item.phone,
                                           skills=item.skills, work=data.IMPORT_WORK)
    out["fidelity"], out["missing"] = score, missing
    out["appFidelity"] = (detail.get("fidelity") or {}).get("score")  # the app's own check against the extracted text
    out["flags"] = len(detail.get("flags") or [])
    out["checks"] = [Check("fidelity", score >= grade.MIN_IMPORT_FIDELITY,
                           f"{score:.0%}" + (f"; missing {', '.join(missing[:5])}" if missing else ""))]
    return _dump(out)


def _dump(out: dict[str, Any]) -> dict[str, Any]:
    out["checks"] = [c.as_dict() for c in out["checks"]]
    return out


def summarize(report: dict[str, Any]) -> dict[str, Any]:
    cases, imports = report["cases"], report["imports"]
    checks: list[Check] = []
    total = sum(c.get("items", 0) for c in cases)
    flagged = sum(len(c.get("flagged") or {}) for c in cases)
    if total:
        rate = flagged / total
        checks.append(Check("G3/G4 rate", rate < grade.MAX_FLAGGED_RATE,
                            f"{flagged} of {total} items ({rate:.1%}); the bar is under {grade.MAX_FLAGGED_RATE:.0%}"))
    verdicts = [c["judge"] for c in cases if c.get("judge")]
    for criterion in ("relevance", "letter"):
        if not verdicts:
            checks.append(Check(f"judge: {criterion}", None, "not judged"))
            continue
        scores = [v[criterion]["score"] for v in verdicts]
        ok = mean(scores) >= judge.MIN_MEAN and min(scores) >= judge.MIN_SCORE
        checks.append(Check(f"judge: {criterion}", ok, f"mean {mean(scores):.2f}, lowest {min(scores)} "
                                                       f"(bars: mean {judge.MIN_MEAN}, lowest {judge.MIN_SCORE})"))
    failed = [f"{r['id']}: {c['name']}" + (f" ({c['detail']})" if c["detail"] else "")
              for r in [*cases, *imports] for c in r["checks"] if c["passed"] is False]
    failed += [f"{c.name} ({c.detail})" for c in checks if c.passed is False]
    cost = sum(r.get("costUsd", 0) + r.get("judgeCostUsd", 0) for r in [*cases, *imports])
    return {"passed": not failed, "failed": failed, "checks": [c.as_dict() for c in checks],
            "costUsd": round(cost, 4)}


# ---- the written report -------------------------------------------------------------------------------------

def _mark(passed: bool | None) -> str:
    return {True: "pass", False: "**FAIL**", None: "–"}[passed]


def _check(row: dict[str, Any], name: str) -> dict[str, Any] | None:
    return next((c for c in row["checks"] if c["name"] == name), None)


def markdown(report: dict[str, Any]) -> str:
    s = report["summary"]
    lines = [
        "# Eval report: " + ("offline (a harness check; the scores mean nothing)" if report["provider"] == "fake"
                             else "passed" if s["passed"] else "FAILED"), "",
        f"Model {report['model']} ({report['provider']}), judge {report['judgeModel'] or 'skipped'}. "
        f"{report['durationSeconds']} s, about ${s['costUsd']:.2f}"
        f"{' (estimated as if real: the offline model costs nothing)' if report['provider'] == 'fake' else ''}.", "",
        "| Case | Coverage (baseline) | Pages (résumé, letter) | G2/G5 | G3/G4 items | Relevance | Letter | Cost |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for c in report["cases"]:
        pages = c.get("pages") or {}
        errors = _check(c, "G2/G5 errors")
        cov = "–" if c.get("coverage") is None else f"{c['coverage']:.0%}"
        if c.get("baseline") is not None:
            cov += f" ({c['baseline']:.0%})"
        verdict = c.get("judge") or {}
        relevance, letter = ((verdict.get(k) or {}).get("score", "–") for k in ("relevance", "letter"))
        lines.append(
            f"| {c['id']} | {cov} | {pages.get('resume', '–')}, {pages.get('letter', '–')} | "
            f"{_mark(errors['passed']) if errors else '–'} | {len(c.get('flagged') or {})} of {c.get('items', 0)} | "
            f"{relevance} | {letter} | "
            f"${c['costUsd'] + c.get('judgeCostUsd', 0):.2f} |")
    lines += ["", "| Import | Fidelity | App's own check | Flags | Cost |", "|---|---|---|---|---|"]
    for i in report["imports"]:
        app_score = i.get("appFidelity")
        lines.append(f"| {i['id']} | {_check(i, 'fidelity')['detail'] if _check(i, 'fidelity') else i['status']} | "
                     f"{'–' if app_score is None else f'{app_score:.0%}'} | {i.get('flags', '–')} | "
                     f"${i['costUsd']:.2f} |")
    lines += ["", "## Overall", ""] + [f"- {c['name']}: {_mark(c['passed'])}, {c['detail']}" for c in s["checks"]]
    if s["failed"]:
        lines += ["", "## Failures", ""] + [f"- {f}" for f in s["failed"]]
    notes = [(c["id"], c) for c in report["cases"] if c.get("flagged") or c.get("claimAudit") or c.get("judge")]
    if notes:
        lines += ["", "## Details", ""]
        for case_id, c in notes:
            lines.append(f"### {case_id}")
            for target, messages in (c.get("flagged") or {}).items():
                lines += [f"- {target}: {m}" for m in messages]
            lines += [f"- claim audit, {m}" for m in c.get("claimAudit") or []]
            if c.get("judge"):
                v = c["judge"]
                lines += [f"- relevance {v['relevance']['score']}: {v['relevance']['reason']}",
                          f"- letter {v['letter']['score']}: {v['letter']['reason']}"]
                lines += [f"- problem: {p}" for p in v["problems"]]
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"
