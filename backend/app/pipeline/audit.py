"""The claim audit (stage D, guardrail G7, TLR-8): an independent model call that compares each rewritten
claim with its sources and flags embellishment.

Claims are the AI-written or edited résumé lines (bullets, headline, summary) and every cover letter
paragraph. Verdicts are stored with the text they judged, so a verdict disappears once that text changes
(see `editing.audit_warning`).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.ai.schemas import AuditResult
from app.pipeline.hydrate import MasterIndex
from app.pipeline.validators import source_text

MAX_POSTING_CHARS = 6000


def _sources(index: MasterIndex, owner: str | None, ids: list[str]) -> list[str]:
    text = source_text(index, owner, ids)
    return [line for line in text.splitlines() if line.strip()]


def resume_claims(resume: dict[str, Any], index: MasterIndex) -> list[dict[str, Any]]:
    claims = []
    for key in ("headline", "summary"):
        block = resume.get(key) or {}
        if block.get("text") and block.get("sourceIds"):
            claims.append({"id": key, "claim": block["text"], "sources": _sources(index, None, block["sourceIds"])})
    for section in resume.get("sections") or []:
        for item in section.get("items") or []:
            for bullet in item.get("bullets") or []:
                if bullet.get("origin") == "master" and not bullet.get("edited"):
                    continue  # copied word for word from the master: nothing to check
                if bullet.get("sourceIds"):
                    claims.append({"id": bullet["id"], "claim": bullet["text"],
                                   "sources": _sources(index, item["sourceId"], bullet["sourceIds"])})
    return claims


def letter_claims(letter: dict[str, Any], index: MasterIndex, posting: str) -> list[dict[str, Any]]:
    notes = ((letter.get("options") or {}).get("notes") or "").strip()
    claims = []
    for p in letter.get("paragraphs") or []:
        sources = _sources(index, None, p.get("sourceIds") or [])
        if "posting" in (p.get("companySources") or []):
            sources.append(f"[job posting] {posting[:MAX_POSTING_CHARS]}")
        if "notes" in (p.get("companySources") or []) and notes:
            sources.append(f"[candidate's notes] {notes}")
        claims.append({"id": f"letter:{p['id']}", "claim": p["text"], "sources": sources})
    return claims


def store_results(doc: dict[str, Any], claims: list[dict[str, Any]], result: AuditResult | None,
                  *, error: str | None = None) -> None:
    """Record verdicts (with the text each judged) in the document's analysis."""
    report = doc.setdefault("analysis", {})
    previous = (report.get("audit") or {}).get("results") or {}
    if result is None:
        report["audit"] = {"status": "unavailable", "message": error or "The claim audit couldn't run.",
                           "results": previous}
        return
    texts = {c["id"]: c["claim"] for c in claims}
    results = dict(previous)
    for verdict in result.verdicts:
        if verdict.claim_id in texts:
            results[verdict.claim_id] = {"verdict": verdict.verdict, "reason": verdict.reason.strip(),
                                         "text": texts[verdict.claim_id]}
    report["audit"] = {"status": "done", "checkedAt": datetime.now(UTC).isoformat(timespec="seconds"),
                       "checked": len(claims), "results": results}
