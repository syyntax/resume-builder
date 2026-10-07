"""Guardrail G8 (DESIGN.md §9.5): every imported text field should appear in the source document.

A field passes when it fuzzy-matches the text extracted from the upload (rapidfuzz ``partial_ratio`` of
at least 90) *and* every word of three or more characters, and every number, in it appears in that text.
The second test catches what fuzzy matching alone lets through on a long bullet: "40" becoming "400", or
"EKS" becoming "GKE". Both sides are reduced to lowercase letters and digits first (accents removed), so
line breaks, hyphenation at line ends, bullet symbols, curly quotes and spacing differences from PDF
extraction don't count as mismatches. Dates, URLs, tags and skill categories are normalized or inferred by
design, so they aren't checked.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from rapidfuzz import fuzz

THRESHOLD = 90.0
MIN_CHARS = 3  # shorter values ("B.S.", "UX") match almost anywhere; checking them proves nothing

# section -> fields to check on each item ("highlights" and custom-section items are walked separately)
_FIELDS: dict[str, tuple[str, ...]] = {
    "headlines": ("text",), "summaries": ("text",),
    "work": ("company", "position", "location", "summary"),
    "projects": ("name", "description"),
    "education": ("institution", "studyType", "area", "score"),
    "certifications": ("name", "issuer", "credentialId"),
    "skills": ("name",),
    "awards": ("title", "awarder", "summary"),
    "publications": ("name", "publisher", "summary"),
    "volunteer": ("organization", "position", "summary"),
    "languages": ("language", "fluency"),
    "interests": ("name",),
}
_BASICS = ("name", "label", "email", "phone")
_NON_WORD = re.compile(r"[\W_]+")
_TOKEN = re.compile(r"[^\W_]+")


@dataclass
class FieldCheck:
    target_id: str
    field: str
    path: str
    score: float
    text: str
    missing: list[str]  # words or numbers not found in the source

    @property
    def passed(self) -> bool:
        return self.score >= THRESHOLD and not self.missing

    def as_json(self) -> dict[str, Any]:
        return {"targetId": self.target_id, "field": self.field, "path": self.path, "score": self.score,
                "text": self.text, "missing": self.missing}


def squash(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return _NON_WORD.sub("", "".join(c for c in decomposed if not unicodedata.combining(c)))


def _fields(doc: dict[str, Any]) -> list[tuple[str, str, str, str]]:
    """(target id, field, path, text) for every checked field, in document order."""
    out = []
    basics = doc.get("basics") or {}
    out += [("basics", f, f"basics.{f}", basics[f]) for f in _BASICS if isinstance(basics.get(f), str)]

    def item_fields(item: dict[str, Any], path: str, names: tuple[str, ...]) -> None:
        out.extend((item["id"], f, f"{path}.{f}", item[f]) for f in names if isinstance(item.get(f), str))
        for k, bullet in enumerate(item.get("highlights") or []):
            if isinstance(bullet, dict) and isinstance(bullet.get("text"), str):
                out.append((bullet["id"], "text", f"{path}.highlights[{k}]", bullet["text"]))

    for section, names in _FIELDS.items():
        for i, item in enumerate(doc.get(section) or []):
            item_fields(item, f"{section}[{i}]", names)
    for i, section in enumerate(doc.get("customSections") or []):
        item_fields(section, f"customSections[{i}]", ("title",))
        for j, entry in enumerate(section.get("items") or []):
            item_fields(entry, f"customSections[{i}].items[{j}]", ("title", "subtitle", "summary"))
    return out


def check(doc: dict[str, Any], source_text: str) -> dict[str, Any]:
    """The fidelity report stored with an import: overall score plus every field under the threshold."""
    source = squash(source_text)
    if not source:
        return {"available": False, "threshold": THRESHOLD, "checked": 0, "passed": 0, "score": None,
                "mismatches": []}
    checked: list[FieldCheck] = []
    for target, field, path, text in _fields(doc):
        needle = squash(text)
        if len(needle) < MIN_CHARS:
            continue
        score = 100.0 if needle in source else float(fuzz.partial_ratio(needle, source))
        missing = [t for t in dict.fromkeys(_TOKEN.findall(text))
                   if (len(squash(t)) >= MIN_CHARS or t.isdigit()) and squash(t) not in source]
        checked.append(FieldCheck(target, field, path, round(score, 1), text, missing[:5]))
    passed = sum(c.passed for c in checked)
    return {
        "available": True,
        "threshold": THRESHOLD,
        "checked": len(checked),
        "passed": passed,
        "score": round(passed / len(checked), 4) if checked else 1.0,
        "mismatches": [c.as_json() for c in checked if not c.passed],
    }
