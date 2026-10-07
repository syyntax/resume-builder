"""Deterministic fidelity checks on rewritten text (DESIGN.md §9.5, G3 numbers and G4 terms) and keyword
coverage (§9.6). They produce warnings for the user to review; they never block export."""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from typing import Any

from app.ai.schemas import JobAnalysis
from app.pipeline.hydrate import MasterIndex

MAX_BULLET_CHARS = 220

_WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90, "hundred": 100,
    "half": 0.5, "dozen": 12, "double": 2, "twice": 2, "triple": 3,
}
_WORD_RE = re.compile(r"\b(" + "|".join(_WORDS) + r")\b", re.IGNORECASE)
_NUMBER_RE = re.compile(
    r"(?<![\w.])\$?(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*(%|percent\b|k\b|m\b|mm\b|b\b|bn\b|million\b|billion\b|"
    r"thousand\b|x\b|×)?",
    re.IGNORECASE,
)
_MULTIPLIER = {"k": 1e3, "thousand": 1e3, "m": 1e6, "mm": 1e6, "million": 1e6, "b": 1e9, "bn": 1e9, "billion": 1e9}


def numbers(text: str) -> set[float]:
    """Numeric values in text, normalized: '45%' == '45 percent', '$380K' == '380,000', 'two' == '2'."""
    text = _WORD_RE.sub(lambda m: str(_WORDS[m.group(1).lower()]), text)
    found: set[float] = set()
    for match in _NUMBER_RE.finditer(text):
        value = float(match.group(1).replace(",", ""))
        suffix = (match.group(2) or "").lower()
        value *= _MULTIPLIER.get(suffix, 1)
        found.add(round(value, 4))
    return found


def _fmt(value: float) -> str:
    return f"{value:,.0f}" if value == int(value) else f"{value:g}"


def term_regex(term: str) -> re.Pattern[str]:
    # Word-boundary match that also works for terms like "C++", "CI/CD" and ".NET"; allows a plural "s".
    return re.compile(rf"(?<![A-Za-z0-9]){re.escape(term)}(?:s|es)?(?![A-Za-z0-9])", re.IGNORECASE)


def mentions(text: str, term: str) -> bool:
    return bool(term) and term_regex(term).search(text) is not None


class TermGroups:
    """Equivalent names (a skill and its aliases; a keyword and its aliases), merged when they overlap."""

    def __init__(self, groups: Iterable[Iterable[str]]) -> None:
        self._group_of: dict[str, set[str]] = {}
        for names in groups:
            members = {n.strip() for n in names if n and len(n.strip()) >= 2}
            merged = set(members)
            for m in members:
                merged |= self._group_of.get(m.lower(), set())
            for m in merged:
                self._group_of[m.lower()] = merged

    def terms(self) -> list[str]:
        return sorted({m for group in self._group_of.values() for m in group}, key=len, reverse=True)

    def equivalents(self, term: str) -> set[str]:
        return self._group_of.get(term.lower(), {term})


def build_term_groups(master: dict[str, Any], analysis: JobAnalysis) -> TermGroups:
    groups = [[s["name"], *(s.get("aliases") or [])] for s in master.get("skills") or []]
    groups += [[k.term, *k.aliases] for k in analysis.keywords]
    return TermGroups(groups)


def _source_text(index: MasterIndex, owner_id: str | None, source_ids: list[str]) -> str:
    parts: list[str] = []
    for sid in source_ids:
        owner = index.owner_of.get(sid)
        if owner:
            bullet = index.bullets[owner][sid]
            parts.append(bullet.get("text", ""))
            parts += [v.get("text", "") for v in bullet.get("variants") or []]
            continue
        for section in index.items.values():
            if sid in section:
                item = section[sid]
                parts += [str(v) for k, v in item.items() if isinstance(v, str) and k != "id"]
    if owner_id:  # the parent role/project: its summary, tags, and the names of its skills
        for section in ("work", "projects"):
            item = index.items.get(section, {}).get(owner_id)
            if item:
                parts += [item.get("summary") or "", item.get("description") or "", " ".join(item.get("tags") or [])]
                for skill_id in item.get("skills") or []:
                    skill = index.items["skills"].get(skill_id)
                    if skill:
                        parts += [skill["name"], *(skill.get("aliases") or [])]
    return "\n".join(parts)


def check_text(text: str, source: str, groups: TermGroups) -> list[dict[str, str]]:
    warnings = []
    unsupported_numbers = numbers(text) - numbers(source)
    if unsupported_numbers:
        shown = ", ".join(sorted(_fmt(n) for n in unsupported_numbers))
        warnings.append({"code": "NUMBER_NOT_IN_SOURCE",
                         "message": f"Mentions {shown}, which its sources don't. Check the figure."})
    for term in groups.terms():
        if mentions(text, term) and not any(mentions(source, eq) for eq in groups.equivalents(term)):
            warnings.append({"code": "TERM_NOT_IN_SOURCE",
                             "message": f'Mentions "{term}", which its sources don\'t. Make sure it\'s accurate.'})
    return warnings


def iter_bullets(resume: dict[str, Any]) -> Iterator[tuple[str, dict[str, Any]]]:
    for section in resume.get("sections", []):
        for item in section.get("items", []):
            for bullet in item.get("bullets", []):
                yield item["sourceId"], bullet


def validate(resume: dict[str, Any], master: dict[str, Any], analysis: JobAnalysis) -> list[dict[str, str]]:
    """Attach warnings to bullets in place and return them all (with targetId) for the summary list."""
    index = MasterIndex.build(master)
    groups = build_term_groups(master, analysis)
    all_warnings: list[dict[str, str]] = []
    for owner_id, bullet in iter_bullets(resume):
        if bullet.get("origin") == "master":  # copied verbatim from the master
            continue
        warnings = check_text(bullet["text"], _source_text(index, owner_id, bullet["sourceIds"]), groups)
        if len(bullet["text"]) > MAX_BULLET_CHARS:
            warnings.append({"code": "BULLET_TOO_LONG",
                             "message": f"{len(bullet['text'])} characters; aim for {MAX_BULLET_CHARS} or fewer."})
        bullet["warnings"] = warnings
        all_warnings += [{"targetId": bullet["id"], **w} for w in warnings]
    for key in ("headline", "summary"):
        block = resume.get(key) or {}
        if block.get("text"):
            source = _source_text(index, None, block.get("sourceIds") or [])
            # The summary may draw on any visible fact, so its sources are the whole master résumé.
            if key == "summary":
                source += "\n" + "\n".join(b.get("text", "") for bs in index.bullets.values() for b in bs.values())
            for w in check_text(block["text"], source, groups):
                all_warnings.append({"targetId": key, **w})
    return all_warnings


# ---- coverage -------------------------------------------------------------------------------------------


def resume_text(resume: dict[str, Any]) -> str:
    parts = [(resume.get("headline") or {}).get("text", ""), (resume.get("summary") or {}).get("text", "")]
    for section in resume.get("sections", []):
        for group in section.get("groups", []):
            parts += [group["name"], *(i["display"] for i in group["items"])]
        for item in section.get("items", []):
            parts += [str(v) for k, v in item.items() if isinstance(v, str) and k != "sourceId"]
            parts += [b["text"] for b in item.get("bullets", [])]
    return "\n".join(parts)


def _master_text_by_id(index: MasterIndex) -> dict[str, str]:
    texts: dict[str, str] = {}
    for bullets in index.bullets.values():
        for bid, bullet in bullets.items():
            if bid not in index.hidden:
                texts[bid] = bullet.get("text", "")
    for skill_id, skill in index.items.get("skills", {}).items():
        if skill_id not in index.hidden:
            texts[skill_id] = " ".join([skill["name"], *(skill.get("aliases") or [])])
    for cert_id, cert in index.items.get("certifications", {}).items():
        if cert_id not in index.hidden:
            texts[cert_id] = cert.get("name", "")
    return texts


def coverage(resume: dict[str, Any], master: dict[str, Any], analysis: JobAnalysis) -> dict[str, Any]:
    text = resume_text(resume)
    master_texts = _master_text_by_id(MasterIndex.build(master))
    total = matched_weight = 0
    matched, missing, gaps, available = [], [], [], []
    for keyword in analysis.keywords:
        names = [keyword.term, *keyword.aliases]
        total += keyword.importance
        if any(mentions(text, n) for n in names):
            matched_weight += keyword.importance
            matched.append(keyword.term)
            continue
        missing.append(keyword.term)
        ids = [i for i, t in master_texts.items() if any(mentions(t, n) for n in names)]
        if ids:
            available.append({"term": keyword.term, "ids": ids[:10]})
        else:
            gaps.append(keyword.term)
    return {
        "score": round(matched_weight / total, 3) if total else None,
        "matched": matched,
        "missing": missing,
        "gaps": gaps,
        "available": available,
    }
