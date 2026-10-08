"""Merging an imported résumé into an existing master (IMP-6).

The plan compares the reviewed import with the master's current version, section by section: an imported item
is new, the same as one already there, or a match with bullets the master doesn't have yet. Matching is fuzzy
(the same employer and start date or role, the same project or certificate name), and so is the check for
duplicate bullets, so a reworded copy of a bullet already in the master isn't offered again. The user picks what
to add; nothing already in the master is changed or removed.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

from rapidfuzz import fuzz

SAME = 90  # names and titles
SIMILAR = 85  # roles and fields of study
BULLET_SAME = 88  # a bullet reworded slightly is still the same bullet
BULLET_SIMILAR = 65  # about the same thing: offered, but pointed out (and not picked by default)

# Sections of items with ids, in master order
ITEM_SECTIONS = ("work", "projects", "education", "certifications", "awards", "publications", "volunteer",
                 "languages", "customSections")
TEXT_SECTIONS = ("headlines", "summaries")


def _norm(value: Any) -> str:
    return " ".join(str(value or "").casefold().split())


def _same(a: Any, b: Any, threshold: int = SAME) -> bool:
    a, b = _norm(a), _norm(b)
    return bool(a) and bool(b) and fuzz.token_sort_ratio(a, b) >= threshold


def _matches(section: str, new: dict[str, Any], old: dict[str, Any]) -> bool:
    if section == "work":
        same_start = bool(new.get("startDate")) and str(new.get("startDate"))[:7] == str(old.get("startDate"))[:7]
        return _same(new.get("company"), old.get("company")) and (
            same_start or _same(new.get("position"), old.get("position"), SIMILAR))
    if section == "volunteer":
        return _same(new.get("organization"), old.get("organization")) and _same(
            new.get("position"), old.get("position"), SIMILAR)
    if section == "education":
        return _same(new.get("institution"), old.get("institution")) and (
            not new.get("area") or not old.get("area") or _same(new.get("area"), old.get("area"), SIMILAR))
    if section == "languages":
        return _norm(new.get("language")) == _norm(old.get("language"))
    field_name = {"projects": "name", "certifications": "name", "awards": "title", "publications": "name",
                  "customSections": "title"}[section]
    return _same(new.get(field_name), old.get(field_name))


def _bullet_texts(item: dict[str, Any]) -> list[str]:
    texts = []
    for bullet in item.get("highlights") or []:
        if isinstance(bullet, dict):
            texts.append(bullet.get("text", ""))
            texts += [v.get("text", "") for v in bullet.get("variants") or [] if isinstance(v, dict)]
        else:
            texts.append(str(bullet))
    return texts


def _main_texts(item: dict[str, Any]) -> list[str]:
    return [b.get("text", "") if isinstance(b, dict) else str(b) for b in item.get("highlights") or []]


def _closest(text: str, known: list[str]) -> tuple[str | None, float]:
    t = _norm(text)
    best, score = None, 0.0
    for k in known:
        s = fuzz.token_set_ratio(t, _norm(k)) * 0.5 + fuzz.token_sort_ratio(t, _norm(k)) * 0.5
        if s > score:
            best, score = k, s
    return best, score


def _is_known(text: str, known: list[str]) -> bool:
    return _closest(text, known)[1] >= BULLET_SAME


def label_of(section: str, item: dict[str, Any]) -> tuple[str, str]:
    """A title and a detail line, for the review list."""
    if section in ("work", "volunteer"):
        return (item.get("position") or "", item.get("company") or item.get("organization") or "")
    if section == "education":
        return (" ".join(p for p in (item.get("studyType"), item.get("area")) if p) or item.get("institution", ""),
                item.get("institution") or "")
    if section == "languages":
        return item.get("language") or "", item.get("fluency") or ""
    if section == "skills":
        return item.get("name") or "", item.get("category") or ""
    return (item.get("name") or item.get("title") or "", item.get("issuer") or item.get("awarder")
            or item.get("publisher") or "")


@dataclass
class PlanItem:
    key: str  # section:index in the import
    section: str
    title: str
    detail: str
    status: str  # new · match (with new bullets) · same (nothing to add)
    match_id: str | None = None
    bullets: list[str] = field(default_factory=list)  # new: all of them; match: only those the master lacks
    similar_to: list[str | None] = field(default_factory=list)  # per bullet: a master bullet it resembles


def plan(imported: dict[str, Any], master: dict[str, Any]) -> list[PlanItem]:
    items: list[PlanItem] = []
    for section in ITEM_SECTIONS:
        existing = [i for i in master.get(section) or [] if isinstance(i, dict)]
        for n, item in enumerate(imported.get(section) or []):
            if not isinstance(item, dict):
                continue
            title, detail = label_of(section, item)
            match = next((old for old in existing if _matches(section, item, old)), None)
            if match is None:
                items.append(PlanItem(f"{section}:{n}", section, title, detail, "new", None, _main_texts(item)))
                continue
            known = _bullet_texts(match)  # its bullets and their variants
            fresh, similar = [], []
            for text in _main_texts(item):
                closest, score = _closest(text, known)
                if text and score < BULLET_SAME:
                    fresh.append(text)
                    similar.append(closest if score >= BULLET_SIMILAR else None)
            if section == "customSections":  # its items are entries, compared by title
                titles = [i.get("title") for i in match.get("items") or []]
                fresh = [i.get("title", "") for i in item.get("items") or [] if not any(_same(i.get("title"), t)
                                                                                        for t in titles)]
                similar = [None] * len(fresh)
            items.append(PlanItem(f"{section}:{n}", section, title, detail, "match" if fresh else "same",
                                  match.get("id"), fresh, similar))
    known_skills = {_norm(s.get("name")) for s in master.get("skills") or [] if isinstance(s, dict)} | {
        _norm(a) for s in master.get("skills") or [] if isinstance(s, dict) for a in s.get("aliases") or []}
    for n, skill in enumerate(imported.get("skills") or []):
        if isinstance(skill, dict) and skill.get("name"):
            title, detail = label_of("skills", skill)
            status = "same" if _norm(skill["name"]) in known_skills else "new"
            items.append(PlanItem(f"skills:{n}", "skills", title, detail, status))
    for section in TEXT_SECTIONS:
        known = [i.get("text", "") for i in master.get(section) or [] if isinstance(i, dict)]
        for n, block in enumerate(imported.get(section) or []):
            if isinstance(block, dict) and block.get("text"):
                status = "same" if _is_known(block["text"], known) else "new"
                items.append(PlanItem(f"{section}:{n}", section, block["text"][:120], "", status))
    return items


def _without_ids(value: Any) -> Any:
    """A copy with every id removed, so the master assigns its own (an imported id could clash)."""
    if isinstance(value, dict):
        return {k: _without_ids(v) for k, v in value.items() if k != "id"}
    if isinstance(value, list):
        return [_without_ids(v) for v in value]
    return value


def apply(imported: dict[str, Any], master: dict[str, Any], selections: dict[str, list[int] | None]) -> dict[str, Any]:
    """The master with what was picked: whole new items (``None``), or bullets by their index in the plan item's
    ``bullets``. Unknown keys and indexes are ignored; nothing already in the master changes."""
    merged = copy.deepcopy(master)
    by_key = {p.key: p for p in plan(imported, master)}
    for key, picked in selections.items():
        item = by_key.get(key)
        if item is None or item.status == "same":
            continue
        section, index = item.key.split(":")
        source = (imported.get(section) or [])[int(index)]
        if item.status == "new":
            merged.setdefault(section, []).append(_without_ids(source))
            continue
        target = next(i for i in merged.get(section) or [] if isinstance(i, dict) and i.get("id") == item.match_id)
        indexes = range(len(item.bullets)) if picked is None else picked
        chosen = [item.bullets[i] for i in indexes if 0 <= i < len(item.bullets)]
        if section == "customSections":
            entries = [e for e in source.get("items") or [] if e.get("title", "") in chosen]
            target.setdefault("items", []).extend(_without_ids(entries))
        else:
            originals = {b.get("text"): b for b in source.get("highlights") or [] if isinstance(b, dict)}
            target.setdefault("highlights", []).extend(_without_ids(originals.get(t, {"text": t})) for t in chosen)
    return merged
