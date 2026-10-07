"""Turn a stage I draft into a master résumé (DESIGN.md §10.3).

The draft uses empty strings for "absent" (see `app.ai.import_schema`); this drops them, reads dates
leniently, fills required fields that are missing with visible placeholders (each with a note), and
translates the model's note paths into paths in the converted document. `finalize()` then normalizes the
document (assigning IDs) and attaches each note to the item it's about.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.ai.import_schema import MasterImportDraft
from app.importers.sniff import ImportRejected
from app.masters.normalize import NormalizeResult, normalize

SHORT, TEXT, URL, TAG = 300, 5000, 2048, 60
_MONTHS = {name: i for i, names in enumerate(
    [("jan", "january"), ("feb", "february"), ("mar", "march"), ("apr", "april"), ("may",), ("jun", "june"),
     ("jul", "july"), ("aug", "august"), ("sep", "sept", "september"), ("oct", "october"), ("nov", "november"),
     ("dec", "december")], start=1) for name in names}
_PRESENT = {"present", "current", "now", "ongoing", "today"}
_ISO = re.compile(r"^(\d{4})(?:-(\d{1,2})(?:-(\d{1,2}))?)?$")
_NUMERIC = re.compile(r"^(\d{1,2})\s*[/.-]\s*(\d{4})$")
_NAMED = re.compile(r"^([a-z]+)\.?,?\s+(\d{4})$")


@dataclass
class Note:
    path: str
    severity: str  # info | warning
    message: str
    source: str = "model"  # model | import


@dataclass
class Converted:
    document: dict[str, Any]
    notes: list[Note] = field(default_factory=list)
    inferred_skills: list[dict[str, str]] = field(default_factory=list)


def parse_date(text: str) -> str | None:
    """A date as YYYY, YYYY-MM or YYYY-MM-DD, or None when it can't be read. "Present" isn't a date."""
    value = text.strip().lower()
    if match := _ISO.match(value):
        year, month, day = match.groups()
        if month is None:
            return year
        if not 1 <= int(month) <= 12:
            return None
        return f"{year}-{int(month):02d}" + (f"-{int(day):02d}" if day else "")
    if (match := _NUMERIC.match(value)) and 1 <= int(match.group(1)) <= 12:
        return f"{match.group(2)}-{int(match.group(1)):02d}"
    if (match := _NAMED.match(value)) and match.group(1) in _MONTHS:
        return f"{match.group(2)}-{_MONTHS[match.group(1)]:02d}"
    return None


class _Builder:
    def __init__(self) -> None:
        self.notes: list[Note] = []

    def note(self, path: str, severity: str, message: str) -> None:
        self.notes.append(Note(path, severity, message, source="import"))

    def text(self, value: str, path: str, limit: int = SHORT) -> str | None:
        value = value.strip()
        if not value:
            return None
        if len(value) > limit:
            self.note(path, "warning", f"Shortened to {limit} characters; check the end of this text.")
            value = value[:limit].rstrip()
        return value

    def required(self, value: str, path: str, placeholder: str) -> str:
        text = self.text(value, path)
        if text is None:
            self.note(path, "warning", f'Missing in the document, so it says "{placeholder}". Fill it in.')
            return placeholder
        return text

    def strings(self, values: list[str], path: str, limit: int = SHORT, max_items: int = 100) -> list[str]:
        out: list[str] = []
        for i, value in enumerate(values):
            text = self.text(value, f"{path}[{i}]", limit)
            if text and text not in out:
                out.append(text)
        if len(out) > max_items:
            self.note(path, "warning", f"Only the first {max_items} entries were kept.")
        return out[:max_items]

    def tags(self, values: list[str], path: str) -> list[str]:
        return self.strings([v.lower() for v in values], path, limit=TAG, max_items=50)

    def date(self, value: str, path: str) -> str | None:
        if not value.strip() or value.strip().lower() in _PRESENT:
            return None
        parsed = parse_date(value)
        if parsed is None:
            self.note(path, "warning", f'Couldn\'t read the date "{value.strip()}". Enter it as YYYY-MM.')
        return parsed

    def dates(self, item: Any, path: str, out: dict[str, Any], *, current: bool | None) -> None:
        start = self.date(item.start_date, f"{path}.startDate")
        end = None if current else self.date(item.end_date, f"{path}.endDate")
        if start:
            out["startDate"] = start
        if end:
            out["endDate"] = end
        elif current is False and start and not item.end_date.strip():
            self.note(f"{path}.endDate", "warning", "No end date, so this shows as current. Add the end date if "
                                                   "it has ended.")


def _compact(item: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in item.items() if v not in (None, "", [], {})}


def convert(draft: MasterImportDraft, *, label: str) -> Converted:
    b = _Builder()
    index: dict[str, dict[int, int]] = {}  # draft section index -> document index (empty items are dropped)

    def keep(section: str, draft_index: int, items: list[dict[str, Any]], item: dict[str, Any]) -> None:
        index.setdefault(section, {})[draft_index] = len(items)
        items.append(item)

    basics_in = draft.basics
    location = _compact({"city": b.text(basics_in.location.city, "basics.location.city"),
                         "region": b.text(basics_in.location.region, "basics.location.region"),
                         "countryCode": b.text(basics_in.location.country_code, "basics.location.countryCode")})
    profiles = [_compact({"network": b.text(p.network, f"basics.profiles[{i}].network"),
                          "username": b.text(p.username, f"basics.profiles[{i}].username"),
                          "url": b.text(p.url, f"basics.profiles[{i}].url", URL)})
                for i, p in enumerate(basics_in.profiles)]
    basics = _compact({
        "name": b.required(basics_in.name, "basics.name", "Your name"),
        "label": b.text(basics_in.label, "basics.label"),
        "email": b.text(basics_in.email, "basics.email"),
        "phone": b.text(basics_in.phone, "basics.phone"),
        "url": b.text(basics_in.url, "basics.url", URL),
        "location": location,
        "profiles": [p for p in profiles if p],
    })
    doc: dict[str, Any] = {"meta": {"schemaVersion": "1.0", "label": label}, "basics": basics}
    if headline := b.text(draft.headline, "headlines[0].text"):
        doc["headlines"] = [{"text": headline}]
    if summary := b.text(draft.summary, "summaries[0].text", TEXT):
        doc["summaries"] = [{"text": summary}]

    work: list[dict[str, Any]] = []
    for i, w in enumerate(draft.work):
        path = f"work[{len(work)}]"
        if not any([w.company.strip(), w.position.strip(), w.highlights, w.summary.strip()]):
            continue
        item = {"company": b.required(w.company, f"{path}.company", "Unknown company"),
                "position": b.required(w.position, f"{path}.position", "Unknown position"),
                "location": b.text(w.location, f"{path}.location"),
                "summary": b.text(w.summary, f"{path}.summary", TEXT),
                "tags": b.tags(w.tags, f"{path}.tags"),
                "highlights": b.strings(w.highlights, f"{path}.highlights", TEXT)}
        b.dates(w, path, item, current=w.current)
        keep("work", i, work, _compact(item))

    projects: list[dict[str, Any]] = []
    for i, p in enumerate(draft.projects):
        path = f"projects[{len(projects)}]"
        if not any([p.name.strip(), p.description.strip(), p.highlights]):
            continue
        item = {"name": b.required(p.name, f"{path}.name", "Untitled project"),
                "description": b.text(p.description, f"{path}.description", TEXT),
                "url": b.text(p.url, f"{path}.url", URL), "tags": b.tags(p.tags, f"{path}.tags"),
                "highlights": b.strings(p.highlights, f"{path}.highlights", TEXT)}
        b.dates(p, path, item, current=None)
        keep("projects", i, projects, _compact(item))

    education: list[dict[str, Any]] = []
    for i, e in enumerate(draft.education):
        path = f"education[{len(education)}]"
        if not any([e.institution.strip(), e.area.strip(), e.study_type.strip()]):
            continue
        item = {"institution": b.required(e.institution, f"{path}.institution", "Unknown institution"),
                "studyType": b.text(e.study_type, f"{path}.studyType"), "area": b.text(e.area, f"{path}.area"),
                "score": b.text(e.score, f"{path}.score"), "courses": b.strings(e.courses, f"{path}.courses"),
                "honors": b.strings(e.honors, f"{path}.honors"),
                "highlights": b.strings(e.highlights, f"{path}.highlights", TEXT)}
        b.dates(e, path, item, current=None)
        keep("education", i, education, _compact(item))

    certifications: list[dict[str, Any]] = []
    for i, c in enumerate(draft.certifications):
        path = f"certifications[{len(certifications)}]"
        if not c.name.strip():
            continue
        keep("certifications", i, certifications, _compact({
            "name": b.text(c.name, f"{path}.name"), "issuer": b.text(c.issuer, f"{path}.issuer"),
            "date": b.date(c.date, f"{path}.date"), "expires": b.date(c.expires, f"{path}.expires"),
            "credentialId": b.text(c.credential_id, f"{path}.credentialId"),
            "url": b.text(c.url, f"{path}.url", URL)}))

    skills: list[dict[str, Any]] = []
    by_name: dict[str, dict[str, Any]] = {}
    for i, s in enumerate(draft.skills):
        name = s.name.strip()
        if not name:
            continue
        if name.casefold() in by_name:  # listed twice: merge aliases into the first
            first = by_name[name.casefold()]
            first["aliases"] = [*first.get("aliases", []), *(a for a in s.aliases if a not in first.get("aliases", []))]
            index.setdefault("skills", {})[i] = skills.index(first)
            continue
        path = f"skills[{len(skills)}]"
        item = _compact({"name": b.text(name, f"{path}.name"), "category": b.text(s.category, f"{path}.category"),
                         "level": b.text(s.level, f"{path}.level"),
                         "aliases": [a for a in b.strings(s.aliases, f"{path}.aliases")
                                     if a.casefold() != name.casefold()]})
        by_name[name.casefold()] = item
        keep("skills", i, skills, item)

    inferred = []
    for s in draft.inferred_skills:
        name = s.name.strip()
        if name and name.casefold() not in by_name and all(x["name"].casefold() != name.casefold() for x in inferred):
            inferred.append({"name": name[:SHORT], "category": s.category.strip()[:SHORT],
                             "evidence": s.evidence.strip()[:SHORT]})

    simple: list[tuple[str, list[Any], str, str, list[tuple[str, str, int | None]]]] = [
        ("awards", draft.awards, "title", "Untitled award",
         [("date", "date", None), ("awarder", "awarder", SHORT), ("summary", "summary", TEXT)]),
        ("publications", draft.publications, "name", "Untitled publication",
         [("publisher", "publisher", SHORT), ("release_date", "releaseDate", None), ("url", "url", URL),
          ("summary", "summary", TEXT)]),
        ("languages", draft.languages, "language", "", [("fluency", "fluency", SHORT)]),
    ]
    for section, entries, title_key, placeholder, fields in simple:
        items: list[dict[str, Any]] = []
        for i, entry in enumerate(entries):
            path = f"{section}[{len(items)}]"
            title = getattr(entry, title_key).strip()
            if not title and (not placeholder or not any(getattr(entry, attr).strip() for attr, _, _ in fields)):
                continue
            item: dict[str, Any] = {title_key: b.required(title, f"{path}.{title_key}", placeholder)}
            for attr, key, limit in fields:
                raw = getattr(entry, attr)
                item[key] = b.date(raw, f"{path}.{key}") if limit is None else b.text(raw, f"{path}.{key}", limit)
            keep(section, i, items, _compact(item))
        if items:
            doc[section] = items

    volunteer: list[dict[str, Any]] = []
    for i, v in enumerate(draft.volunteer):
        path = f"volunteer[{len(volunteer)}]"
        if not v.organization.strip() and not v.position.strip():
            continue
        item = {"organization": b.required(v.organization, f"{path}.organization", "Unknown organization"),
                "position": b.text(v.position, f"{path}.position"),
                "summary": b.text(v.summary, f"{path}.summary", TEXT),
                "highlights": b.strings(v.highlights, f"{path}.highlights", TEXT)}
        b.dates(v, path, item, current=None)
        keep("volunteer", i, volunteer, _compact(item))

    interests = []
    for i, it in enumerate(draft.interests):
        if it.name.strip():
            path = f"interests[{len(interests)}]"
            keep("interests", i, interests, _compact({"name": b.text(it.name, f"{path}.name"),
                                                       "keywords": b.strings(it.keywords, f"{path}.keywords")}))

    custom: list[dict[str, Any]] = []
    for i, section in enumerate(draft.custom_sections):
        path = f"customSections[{len(custom)}]"
        items = []
        for j, ci in enumerate(section.items):
            title = ci.title.strip() or ci.subtitle.strip() or ci.summary.strip()[:80]
            if not title:
                continue
            ipath = f"{path}.items[{len(items)}]"
            index.setdefault(f"customSections[{i}].items", {})[j] = len(items)
            item = {"title": b.text(title, f"{ipath}.title"),
                    "subtitle": b.text(ci.subtitle, f"{ipath}.subtitle") if ci.title.strip() else None,
                    "date": b.date(ci.date, f"{ipath}.date"), "summary": b.text(ci.summary, f"{ipath}.summary", TEXT),
                    "highlights": b.strings(ci.highlights, f"{ipath}.highlights", TEXT)}
            items.append(_compact(item))
        if items or section.title.strip():
            keep("customSections", i, custom, {"title": b.required(section.title, f"{path}.title", "Other"),
                                               "items": items})

    for key, value in (("work", work), ("projects", projects), ("education", education),
                       ("certifications", certifications), ("skills", skills), ("volunteer", volunteer),
                       ("interests", interests), ("customSections", custom)):
        if value:
            doc[key] = value

    notes = [Note(_translate(n.path, index), n.severity, n.message.strip()[:300]) for n in draft.import_notes
             if n.message.strip()]
    return Converted(document=doc, notes=notes + b.notes, inferred_skills=inferred)


_SEGMENT = re.compile(r"([A-Za-z_]\w*)|\[(\d+)\]")


def _segments(path: str) -> list[str | int]:
    return [m.group(1) if m.group(1) is not None else int(m.group(2)) for m in _SEGMENT.finditer(path)]


def _translate(path: str, index: dict[str, dict[int, int]]) -> str:
    """Map a path in the model's draft to the same place in the converted document."""
    path = path.strip()
    if path.startswith("headline"):
        return "headlines[0].text"
    if path.startswith("summary"):
        return "summaries[0].text"
    match = re.match(r"^(\w+)\[(\d+)\](.*)$", path)
    if not match:
        return path
    section, i, rest = match.group(1), int(match.group(2)), match.group(3)
    if section == "inferredSkills":
        return "skills"
    if section not in index or i not in index[section]:
        return section
    if section == "customSections" and (inner := re.match(r"^\.items\[(\d+)\](.*)$", rest)):
        items = index.get(f"customSections[{i}].items", {})
        j = int(inner.group(1))
        rest = f".items[{items[j]}]{inner.group(2)}" if j in items else ""
    rest = rest.replace(".current", ".endDate")
    return f"{section}[{index[section][i]}]{rest}"


# ---- normalize and locate ---------------------------------------------------------------------------


def _drop(doc: dict[str, Any], path: str) -> bool:
    parts = _segments(path)
    node: Any = doc
    for part in parts[:-1]:
        try:
            node = node[part]
        except (KeyError, IndexError, TypeError):
            return False
    last = parts[-1] if parts else None
    if isinstance(node, dict) and isinstance(last, str) and last in node and last not in _REQUIRED:
        del node[last]
        return True
    return False


_REQUIRED = {"name", "company", "position", "institution", "title", "organization", "language", "text"}


def finalize(converted: Converted) -> tuple[dict[str, Any], list[Note]]:
    """Normalize the converted document. Values that still fail validation are removed (with a note) once;
    anything that can't be repaired that way fails the import."""
    notes = list(converted.notes)
    if not converted.document.get("work") and not converted.document.get("projects"):
        # A master needs at least one role or project to tailor from; ask for one instead of failing.
        converted.document["work"] = [{"company": "Your employer", "position": "Your role"}]
        notes.append(Note("work[0]", "warning", "No experience or projects were found. Replace this placeholder "
                                                "with a real role, or delete it and add a project.", source="import"))
    result: NormalizeResult = normalize(converted.document)
    if result.errors:
        repaired = True
        for issue in result.errors:
            if _drop(converted.document, issue.path):
                notes.append(Note(issue.path.rsplit(".", 1)[0], "warning",
                                  f"Removed {issue.path.rsplit('.', 1)[-1]}: {issue.message}", source="import"))
            else:
                repaired = False
        result = normalize(converted.document) if repaired else result
    if not result.ok or result.document is None:
        raise ImportRejected("bad_output", "The transcription couldn't be turned into a master résumé. Retry the "
                                           "import.")
    return result.document, notes


def locate(doc: dict[str, Any], path: str) -> tuple[str | None, str | None]:
    """The id of the deepest item on ``path`` and the field below it: ``work[2].endDate`` → (``work-3``,
    ``endDate``); ``basics.phone`` → (``basics``, ``phone``)."""
    parts = _segments(path)
    node: Any = doc
    target: str | None = "basics" if parts[:1] == ["basics"] else None
    rest_from = 1 if target else 0
    for n, part in enumerate(parts):
        try:
            node = node[part]
        except (KeyError, IndexError, TypeError):
            break
        if isinstance(node, dict) and isinstance(node.get("id"), str):
            target, rest_from = node["id"], n + 1
    if target is None:  # a whole section, or a path that doesn't exist (any more)
        return None, None
    field_name = ".".join(str(p) for p in parts[rest_from:] if isinstance(p, str)) or None
    return target, field_name
