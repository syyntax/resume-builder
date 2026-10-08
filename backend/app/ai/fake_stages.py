"""Stages C (letter), R (refine) and D (audit) for the offline stand-in model (AI_PROVIDER=fake).

Mechanical and deterministic: the letter stitches together cited bullets, refinements swap a leading verb or
shorten a line, and the audit flags any claim with a number its sources don't contain. Enough to exercise
the whole workspace without an API key; never a substitute for the real model.
"""

from __future__ import annotations

import re
from typing import Any

from app.pipeline.validators import numbers

_VERBS = {"Led": "Drove", "Built": "Delivered", "Designed": "Architected", "Cut": "Reduced", "Reduced": "Cut",
          "Created": "Developed", "Developed": "Created", "Mentored": "Coached", "Ran": "Managed",
          "Drove": "Led", "Delivered": "Built", "Maintained": "Supported", "Wrote": "Authored"}


def _swap_verb(text: str) -> str:
    first, _, rest = text.partition(" ")
    return f"{_VERBS[first]} {rest}" if first in _VERBS else f"Delivered: {text[0].lower()}{text[1:]}"


def _shorten(text: str) -> str:
    head = re.split(r",\s|;\s| and ", text, maxsplit=1)[0].rstrip(".")
    return f"{head}." if head != text.rstrip(".") else text


def _rewrite(text: str, instruction: str) -> str:
    return _shorten(text) if "short" in instruction.lower() else _swap_verb(text)


def _bullets(resume: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    return [(item.get("sourceId", ""), b) for s in resume.get("sections") or [] for item in s.get("items") or []
            for b in item.get("bullets") or []]


def letter(analysis: dict[str, Any], resume: dict[str, Any], notes: str) -> dict[str, Any]:
    bullets = [b for _, b in _bullets(resume)]
    title = analysis.get("title") or "this role"
    company = analysis.get("company") or "your team"
    top = bullets[0] if bullets else {"text": "", "sourceIds": []}
    evidence = bullets[1:3]
    requirement = next(iter(analysis.get("requirements") or []), {"id": "", "text": "the work described"})
    has_notes = notes.strip() not in ("", "(none)")
    motivation = f"The posting's focus on {requirement['text'].rstrip('.').lower()} matches the work I want to do next."
    if has_notes:
        motivation += f" {notes.strip()}"
    paragraphs = [
        {"role": "opening", "text": f"I'm applying for the {title} role at {company}. {top['text']}",
         "sourceIds": top.get("sourceIds", []), "jobRefs": [requirement["id"]] if requirement["id"] else [],
         "companySources": []},
        {"role": "evidence",
         "text": " ".join(b["text"] for b in evidence) or "My recent work is summarized in my résumé.",
         "sourceIds": [s for b in evidence for s in b.get("sourceIds", [])], "jobRefs": [], "companySources": []},
        {"role": "motivation", "text": motivation, "sourceIds": [], "jobRefs": [],
         "companySources": ["posting", "notes"] if has_notes else ["posting"]},
        {"role": "closing", "text": "I'd welcome the chance to talk about how I could help. Thank you for your time.",
         "sourceIds": [], "jobRefs": [], "companySources": []},
    ]
    highlights = []
    for b in bullets:  # up to three key numbers, each from a cited bullet
        number = re.search(r"\$?\d[\d,.]*\s?(?:%|K|M|x)?", b["text"])
        if number and len(highlights) < 3:
            label = " ".join(b["text"].replace(number.group(0), "").split()[:6]).rstrip(",;.")
            highlights.append({"value": number.group(0).strip(), "label": label, "sourceIds": b.get("sourceIds", [])})
    return {"subject": title if title != "this role" else "", "paragraphs": paragraphs, "highlights": highlights,
            "notes": [] if has_notes else [{"type": "suggestion", "text": "Add a sentence about why this company "
                                                                          "appeals to you."}]}


def _request(text: str) -> dict[str, str]:
    fields = {}
    for line in text.splitlines():
        key, _, value = line.partition(": ")
        if key in ("Scope", "Target", "Instruction"):
            fields[key.lower()] = value
    return fields


def refine(resume: dict[str, Any], request: str) -> dict[str, Any]:
    req = _request(request)
    scope, target, instruction = req.get("scope", ""), req.get("target", ""), req.get("instruction", "")
    empty = {"text": "", "sourceIds": []}
    out: dict[str, Any] = {"headline": empty, "summary": empty, "bullets": [], "items": [], "notes": []}
    bullets = _bullets(resume)
    if scope == "bullet":
        bullet_id = target.split(" ")[1] if target.startswith("bullet ") else ""
        out["bullets"] = [{"targetId": b["id"], "text": _rewrite(b["text"], instruction), "sourceIds": b["sourceIds"],
                           "keywords": []} for _, b in bullets if b["id"] == bullet_id]
    elif scope == "item":
        item_id = target.removeprefix("all bullets of ").split(":")[0]
        out["items"] = [{"itemId": item_id, "bullets": [
            {"targetId": b["id"], "text": _rewrite(b["text"], instruction), "sourceIds": b["sourceIds"], "keywords": []}
            for owner, b in bullets if owner == item_id]}]
    elif scope in ("headline", "summary"):
        current = resume.get(scope) or ""
        out[scope] = {"text": _rewrite(current, instruction) if current else "", "sourceIds": []}
    else:  # the whole document
        out["bullets"] = [{"targetId": b["id"], "text": _rewrite(b["text"], instruction), "sourceIds": b["sourceIds"],
                           "keywords": []} for _, b in bullets]
    if "metric" in instruction.lower() or "number" in instruction.lower():
        out["notes"].append({"type": "suggestion", "text": "I can't add numbers your master résumé doesn't have."})
    return out


def refine_letter(letter_doc: dict[str, Any], request: str) -> dict[str, Any]:
    req = _request(request)
    target, instruction = req.get("target", ""), req.get("instruction", "")
    paragraph_id = target.split(" ")[1].rstrip(":") if target.startswith("paragraph ") else ""
    chosen = [p for p in letter_doc.get("paragraphs") or [] if not paragraph_id or p["id"] == paragraph_id]
    return {"paragraphs": [{"targetId": p["id"], "role": p["role"], "text": _rewrite(p["text"], instruction),
                            "sourceIds": p.get("sourceIds", []), "jobRefs": p.get("jobRefs", []),
                            "companySources": p.get("companySources", [])} for p in chosen], "notes": []}


def audit(claims: list[dict[str, Any]]) -> dict[str, Any]:
    verdicts = []
    for claim in claims:
        extra = numbers(claim["claim"]) - numbers("\n".join(claim.get("sources") or []))
        if extra:
            shown = ", ".join(f"{n:g}" for n in sorted(extra))
            verdicts.append({"claimId": claim["id"], "verdict": "embellished",
                             "reason": f"States {shown}, which the sources don't mention."})
        else:
            verdicts.append({"claimId": claim["id"], "verdict": "supported", "reason": ""})
    return {"verdicts": verdicts}


def condense(items: list[dict[str, str]]) -> dict[str, Any]:
    """Drop each text's last sentence (or, for one sentence, its last clause): shorter, nothing added."""
    out = []
    for item in items:
        sentences = re.split(r"(?<=[.!?])\s+", item["text"].strip())
        text = " ".join(sentences[:-1]) if len(sentences) > 1 else _shorten(item["text"])
        out.append({"targetId": item["id"], "text": text})
    return {"items": out}
