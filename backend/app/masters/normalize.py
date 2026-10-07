"""Validate and normalize master résumés.

Normalization assigns missing IDs (``work-2``, ``work-2.b3``, ``kubernetes``), turns string bullets into
objects, normalizes dates, resolves skill references given by name or alias to skill IDs, and fills in
``meta``. Errors and warnings carry JSON paths such as ``work[2].startDate`` so the UI can point at them.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterator
from dataclasses import asdict, dataclass, field
from typing import Any

from pydantic import BaseModel, ValidationError

from app.models.master import (
    OBJECT_TAG,
    SCHEMA_VERSION,
    TEXT_TAG,
    CustomSection,
    Highlight,
    MasterResume,
    Meta,
    Project,
    Work,
)

MAX_DOCUMENT_BYTES = 1_048_576

# section attribute -> prefix for generated ids
_SECTION_PREFIX = {
    "headlines": "headline",
    "summaries": "summary",
    "work": "work",
    "projects": "project",
    "education": "education",
    "certifications": "cert",
    "awards": "award",
    "publications": "publication",
    "volunteer": "volunteer",
    "languages": "language",
    "interests": "interest",
    "references": "reference",
    "custom_sections": "section",
}
_WITH_HIGHLIGHTS = ("work", "projects", "education", "volunteer")


@dataclass
class Issue:
    path: str
    message: str


@dataclass
class NormalizeResult:
    document: dict[str, Any] | None = None
    errors: list[Issue] = field(default_factory=list)
    warnings: list[Issue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.document is not None and not self.errors

    def issues_as_dicts(self) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
        return [asdict(i) for i in self.errors], [asdict(i) for i in self.warnings]


# ---- helpers -------------------------------------------------------------------------------------


def _json_name(model: BaseModel, attr: str) -> str:
    info = type(model).model_fields[attr]
    return info.serialization_alias or info.alias or attr


def _join(path: str, key: str | int) -> str:
    if isinstance(key, int):
        return f"{path}[{key}]"
    return f"{path}.{key}" if path else key


def format_loc(loc: tuple[Any, ...]) -> str:
    path = ""
    for part in loc:
        if part in (TEXT_TAG, OBJECT_TAG):
            continue
        path = _join(path, part)
    return path or "(document)"


def _friendly(error: dict[str, Any]) -> str:
    kind, msg = error.get("type", ""), str(error.get("msg", "invalid value"))
    loc = error.get("loc", ())
    if kind == "missing":
        return "required"
    if loc and loc[-1] == OBJECT_TAG and kind == "model_type":
        return 'expected a string, or an object with a "text" field'
    if msg.startswith("Value error, "):
        msg = msg[len("Value error, "):]
    return msg


def slugify(name: str) -> str:
    text = name.lower().replace("++", "pp").replace("+", "plus").replace("#", "sharp").replace(".", "dot")
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return (text or "skill")[:60]


def canonical_json(document: dict[str, Any]) -> str:
    return json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def content_sha256(document: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(document).encode("utf-8")).hexdigest()


# ---- traversal ---------------------------------------------------------------------------------------


def _iter_items(master: MasterResume) -> Iterator[tuple[str, Any]]:
    """Yield (path, item) for every ID-bearing item in document order, children after parents."""
    for attr in [*_SECTION_PREFIX, "skills"]:
        json_attr = _json_name(master, attr)
        for i, item in enumerate(getattr(master, attr)):
            path = f"{json_attr}[{i}]"
            yield path, item
            if attr in _WITH_HIGHLIGHTS:
                for j, h in enumerate(item.highlights):
                    if isinstance(h, Highlight):
                        yield f"{path}.highlights[{j}]", h
            if isinstance(item, CustomSection):
                for j, ci in enumerate(item.items):
                    yield f"{path}.items[{j}]", ci
                    for k, h in enumerate(ci.highlights):
                        if isinstance(h, Highlight):
                            yield f"{path}.items[{j}].highlights[{k}]", h


def _walk_extras(model: BaseModel, path: str, out: list[Issue]) -> None:
    for key in (model.model_extra or {}):
        out.append(Issue(_join(path, key), f'unknown field "{key}" (kept as-is)'))
    for attr in type(model).model_fields:
        value = getattr(model, attr)
        name = _json_name(model, attr)
        if isinstance(value, BaseModel):
            _walk_extras(value, _join(path, name), out)
        elif isinstance(value, list):
            for i, entry in enumerate(value):
                if isinstance(entry, BaseModel):
                    _walk_extras(entry, f"{_join(path, name)}[{i}]", out)


def _date_bounds(value: str, *, end: bool) -> tuple[int, int, int]:
    parts = [int(p) for p in value.split("-")]
    year = parts[0]
    month = parts[1] if len(parts) > 1 else (12 if end else 1)
    day = parts[2] if len(parts) > 2 else (31 if end else 1)
    return year, month, day


# ---- main entry points -----------------------------------------------------------------------------


def parse_json(raw: bytes | str) -> tuple[Any, Issue | None]:
    try:
        return json.loads(raw), None
    except UnicodeDecodeError:
        return None, Issue("(document)", "the file is not UTF-8 text")
    except json.JSONDecodeError as exc:
        return None, Issue("(document)", f"invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}")


def normalize(data: Any) -> NormalizeResult:
    result = NormalizeResult()
    if not isinstance(data, dict):
        result.errors.append(Issue("(document)", "expected a JSON object at the top level"))
        return result
    try:
        master = MasterResume.model_validate(data)
    except ValidationError as exc:
        result.errors = [Issue(format_loc(tuple(e["loc"])), _friendly(e)) for e in exc.errors(include_url=False)]
        return result

    _walk_extras(master, "", result.warnings)
    _convert_string_highlights(master)
    _check_duplicate_ids(master, result.errors)
    if result.errors:
        return result
    _assign_ids(master)
    _resolve_skill_refs(master, result.errors)
    _check_dates(master, result.errors, result.warnings)
    _check_structure(master, result.errors, result.warnings)
    if result.errors:
        return result

    if master.meta is None:
        master.meta = Meta()
    master.meta.schema_version = SCHEMA_VERSION
    if not master.meta.label:
        master.meta.label = "Master résumé"
    result.document = master.model_dump(mode="json", by_alias=True, exclude_unset=True)
    return result


def normalize_raw(raw: bytes | str) -> NormalizeResult:
    data, issue = parse_json(raw)
    if issue:
        return NormalizeResult(errors=[issue])
    return normalize(data)


# ---- steps ----------------------------------------------------------------------------------------


def _convert_string_highlights(master: MasterResume) -> None:
    holders: list[Any] = []
    for attr in _WITH_HIGHLIGHTS:
        holders.extend(getattr(master, attr))
    for section in master.custom_sections:
        holders.extend(section.items)
    for holder in holders:
        for j, h in enumerate(holder.highlights):
            if isinstance(h, str):
                holder.highlights[j] = Highlight(text=h)


def _check_duplicate_ids(master: MasterResume, errors: list[Issue]) -> None:
    seen: dict[str, str] = {}
    for path, item in _iter_items(master):
        if item.id is None:
            continue
        if item.id in seen:
            errors.append(Issue(f"{path}.id", f'duplicate id "{item.id}" (also used at {seen[item.id]})'))
        else:
            seen[item.id] = path


def _assign_ids(master: MasterResume) -> None:
    used = {item.id for _, item in _iter_items(master) if item.id}

    def unique(candidate: str) -> str:
        value, n = candidate, 2
        while value in used:
            value, n = f"{candidate}-{n}", n + 1
        used.add(value)
        return value

    for skill in master.skills:
        if skill.id is None:
            skill.id = unique(slugify(skill.name))
    for attr, prefix in _SECTION_PREFIX.items():
        for i, item in enumerate(getattr(master, attr)):
            if item.id is None:
                item.id = unique(f"{prefix}-{i + 1}")
            if attr in _WITH_HIGHLIGHTS:
                _assign_child_ids(item.id, item.highlights, "b", unique)
            if isinstance(item, CustomSection):
                for j, ci in enumerate(item.items):
                    if ci.id is None:
                        ci.id = unique(f"{item.id}.i{j + 1}")
                    _assign_child_ids(ci.id, ci.highlights, "b", unique)


def _assign_child_ids(parent_id: str, children: list[Any], letter: str, unique: Any) -> None:
    for j, child in enumerate(children):
        if isinstance(child, Highlight) and child.id is None:
            child.id = unique(f"{parent_id}.{letter}{j + 1}")


def _resolve_skill_refs(master: MasterResume, errors: list[Issue]) -> None:
    """Skill references may use a skill's id, name or alias (case-insensitive); store the id."""
    ids = {s.id: s.id for s in master.skills if s.id}
    ids_ci = {s.id.lower(): s.id for s in master.skills if s.id}
    by_name: dict[str, set[str]] = {}
    for skill in master.skills:
        for key in [skill.name, *skill.aliases]:
            by_name.setdefault(key.lower(), set()).add(skill.id)  # type: ignore[arg-type]

    def resolve(refs: list[str], path: str) -> None:
        for k, ref in enumerate(refs):
            if ref in ids:
                continue
            matches = by_name.get(ref.lower(), set())
            if len(matches) == 1:
                refs[k] = next(iter(matches))
            elif len(matches) > 1:
                errors.append(Issue(f"{path}.skills[{k}]", f'"{ref}" matches more than one skill; use its id'))
            elif ref.lower() in ids_ci:
                refs[k] = ids_ci[ref.lower()]
            else:
                errors.append(Issue(f"{path}.skills[{k}]",
                                    f'unknown skill "{ref}" (add it to skills, or use an existing skill id)'))

    for path, item in _iter_items(master):
        if isinstance(item, (Work, Project, Highlight)):
            resolve(item.skills, path)


def _check_dates(master: MasterResume, errors: list[Issue], warnings: list[Issue]) -> None:
    for path, item in _iter_items(master):
        start = getattr(item, "start_date", None)
        end = getattr(item, "end_date", None)
        if start and end and _date_bounds(start, end=False) > _date_bounds(end, end=True):
            errors.append(Issue(f"{path}.endDate", f"ends ({end}) before it starts ({start})"))
    for i, work in enumerate(master.work):
        if work.start_date is None:
            warnings.append(Issue(f"work[{i}].startDate", "no start date, so no dates will be shown for this role"))


def _check_structure(master: MasterResume, errors: list[Issue], warnings: list[Issue]) -> None:
    if not master.work and not master.projects:
        errors.append(Issue("work", "add at least one work or projects entry"))
    for path, item in _iter_items(master):
        if getattr(item, "pin", False) and getattr(item, "hidden", False):
            warnings.append(Issue(path, "both pin and hidden are set; hidden wins"))
    names: dict[str, int] = {}
    for i, skill in enumerate(master.skills):
        lowered = skill.name.lower()
        if lowered in names:
            warnings.append(Issue(f"skills[{i}].name", f'"{skill.name}" is listed more than once'))
        names.setdefault(lowered, i)


# ---- summaries and diffs ----------------------------------------------------------------------------


def summarize(document: dict[str, Any]) -> dict[str, Any]:
    def count(key: str) -> int:
        value = document.get(key)
        return len(value) if isinstance(value, list) else 0

    bullets = 0
    for key in _WITH_HIGHLIGHTS:
        for entry in document.get(key, []) or []:
            bullets += len(entry.get("highlights", []) or [])
    return {
        "name": (document.get("basics") or {}).get("name"),
        "label": (document.get("meta") or {}).get("label"),
        "counts": {
            "headlines": count("headlines"),
            "summaries": count("summaries"),
            "work": count("work"),
            "projects": count("projects"),
            "bullets": bullets,
            "skills": count("skills"),
            "education": count("education"),
            "certifications": count("certifications"),
            "customSections": count("customSections"),
        },
    }


def _flatten(node: Any, out: dict[str, str]) -> Any:
    """Map id -> canonical JSON of each item, with child items replaced by their ids."""
    if isinstance(node, dict):
        reduced = {k: _flatten(v, out) for k, v in node.items()}
        if isinstance(node.get("id"), str):
            out[node["id"]] = canonical_json(reduced)
            return {"$ref": node["id"]}
        return reduced
    if isinstance(node, list):
        return [_flatten(v, out) for v in node]
    return node


def diff_documents(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    old_items: dict[str, str] = {}
    new_items: dict[str, str] = {}
    old_root = _flatten(old, old_items)
    new_root = _flatten(new, new_items)
    added = [k for k in new_items if k not in old_items]
    removed = [k for k in old_items if k not in new_items]
    changed = [k for k in new_items if k in old_items and new_items[k] != old_items[k]]
    return {
        "added": added,
        "removed": removed,
        "changed": changed,
        "basicsChanged": old_root.get("basics") != new_root.get("basics"),
        "preferencesChanged": old_root.get("preferences") != new_root.get("preferences"),
    }
