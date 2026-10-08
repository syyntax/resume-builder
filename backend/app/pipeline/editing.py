"""Edited documents (DESIGN.md §4.9): what the editor saves is checked and annotated again on the server.

- G1: facts (employers, titles, dates, degrees, contact details) are always copied from the master version;
  the editor can choose and order items, not change their facts.
- G2: every source id must be a visible item or bullet of the master version, and a bullet may cite only
  bullets of its own role or project. Lines with no source are kept, with a warning.
- G3/G4 and coverage are recomputed, and claim-audit verdicts stay attached only while the text they
  judged is unchanged.
"""

from __future__ import annotations

import copy
import re
from typing import Any

from app.ai.schemas import JobAnalysis
from app.errors import ApiError
from app.pipeline.hydrate import FACT_FIELDS, SECTION_TITLES, MasterIndex
from app.pipeline.validators import coverage, validate

ITEM_ID = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
SECTION_SOURCE = {
    "experience": "work", "earlier-experience": "work", "projects": "projects", "education": "education",
    "certifications": "certifications", "awards": "awards", "publications": "publications",
    "volunteer": "volunteer", "languages": "languages",
}
WITH_BULLETS = {"experience", "projects"}
MAX_TEXT = {"headline": 300, "summary": 2000, "bullet": 1000}
CUSTOM_FIELDS = ("title", "subtitle", "date", "startDate", "endDate", "url", "summary")


def audit_warning(result: dict[str, Any] | None, text: str) -> dict[str, str] | None:
    """The claim audit's verdict as a warning, while the text it judged is unchanged."""
    if not result or result.get("text") != text or result.get("verdict") == "supported":
        return None
    label = "Overstates its sources" if result["verdict"] == "embellished" else "Not supported by its sources"
    return {"code": f"CLAIM_{result['verdict'].upper()}", "message": f"{label}: {result.get('reason', '')}".strip()}


def annotate_resume(resume: dict[str, Any], master: dict[str, Any], analysis: JobAnalysis) -> dict[str, Any]:
    """Warnings (G3/G4, length, missing sources, claim audit) and keyword coverage, recomputed in place."""
    warnings = validate(resume, master, analysis)
    report = resume.setdefault("analysis", {})
    audit = (report.get("audit") or {}).get("results") or {}
    for section in resume.get("sections") or []:
        for item in section.get("items") or []:
            for bullet in item.get("bullets") or []:
                extra = []
                if not bullet.get("sourceIds"):
                    extra.append({"code": "NO_SOURCE", "message": "Not backed by your master résumé: check it's "
                                                                  "accurate, or add it to your master."})
                if found := audit_warning(audit.get(bullet["id"]), bullet["text"]):
                    extra.append(found)
                bullet["warnings"] = [*bullet.get("warnings", []), *extra]
                warnings += [{"targetId": bullet["id"], **w} for w in extra]
    for key in ("headline", "summary"):
        block = resume.get(key) or {}
        if found := audit_warning(audit.get(key), block.get("text", "")):
            warnings.append({"targetId": key, **found})
    report["warnings"] = warnings
    report["coverage"] = coverage(resume, master, analysis)
    return resume


class EditError(ApiError):
    def __init__(self, errors: list[dict[str, str]]) -> None:
        super().__init__(422, "Some edits couldn't be saved.", errors=errors)


def _text(value: Any, limit: int, path: str, errors: list[dict[str, str]], *, required: bool = True) -> str:
    text = value.strip() if isinstance(value, str) else ""
    if required and not text:
        errors.append({"path": path, "message": "can't be empty"})
    elif len(text) > limit:
        errors.append({"path": path, "message": f"is longer than {limit} characters"})
    return text


def _bullet(raw: Any, item_id: str, index: MasterIndex, path: str, seen: set[str],
            errors: list[dict[str, str]]) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        errors.append({"path": path, "message": "isn't a bullet"})
        return None
    bullet_id = raw.get("id")
    if not isinstance(bullet_id, str) or not ITEM_ID.match(bullet_id) or bullet_id in seen:
        errors.append({"path": f"{path}.id", "message": "needs a unique id"})
        return None
    seen.add(bullet_id)
    text = _text(raw.get("text"), MAX_TEXT["bullet"], f"{path}.text", errors)
    own = index.bullets.get(item_id, {})
    sources = [s for s in raw.get("sourceIds") or [] if isinstance(s, str) and s in own and s not in index.hidden]
    origin = raw.get("origin") if raw.get("origin") in ("ai", "master", "user") else "user"
    if not sources:
        origin = "user"
    ai_text = raw.get("aiText") if isinstance(raw.get("aiText"), str) else None
    if origin == "master":
        edited = text != own[sources[0]].get("text")
    else:
        edited = text != ai_text if ai_text is not None else origin == "user"
    relevance = raw.get("relevance") if isinstance(raw.get("relevance"), int) and 1 <= raw["relevance"] <= 5 else 3
    keywords = [k for k in raw.get("keywords") or [] if isinstance(k, str)][:20]
    return {"id": bullet_id, "text": text, "sourceIds": sources, "relevance": relevance, "keywords": keywords,
            "origin": origin, "edited": edited, "aiText": ai_text, "warnings": []}


def normalize_resume(edited: dict[str, Any], stored: dict[str, Any], master: dict[str, Any],
                     analysis: JobAnalysis) -> dict[str, Any]:
    """The edited résumé, with facts and sources enforced (G1, G2) and annotations recomputed."""
    stored = copy.deepcopy(stored)  # never modify the loaded JSON in place (SQLAlchemy wouldn't see the change)
    index = MasterIndex.build(master)
    errors: list[dict[str, str]] = []
    seen: set[str] = set()
    sections: list[dict[str, Any]] = []
    raw_sections = edited.get("sections") if isinstance(edited.get("sections"), list) else []
    for i, raw in enumerate(raw_sections):
        path = f"sections[{i}]"
        kind = raw.get("type") if isinstance(raw, dict) else None
        title = _text(raw.get("title") if isinstance(raw, dict) else None, 60, f"{path}.title", errors,
                      required=False) or SECTION_TITLES.get(str(kind), "Section")
        if kind == "skills":
            groups = []
            for g, group in enumerate(raw.get("groups") or []):
                items = []
                for s in group.get("items") or []:
                    skill = index.usable("skills", s.get("skillId", ""))
                    if skill is None:
                        errors.append({"path": f"{path}.groups[{g}]", "message": f"unknown skill {s.get('skillId')!r}"})
                        continue
                    names = {skill["name"], *(skill.get("aliases") or [])}
                    display = s.get("display") if s.get("display") in names else skill["name"]  # G5
                    items.append({"skillId": skill["id"], "display": display})
                if items:
                    name = _text(group.get("name"), 60, f"{path}.groups[{g}].name", errors)
                    groups.append({"name": name, "items": items})
            if groups:
                sections.append({"type": "skills", "title": title, "groups": groups})
        elif kind == "custom":
            section = index.usable("customSections", raw.get("sourceId", ""))
            if section is None:
                errors.append({"path": path, "message": "isn't a custom section of your master résumé"})
                continue
            children = []
            for j, item in enumerate(raw.get("items") or []):
                child = index.usable(f"custom:{section['id']}", item.get("sourceId", ""))
                if child is None:
                    errors.append({"path": f"{path}.items[{j}]", "message": "isn't an item of that section"})
                    continue
                children.append({"sourceId": child["id"], **{k: child[k] for k in CUSTOM_FIELDS if k in child}})
            if children:
                sections.append({"type": "custom", "title": title, "sourceId": section["id"], "items": children})
        elif kind in SECTION_SOURCE:
            source_section = SECTION_SOURCE[kind]
            items = []
            for j, item in enumerate(raw.get("items") or []):
                item_path = f"{path}.items[{j}]"
                master_item = index.usable(source_section, item.get("sourceId", "") if isinstance(item, dict) else "")
                if master_item is None:
                    errors.append({"path": item_path, "message": "isn't a visible item of your master résumé"})
                    continue
                facts = {"sourceId": master_item["id"],
                         **{k: master_item[k] for k in FACT_FIELDS[source_section] if k in master_item}}  # G1
                if kind in WITH_BULLETS:
                    bullets = [_bullet(b, master_item["id"], index, f"{item_path}.bullets[{k}]", seen, errors)
                               for k, b in enumerate(item.get("bullets") or [])]
                    facts["bullets"] = [b for b in bullets if b]
                items.append(facts)
            if items:
                sections.append({"type": kind, "title": title, "items": items})
        else:
            errors.append({"path": path, "message": f"unknown section type {kind!r}"})

    blocks = {}
    for key in ("headline", "summary"):
        raw = edited.get(key) if isinstance(edited.get(key), dict) else {}
        text = _text(raw.get("text"), MAX_TEXT[key], f"{key}.text", errors, required=False)
        sources = [s for s in raw.get("sourceIds") or [] if s in index.all_ids and s not in index.hidden]
        stored_block = stored.get(key) or {}
        blocks[key] = {"text": text, "sourceIds": sources, "edited": text != stored_block.get("aiText",
                                                                                              stored_block.get("text")),
                       **({"aiText": stored_block["aiText"]} if "aiText" in stored_block else {})}
    if errors:
        raise EditError(errors[:50])

    resume = {**{k: v for k, v in stored.items() if k not in ("sections", "headline", "summary")},
              **blocks, "sections": sections}
    return annotate_resume(resume, master, analysis)
