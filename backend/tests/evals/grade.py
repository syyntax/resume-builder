"""Graders for the evals (DESIGN.md §17). Pure functions over what the API returns, so they run offline too.

The bars, from the design:
- no G2 or G5 errors (a reference still unresolved after the repair pass, or a skill shown under a name that
  isn't its own or an alias);
- G3 or G4 warnings (a number or a term its sources don't support) on fewer than 5% of items;
- keyword coverage at or above the baseline (the last accepted run, in baseline.json);
- page targets met;
- import fidelity of 95% or more;
- and the judge's rubric (judge.py).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass
from typing import Any

from app.pipeline.validators import mentions

G2_G5 = {"REFERENCE_DROPPED": "G2", "SKILL_DISPLAY_REPLACED": "G5"}
G3_G4 = {"NUMBER_NOT_IN_SOURCE": "G3", "TERM_NOT_IN_SOURCE": "G4"}
MAX_FLAGGED_RATE = 0.05
COVERAGE_TOLERANCE = 0.02  # runs vary a little; a drop beyond this is a regression
MIN_IMPORT_FIDELITY = 0.95


@dataclass
class Check:
    name: str
    passed: bool | None  # None: not graded this run (no baseline yet, judge skipped)
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---- tailoring ------------------------------------------------------------------------------------------------

def guardrail_errors(resume: dict[str, Any]) -> list[dict[str, str]]:
    notices = (resume.get("analysis") or {}).get("notices") or []
    return [{"guardrail": G2_G5[n["code"]], **n} for n in notices if n.get("code") in G2_G5]


def items(resume: dict[str, Any], letter: dict[str, Any] | None) -> list[str]:
    """Every piece of generated text the fidelity checks cover, by target id."""
    ids = [b["id"] for s in resume.get("sections") or [] for i in s.get("items") or [] for b in i.get("bullets") or []]
    ids += [key for key in ("headline", "summary") if (resume.get(key) or {}).get("text")]
    if letter:
        ids += [f"letter:{p['id']}" for p in letter.get("paragraphs") or []]
        ids += [f"letter:highlight:{i}" for i, _ in enumerate(letter.get("highlights") or [])]
    return ids


def flagged(resume: dict[str, Any], letter: dict[str, Any] | None) -> dict[str, list[str]]:
    """Items with G3/G4 warnings: target id -> the warnings' messages."""
    found: dict[str, list[str]] = {}
    sources = [("", resume)] + ([("letter:", letter)] if letter else [])
    for prefix, doc in sources:
        for w in (doc.get("analysis") or {}).get("warnings") or []:
            if w.get("code") in G3_G4:
                found.setdefault(prefix + w["targetId"], []).append(f"{G3_G4[w['code']]}: {w['message']}")
    return found


def claim_audit(resume: dict[str, Any], letter: dict[str, Any] | None) -> list[str]:
    """What the claim audit (stage D) called embellished or unsupported. Reported, not graded."""
    out = []
    for doc in (resume, letter or {}):
        out += [f"{w['targetId']}: {w['message']}" for w in (doc.get("analysis") or {}).get("warnings") or []
                if str(w.get("code", "")).startswith("CLAIM_")]
    return out


def plain_text(resume: dict[str, Any], letter: dict[str, Any] | None) -> str:
    parts = [(resume.get(k) or {}).get("text", "") for k in ("headline", "summary")]
    for section in resume.get("sections") or []:
        for item in section.get("items") or []:
            parts += [b.get("text", "") for b in item.get("bullets") or []]
        for group in section.get("groups") or []:  # the skills section
            parts += [s.get("display", "") for s in group.get("items") or []]
    if letter:
        parts += [p.get("text", "") for p in letter.get("paragraphs") or []]
        parts += [f"{h.get('value', '')} {h.get('label', '')}" for h in letter.get("highlights") or []]
    return "\n".join(parts)


def planted(text: str, terms: tuple[str, ...]) -> list[str]:
    return [t for t in terms if mentions(text, t)]


def coverage_check(score: float | None, baseline: float | None) -> Check:
    if score is None:
        return Check("coverage", False, "no coverage score")
    if baseline is None:
        return Check("coverage", None, f"{score:.0%}; no baseline yet (run with --update-baseline to set one)")
    ok = score >= baseline - COVERAGE_TOLERANCE
    return Check("coverage", ok, f"{score:.0%} (baseline {baseline:.0%})")


def page_check(name: str, pages: int | None, limit: int) -> Check:
    if pages is None:
        return Check(name, False, "not rendered")
    return Check(name, pages <= limit, f"{pages} page{'s' if pages != 1 else ''} (target {limit})")


# ---- imports --------------------------------------------------------------------------------------------------

_QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-", " ": " "})


def squash(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).translate(_QUOTES)
    return re.sub(r"\s+", " ", text).strip().casefold()


def _strings(node: Any) -> list[str]:
    if isinstance(node, str):
        return [node]
    if isinstance(node, dict):
        return [s for v in node.values() for s in _strings(v)]
    if isinstance(node, list):
        return [s for v in node for s in _strings(v)]
    return []


def import_fidelity(document: dict[str, Any], *, text: list[str], phone: str | None, skills: tuple[str, ...],
                    work: dict[str, tuple[str, str]]) -> tuple[float, list[str]]:
    """The share of known facts the import recovered, and the ones it missed."""
    everything = squash("\n".join(_strings(document)))
    missing = [f"text: {t[:60]}" for t in text if squash(t) not in everything]
    if phone and re.sub(r"\D", "", phone) not in re.sub(r"\D", "", (document.get("basics") or {}).get("phone") or ""):
        missing.append(f"phone: {phone}")
    names = {squash(s.get("name", "")) for s in document.get("skills") or []}
    missing += [f"skill: {s}" for s in skills if squash(s) not in names]
    roles = {squash(w.get("company", "")): w for w in document.get("work") or []}
    for company, (position, start) in work.items():
        role = roles.get(squash(company))
        if role is None:
            missing.append(f"role: {company}")
            continue
        if squash(role.get("position", "")) != squash(position):
            missing.append(f"position at {company}: {role.get('position')!r}")
        if (role.get("startDate") or "") != start:
            missing.append(f"start date at {company}: {role.get('startDate')!r}")
    total = len(text) + bool(phone) + len(skills) + 3 * len(work)
    return round(1 - len(missing) / total, 4), missing
