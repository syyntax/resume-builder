"""Cover letters (DESIGN.md §4.8, §7.4): build the letter from stage C's draft, and check it.

The model writes only the paragraphs and subject. The server fills in the sender (from the master), the
date, the recipient (from the options), and a salutation that never guesses an honorific (CVL-7). Each
paragraph is checked like a résumé bullet (G3 numbers, G4 terms), and statements about the company must
come from the posting or the candidate's notes (G6); without notes, the motivation paragraph is flagged
for the candidate to personalize.
"""

from __future__ import annotations

import copy
import re
from datetime import date
from typing import Any

from app.ai.schemas import JobAnalysis, LetterDraft
from app.errors import ApiError
from app.pipeline.editing import ITEM_ID, audit_warning
from app.pipeline.hydrate import MasterIndex
from app.pipeline.validators import build_term_groups, check_text, source_text

ROLES = ("opening", "evidence", "motivation", "closing")
SENDER_FIELDS = ("name", "label", "email", "phone", "url", "location", "profiles")
MAX_PARAGRAPH = 3000


def salutation(recipient: dict[str, Any]) -> str:
    name = (recipient.get("name") or "").strip()
    return f"Dear {name}," if name else "Dear Hiring Team,"


def sender_of(master: dict[str, Any], resume: dict[str, Any] | None) -> dict[str, Any]:
    basics = master.get("basics") or {}
    sender = {k: basics[k] for k in SENDER_FIELDS if k in basics}
    headline = ((resume or {}).get("headline") or {}).get("text")
    if headline:
        sender["label"] = headline
    return sender


def _valid_ids(index: MasterIndex, ids: list[Any]) -> list[str]:
    return [i for i in ids if isinstance(i, str) and i in index.all_ids and i not in index.hidden]


def build_letter(draft: LetterDraft, *, master: dict[str, Any], resume: dict[str, Any] | None,
                 analysis: JobAnalysis, options: dict[str, Any], job_company: str | None, meta: dict[str, Any],
                 today: date | None = None) -> dict[str, Any]:
    index = MasterIndex.build(master)
    requirement_ids = {r.id for r in analysis.requirements}
    recipient = dict(options.get("recipient") or {})
    recipient["company"] = recipient.get("company") or job_company or ""
    paragraphs = []
    for n, p in enumerate(draft.paragraphs, start=1):
        text = p.text.strip()
        if not text:
            continue
        paragraphs.append({"id": f"p{n}", "role": p.role, "text": text, "sourceIds": _valid_ids(index, p.source_ids),
                           "jobRefs": [r for r in p.job_refs if r in requirement_ids],
                           "companySources": list(dict.fromkeys(p.company_sources)), "aiText": text,
                           "edited": False, "flags": [], "warnings": []})
    return {
        "meta": meta,
        "options": options,
        "sender": sender_of(master, resume),
        "date": (today or date.today()).isoformat(),
        "recipient": {k: v for k, v in recipient.items() if v},
        "subject": draft.subject.strip(),
        "salutation": salutation(recipient),
        "paragraphs": paragraphs,
        "highlights": [{"value": h.value, "label": h.label, "sourceIds": _valid_ids(index, h.source_ids)}
                       for h in draft.highlights],
        "closing": "Sincerely,",
        "signature": (master.get("basics") or {}).get("name", ""),
        "analysis": {"notes": [n.model_dump(by_alias=True) for n in draft.notes]},
    }


def annotate_letter(letter: dict[str, Any], master: dict[str, Any], analysis: JobAnalysis,
                    posting: str) -> dict[str, Any]:
    """Warnings and flags for every paragraph, and the word count, recomputed in place."""
    index = MasterIndex.build(master)
    groups = build_term_groups(master, analysis)
    notes = ((letter.get("options") or {}).get("notes") or "").strip()
    report = letter.setdefault("analysis", {})
    audit = (report.get("audit") or {}).get("results") or {}
    warnings: list[dict[str, str]] = []
    for p in letter.get("paragraphs") or []:
        companies = p.get("companySources") or []
        source = source_text(index, None, p.get("sourceIds") or [])
        if "posting" in companies:
            source += "\n" + posting
        if "notes" in companies and notes:
            source += "\n" + notes
        found = check_text(p["text"], source, groups)
        flags: list[str] = []
        if p["role"] == "motivation":
            if not notes:
                flags.append("PERSONALIZE")
            if not companies:
                found.append({"code": "COMPANY_UNSOURCED", "message": "Says why this company without drawing on "
                                                                      "the posting or your notes."})
            elif "notes" in companies and not notes:
                found.append({"code": "NOTES_MISSING", "message": "Cites your notes, but you haven't added any."})
        if not p.get("sourceIds") and p["role"] in ("opening", "evidence"):
            found.append({"code": "NO_SOURCE", "message": "Doesn't cite anything from your master résumé."})
        if result := audit_warning(audit.get(f"letter:{p['id']}"), p["text"]):
            found.append(result)
        p["warnings"], p["flags"] = found, flags
        warnings += [{"targetId": p["id"], **w} for w in found]
    report["warnings"] = warnings
    report["wordCount"] = sum(len(p["text"].split()) for p in letter.get("paragraphs") or [])
    return letter


def normalize_letter(edited: dict[str, Any], stored: dict[str, Any], master: dict[str, Any],
                     analysis: JobAnalysis, posting: str) -> dict[str, Any]:
    """The edited letter: recipient, subject, salutation and paragraphs from the editor; the sender always
    from the master; everything re-checked."""
    stored = copy.deepcopy(stored)  # never modify the loaded JSON in place (SQLAlchemy wouldn't see the change)
    index = MasterIndex.build(master)
    requirement_ids = {r.id for r in analysis.requirements}
    errors: list[dict[str, str]] = []

    def text(value: Any, limit: int, path: str, *, required: bool = False) -> str:
        out = value.strip() if isinstance(value, str) else ""
        if required and not out:
            errors.append({"path": path, "message": "can't be empty"})
        elif len(out) > limit:
            errors.append({"path": path, "message": f"is longer than {limit} characters"})
        return out

    raw_recipient = edited.get("recipient") if isinstance(edited.get("recipient"), dict) else {}
    recipient = {k: text(raw_recipient.get(k), 200, f"recipient.{k}") for k in ("name", "title", "company")}
    address = [text(a, 200, "recipient.address") for a in (raw_recipient.get("address") or [])[:5]]
    recipient = {k: v for k, v in recipient.items() if v} | ({"address": [a for a in address if a]} if any(address)
                                                            else {})
    seen: set[str] = set()
    stored_paragraphs = {p["id"]: p for p in stored.get("paragraphs") or []}
    paragraphs = []
    for i, raw in enumerate(edited.get("paragraphs") or []):
        path = f"paragraphs[{i}]"
        pid = raw.get("id") if isinstance(raw, dict) else None
        if not isinstance(pid, str) or not ITEM_ID.match(pid) or pid in seen:
            errors.append({"path": f"{path}.id", "message": "needs a unique id"})
            continue
        seen.add(pid)
        role = raw.get("role") if raw.get("role") in ROLES else "evidence"
        body = text(raw.get("text"), MAX_PARAGRAPH, f"{path}.text", required=True)
        ai_text = (stored_paragraphs.get(pid) or {}).get("aiText") or (raw.get("aiText") if isinstance(
            raw.get("aiText"), str) else None)
        paragraphs.append({
            "id": pid, "role": role, "text": body, "sourceIds": _valid_ids(index, raw.get("sourceIds") or []),
            "jobRefs": [r for r in raw.get("jobRefs") or [] if r in requirement_ids],
            "companySources": [c for c in dict.fromkeys(raw.get("companySources") or []) if c in ("posting", "notes")],
            "aiText": ai_text, "edited": body != ai_text, "flags": [], "warnings": [],
        })
    if not paragraphs:
        errors.append({"path": "paragraphs", "message": "a letter needs at least one paragraph"})
    subject = text(edited.get("subject"), 200, "subject")
    greeting = text(edited.get("salutation"), 200, "salutation") or salutation(recipient)
    closing = text(edited.get("closing"), 100, "closing") or "Sincerely,"
    if errors:
        raise ApiError(422, "Some edits couldn't be saved.", errors=errors[:50])
    letter = {**stored, "recipient": recipient, "subject": subject, "salutation": greeting, "paragraphs": paragraphs,
              "closing": closing, "sender": stored.get("sender") or sender_of(master, None),
              "signature": (master.get("basics") or {}).get("name", "")}
    return annotate_letter(letter, master, analysis, posting)


def to_markdown(letter: dict[str, Any]) -> str:
    sender = letter.get("sender") or {}
    lines = [f"**{sender.get('name', '')}**"]
    contact = [sender.get("email"), sender.get("phone")]
    lines += [" · ".join(c for c in contact if c), "", letter.get("date", ""), ""]
    recipient = letter.get("recipient") or {}
    lines += [v for v in (recipient.get("name"), recipient.get("title"), recipient.get("company"),
                          *(recipient.get("address") or [])) if v]
    if letter.get("subject"):
        lines += ["", f"**Re: {letter['subject']}**"]
    lines += ["", letter.get("salutation", "")]
    for p in letter.get("paragraphs") or []:
        lines += ["", re.sub(r"\s+", " ", p["text"]).strip()]
    lines += ["", letter.get("closing", "Sincerely,"), "", letter.get("signature", "")]
    return "\n".join(lines).strip() + "\n"
