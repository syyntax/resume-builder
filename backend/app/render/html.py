"""Document JSON → HTML for a template (DESIGN.md §11.1).

Templates get a prepared *view* (dates formatted, roles at one company grouped, contact links built) so
they stay simple. Jinja autoescaping is on; the only markup allowed inside text is **bold** and *italic*.
Links are built here and only ever use https, mailto or tel.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape
from markupsafe import Markup, escape

from app.render.fonts import PAIRINGS, font_css, stack
from app.render.theme import DENSITIES, TEMPLATES, Theme

TEMPLATE_DIR = Path(__file__).parent / "templates"
_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
_LONG_MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
                "November", "December"]
_PAPER = {"letter": "Letter", "a4": "A4"}
ACCENT_BAR_PX = 7

_env = Environment(
    loader=FileSystemLoader(TEMPLATE_DIR),
    autoescape=select_autoescape(["html", "j2"], default=True),
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
)


def inline(text: str | None) -> Markup:
    """Escape, then allow **bold** and *italic*."""
    out = str(escape(text or ""))
    out = re.sub(r"\*\*(\S(?:.*?\S)?)\*\*", r"<strong>\1</strong>", out)
    out = re.sub(r"(?<![*\w])\*(\S(?:.*?\S)?)\*(?![*\w])", r"<em>\1</em>", out)
    return Markup(out)  # noqa: S704  (built from escaped text; only <strong> and <em> are added)


_env.filters["inline"] = inline


# ---- dates -----------------------------------------------------------------------------------------------


def format_date(value: str | None, fmt: str) -> str:
    if not value:
        return ""
    parts = value.split("-")
    year = parts[0]
    if len(parts) == 1 or fmt == "YYYY":
        return year
    month = int(parts[1])
    return f"{month:02d}/{year}" if fmt == "MM/YYYY" else f"{_MONTHS[month - 1]} {year}"


def date_range(item: dict[str, Any], fmt: str, *, current: bool = True) -> str:
    """'Mar 2021 – Present'. ``current``: a missing end date means "Present" (roles), or nothing (degrees)."""
    start = format_date(item.get("startDate"), fmt)
    end = format_date(item.get("endDate"), fmt)
    if start and end:
        return start if start == end else f"{start} – {end}"
    if start:
        return f"{start} – Present" if current else start
    return end or format_date(item.get("date"), fmt)


def long_date(value: str) -> str:
    parsed = date.fromisoformat(value)
    return f"{_LONG_MONTHS[parsed.month - 1]} {parsed.day}, {parsed.year}"


# ---- contact details --------------------------------------------------------------------------------------


def display_url(url: str) -> str:
    return re.sub(r"^(https?://)?(www\.)?", "", url.strip()).rstrip("/")


def _href(url: str) -> str | None:
    url = url.strip()
    if re.match(r"^https?://", url, re.IGNORECASE):
        return url
    if re.match(r"^[\w.-]+\.[a-z]{2,}(/\S*)?$", url, re.IGNORECASE):
        return f"https://{url}"
    return None  # anything else (javascript:, data:, …) is shown as text, never linked


def contact_items(basics: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if email := basics.get("email"):
        items.append({"icon": "mail", "text": email, "href": f"mailto:{email}" if "@" in email else None})
    if phone := basics.get("phone"):
        digits = re.sub(r"[^\d+]", "", phone)
        items.append({"icon": "phone", "text": phone, "href": f"tel:{digits}" if digits else None})
    location = basics.get("location") or {}
    place = ", ".join(p for p in (location.get("city"), location.get("region")) if p)
    if location.get("remote"):
        place = f"{place} · Remote" if place else "Remote"
    if place:
        items.append({"icon": "pin", "text": place, "href": None})
    for profile in basics.get("profiles") or []:
        url = profile.get("url") or ""
        network = (profile.get("network") or "").lower()
        if not url and profile.get("username") and network in ("linkedin", "github"):
            url = f"{'linkedin.com/in' if network == 'linkedin' else 'github.com'}/{profile['username']}"
        if url:
            icon = "linkedin" if "linkedin" in (network + url.lower()) else "code" if (
                "github" in network + url.lower() or "gitlab" in network + url.lower()) else "link"
            items.append({"icon": icon, "text": display_url(url), "href": _href(url)})
    if url := basics.get("url"):
        items.append({"icon": "link", "text": display_url(url), "href": _href(url)})
    if auth := basics.get("workAuthorization"):
        items.append({"icon": "check", "text": auth, "href": None})
    return items


# ---- the résumé view --------------------------------------------------------------------------------------


def _experience(items: list[dict[str, Any]], fmt: str) -> list[dict[str, Any]]:
    """Consecutive roles at the same company become one group (a promotion shows under one employer)."""
    groups: list[dict[str, Any]] = []
    for item in items:
        role = {"position": item.get("position", ""), "dates": date_range(item, fmt),
                "type": item.get("employmentType"), "bullets": item.get("bullets") or []}
        company = item.get("company", "")
        if groups and groups[-1]["company"].casefold() == company.casefold():
            groups[-1]["roles"].append(role)
            groups[-1]["location"] = groups[-1]["location"] or item.get("location")
        else:
            groups.append({"company": company, "location": item.get("location"), "roles": [role]})
    return groups


def _entry(kind: str, item: dict[str, Any], fmt: str) -> dict[str, Any]:
    """A generic titled entry: certifications, education, awards, publications, volunteering, custom."""
    if kind == "education":
        degree = " ".join(p for p in (item.get("studyType"), item.get("area")) if p)
        title, meta = degree or item.get("institution", ""), [item.get("institution") if degree else None,
                                                              date_range(item, fmt, current=False), item.get("score")]
    elif kind == "certifications":
        title, meta = item.get("name", ""), [item.get("issuer"), format_date(item.get("date"), fmt)]
    elif kind == "awards":
        title, meta = item.get("title", ""), [item.get("awarder"), format_date(item.get("date"), fmt)]
    elif kind == "publications":
        title, meta = item.get("name", ""), [item.get("publisher"), format_date(item.get("releaseDate"), fmt)]
    elif kind == "volunteer":
        title = ", ".join(p for p in (item.get("position"), item.get("organization")) if p)
        meta = [date_range(item, fmt)]
    else:  # custom
        title, meta = item.get("title", ""), [item.get("subtitle"), date_range(item, fmt, current=False)]
    return {"title": title, "meta": " · ".join(m for m in meta if m), "summary": item.get("summary"),
            "bullets": item.get("bullets") or []}


_PAIRABLE = {"certifications", "education"}


def resume_view(resume: dict[str, Any], theme: Theme) -> dict[str, Any]:
    fmt = theme.date_format
    basics = resume.get("basics") or {}
    sections: list[dict[str, Any]] = []
    for section in resume.get("sections") or []:
        kind, title = section["type"], section.get("title") or ""
        items = section.get("items") or []
        if kind == "experience":
            sections.append({"kind": kind, "title": title, "groups": _experience(items, fmt)})
        elif kind == "earlier-experience":
            entries = [", ".join(p for p in (i.get("position"), i.get("company")) if p)
                       + (f" ({when})" if (when := date_range(i, fmt)) else "") for i in items]
            sections.append({"kind": kind, "title": title, "entries": entries})
        elif kind == "projects":
            sections.append({"kind": kind, "title": title, "entries": [
                {"name": i.get("name", ""), "aside": i.get("description"),
                 "right": date_range(i, fmt, current=False) or (display_url(i["url"]) if i.get("url") else ""),
                 "bullets": i.get("bullets") or []} for i in items]})
        elif kind == "skills":
            sections.append({"kind": kind, "title": title, "groups": [
                {"name": g["name"], "text": ", ".join(s["display"] for s in g["items"])}
                for g in section.get("groups") or []]})
        elif kind == "languages":
            sections.append({"kind": kind, "title": title, "text": " · ".join(
                i.get("language", "") + (f" ({i['fluency']})" if i.get("fluency") else "") for i in items)})
        else:
            sections.append({"kind": "entries", "type": kind, "title": title,
                             "entries": [_entry(kind, i, fmt) for i in items]})

    # Certifications and education side by side when they're next to each other and short (Meridian's split).
    paired: list[dict[str, Any]] = []
    for section in sections:
        previous = paired[-1] if paired else None
        if (previous and previous.get("type") in _PAIRABLE and section.get("type") in _PAIRABLE
                and previous["kind"] == "entries" and len(previous["entries"]) <= 4 and len(section["entries"]) <= 4):
            paired[-1] = {"kind": "split", "parts": [previous, section]}
        else:
            paired.append(section)

    headline = (resume.get("headline") or {}).get("text") or basics.get("label") or ""
    return {
        "name": basics.get("name", ""),
        "headline": headline,
        "contact": contact_items(basics),
        "summary": (resume.get("summary") or {}).get("text") or "",
        "sections": paired,
    }


# ---- page setup and assembly --------------------------------------------------------------------------------


def _css_string(text: str) -> str:
    """A CSS string literal that can't end the string or the <style> element."""
    escaped = text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ").replace("<", "\\3C ")
    return f'"{escaped}"'


def page_css(template: str, theme: Theme, footer_name: str) -> str:
    top, sides, bottom = TEMPLATES[template].margins[theme.margins]
    pairing = PAIRINGS[theme.fonts]
    density = DENSITIES[theme.density]
    size = density.size_pt
    accent = theme.accent
    bar = "".join(f"@{box}{{content:\"\";background:{accent};}}" for box in
                  ("top-left-corner", "top-left", "top-center", "top-right", "top-right-corner"))
    footer = (f'@bottom-right{{content:{_css_string(footer_name)} " \\B7  Page " counter(page) " of " '
              f'counter(pages);font-family:{stack(pairing.body)};font-size:7.5pt;color:#64748b;}}')
    return (
        f"@page{{size:{_PAPER[theme.paper]};margin:{top}in {sides}in {bottom}in;{footer}}}\n"
        f"@page :first{{margin-top:{ACCENT_BAR_PX}px;{bar}@bottom-right{{content:none;}}}}\n"
        f":root{{--accent:{accent};--font-heading:{stack(pairing.heading)};--font-body:{stack(pairing.body)};"
        f"--base-size:{size}pt;--leading:{density.leading};--space:{density.space};"
        f"--first-top:calc({top}in - {ACCENT_BAR_PX}px);}}\n"
    )


def _document(template: str, kind: str, context: dict[str, Any], theme: Theme, title: str, footer: str) -> str:
    style = (TEMPLATE_DIR / template / "style.css").read_text(encoding="utf-8")
    page = _env.get_template(f"{template}/{kind}.html.j2")
    return page.render(
        title=title, theme=theme, css=Markup(font_css(theme.fonts) + "\n" + page_css(template, theme, footer) + style),  # noqa: S704
        **context,
    )


def render_resume_html(resume: dict[str, Any], template: str, theme: Theme, *, title: str) -> str:
    view = resume_view(resume, theme)
    return _document(template, "resume", {"view": view}, theme, title, view["name"])


def letter_view(letter: dict[str, Any], resume_basics: dict[str, Any] | None = None) -> dict[str, Any]:
    sender = letter.get("sender") or resume_basics or {}
    recipient = letter.get("recipient") or {}
    lines = [recipient.get(k) for k in ("name", "title", "company")] + list(recipient.get("address") or [])
    return {
        "name": sender.get("name", ""),
        "headline": sender.get("label") or "",
        "contact": contact_items(sender),
        "date": long_date(letter["date"]) if letter.get("date") else "",
        "recipient": [line for line in lines if line],
        "subject": letter.get("subject") or "",
        "salutation": letter.get("salutation") or "",
        "paragraphs": [p.get("text", "") for p in letter.get("paragraphs") or []],
        "closing": letter.get("closing") or "Sincerely,",
        "signature": letter.get("signature") or sender.get("name", ""),
    }


def render_letter_html(letter: dict[str, Any], template: str, theme: Theme, *, title: str) -> str:
    view = letter_view(letter)
    return _document(template, "cover_letter", {"view": view}, theme, title, view["name"])
