"""Text exports of a TailoredResume (DESIGN.md §11, EXP-3 Markdown and EXP-4 JSON)."""

from __future__ import annotations

import re
from typing import Any

_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def format_date(value: str | None, *, end: bool = False) -> str:
    if not value:
        return "Present" if end else ""
    parts = value.split("-")
    if len(parts) == 1:
        return parts[0]
    return f"{_MONTHS[int(parts[1]) - 1]} {parts[0]}"


def date_range(item: dict[str, Any]) -> str:
    start = format_date(item.get("startDate"))
    if not start:
        return format_date(item.get("endDate")) if item.get("endDate") else ""
    return f"{start} – {format_date(item.get('endDate'), end=True)}"


def contact_line(basics: dict[str, Any]) -> list[str]:
    location = basics.get("location") or {}
    place = ", ".join(p for p in (location.get("city"), location.get("region")) if p)
    if location.get("remote"):
        place = f"{place} (Remote)" if place else "Remote"
    profiles = [p.get("url") for p in basics.get("profiles") or [] if p.get("url")]
    return [p for p in (basics.get("email"), basics.get("phone"), place, basics.get("url"), *profiles) if p]


def _md(text: str) -> str:
    return re.sub(r"([\\`*_\[\]<>#|])", r"\\\1", text)


def to_markdown(resume: dict[str, Any]) -> str:
    basics = resume.get("basics") or {}
    lines = [f"# {_md(basics.get('name', ''))}"]
    if (resume.get("headline") or {}).get("text"):
        lines.append(f"**{_md(resume['headline']['text'])}**")
    contact = contact_line(basics)
    if contact:
        lines += ["", " · ".join(_md(c) for c in contact)]
    if (resume.get("summary") or {}).get("text"):
        lines += ["", "## Summary", "", _md(resume["summary"]["text"])]

    for section in resume.get("sections", []):
        lines += ["", f"## {_md(section['title'])}"]
        kind = section["type"]
        if kind == "skills":
            lines.append("")
            lines += [f"- **{_md(g['name'])}:** {', '.join(_md(i['display']) for i in g['items'])}"
                      for g in section["groups"]]
            continue
        if kind == "certifications":
            lines.append("")
            lines += [f"- **{_md(c['name'])}**" + "".join(f" · {_md(v)}" for v in
                      (c.get("issuer"), format_date(c.get("date"))) if v) for c in section["items"]]
            continue
        if kind == "languages":
            lines.append("")
            lines += [f"- {_md(x['language'])}" + (f" ({_md(x['fluency'])})" if x.get("fluency") else "")
                      for x in section["items"]]
            continue
        if kind == "earlier-experience":
            lines.append("")
            for item in section["items"]:
                when = date_range(item)
                lines.append(f"- {_md(item['position'])}, {_md(item['company'])}" + (f" ({when})" if when else ""))
            continue
        for item in section["items"]:
            lines.append("")
            if kind == "experience":
                lines.append(f"### {_md(item['position'])} · {_md(item['company'])}")
                meta = [m for m in (item.get("location"), date_range(item)) if m]
            elif kind == "projects":
                lines.append(f"### {_md(item['name'])}")
                meta = [m for m in (item.get("description"), item.get("url"), date_range(item)) if m]
            elif kind == "education":
                degree = " ".join(p for p in (item.get("studyType"), item.get("area")) if p)
                lines.append(f"### {_md(degree or item['institution'])}")
                meta = [m for m in (item["institution"] if degree else None, date_range(item)) if m]
            else:
                title = item.get("title") or item.get("name") or item.get("organization") or ""
                lines.append(f"### {_md(title)}")
                meta = [m for m in (item.get("subtitle"), item.get("awarder"), item.get("publisher"),
                                    item.get("position"), date_range(item) or format_date(item.get("date"))) if m]
            if meta:
                lines.append(f"*{' · '.join(_md(m) for m in meta)}*")
            if item.get("bullets"):
                lines.append("")
                lines += [f"- {_md(b['text'])}" for b in item["bullets"]]
    return "\n".join(lines).strip() + "\n"


def filename(resume: dict[str, Any], job: dict[str, Any], kind: str, ext: str) -> str:
    def slug(value: str | None) -> str:
        return re.sub(r"[^A-Za-z0-9]+", "-", value or "").strip("-")

    parts = [slug((resume.get("basics") or {}).get("name")), slug(job.get("company")), slug(job.get("title")), kind]
    return "_".join(p for p in parts if p)[:150] + f".{ext}"


def markdown_to_text(markdown: str) -> str:
    """Plain text for pasting into an application form's fields (EXP-7): the Markdown export without its markup,
    section headings in capitals."""
    lines = []
    for line in markdown.splitlines():
        if line.startswith("## "):
            line = line[3:].upper()
        elif line.startswith(("# ", "### ")):
            line = line.split(" ", 1)[1]
        elif line.startswith("*") and line.endswith("*") and not line.startswith("**") and len(line) > 1:
            line = line[1:-1]  # an italic meta line
        line = line.replace("**", "")  # our own bold markers (the text's asterisks are escaped)
        line = re.sub(r"\\(.)", r"\1", line)  # unescape
        line = re.sub(r"\*\*(\S(?:.*?\S)?)\*\*", r"\1", line)  # the text's own **bold** and *italic*
        line = re.sub(r"(?<![*\w])\*(\S(?:.*?\S)?)\*(?![*\w])", r"\1", line)
        lines.append(line)
    return "\n".join(lines).strip() + "\n"
