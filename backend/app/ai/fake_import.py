"""Stage I for the offline stand-in model (AI_PROVIDER=fake): a heuristic résumé parser.

It understands the common layouts (section headings; "Position, Company" over a dates line; bulleted
highlights; LinkedIn's "Company / Title / dates" blocks) and copies text verbatim, so it exercises the
whole import pipeline. It's no substitute for the real model on unusual layouts.
"""

from __future__ import annotations

import re
from typing import Any

_HEADINGS = {
    "summary": ("summary", "profile", "professional summary", "about", "about me", "objective"),
    "work": ("experience", "work experience", "professional experience", "employment", "employment history",
             "work history"),
    "education": ("education",),
    "skills": ("skills", "technical skills", "top skills", "core skills", "skills & tools"),
    "projects": ("projects", "selected projects", "open source"),
    "certifications": ("certifications", "certificates", "licenses & certifications", "licenses and certifications"),
    "awards": ("awards", "honors", "honors & awards", "honors-awards"),
    "languages": ("languages",),
    "interests": ("interests",),
    "volunteer": ("volunteer", "volunteering", "volunteer experience"),
    "contact": ("contact",),
}
_HEADING_OF = {name: kind for kind, names in _HEADINGS.items() for name in names}
_MONTH = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
_DATE = rf"(?:{_MONTH}\s+)?\d{{4}}"
_RANGE = re.compile(rf"(?P<start>{_DATE})\s*(?:-|–|—|to)\s*(?P<end>{_DATE}|present|current|now)", re.IGNORECASE)
_YEAR = re.compile(r"\b(19|20)\d{2}\b")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_PHONE = re.compile(r"\+?\(?\d[\d\s().-]{7,}\d")
_URL = re.compile(r"(?:https?://)?(?:www\.)?(?:[\w-]+\.)+(?:com|dev|io|me|net|org)(?:/[\w./-]*)?", re.IGNORECASE)
_LOCATION = re.compile(r"^[A-Z][A-Za-z .'-]+, [A-Z][A-Za-z .]+$")
_BULLET = re.compile(r"^(?:[-•*▪◦–]\s+)")
_PAGE = re.compile(r"^page \d+ of \d+$", re.IGNORECASE)
_PERSON = re.compile(r"^[A-Z][a-z'-]+(?: [A-Z][a-z'.-]+){1,3}$")
_INSTITUTION = re.compile(r"\b(university|college|institute|school|academy)\b", re.IGNORECASE)
_DEGREE = re.compile(r"\b(b\.?s\.?|b\.?a\.?|m\.?s\.?|m\.?a\.?|mba|ph\.?d\.?|bachelor|master|associate|diploma)\b",
                     re.IGNORECASE)
_SEPARATORS = (" | ", " at ", " — ", " – ", " - ", ", ")
_TECH = ("Kubernetes", "Terraform", "AWS", "GCP", "Azure", "Docker", "Python", "Go", "Java", "TypeScript",
         "JavaScript", "React", "PostgreSQL", "MySQL", "Kafka", "Redis", "Argo Rollouts", "Prometheus", "Grafana",
         "Datadog", "Jenkins", "GitHub Actions", "Spark", "Snowflake", "Airflow", "Splunk", "Linux", "Ansible")
_MONTHS = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov",
                                       "dec"), start=1)}


def _date(text: str) -> str:
    text = text.strip().lower()
    year = _YEAR.search(text)
    if not year:
        return ""
    month = _MONTHS.get(text[:3])
    return f"{year.group(0)}-{month:02d}" if month else year.group(0)


def _split(line: str) -> tuple[str, str]:
    for separator in _SEPARATORS:
        if separator in line:
            first, second = line.split(separator, 1)
            return first.strip(), second.strip()
    return line.strip(), ""


def _lines(text: str) -> tuple[list[tuple[str, bool]], list[str]]:
    """Body lines as (text, is_bullet), and the lines of Word headers and footers (contact details)."""
    out: list[tuple[str, bool]] = []
    margins: list[str] = []
    region = ""
    for raw in text.splitlines():
        line = raw.strip()
        if marker := re.fullmatch(r"\[([A-Za-z ]+)\]", line):
            region = marker.group(1)
            continue
        if not line:  # the worker separates header, body and footer with a blank line
            region = ""
            continue
        if region in ("Header", "Footer") and line:
            margins.append(line)
            continue
        if not line or _PAGE.match(line):
            continue
        line = re.sub(r"^#+\s*", "", line)
        bullet = bool(_BULLET.match(line))
        out.append((_BULLET.sub("", line).strip(), bullet))
    # LinkedIn exports put a sidebar first; their name line is followed by "Title at Company". Lead with it.
    for i in range(1, len(out) - 1):
        if _PERSON.match(out[i][0]) and " at " in out[i + 1][0]:
            out = out[i:i + 3] + out[:i] + out[i + 3:]
            break
    return out, margins


def _sections(lines: list[tuple[str, bool]]) -> tuple[list[tuple[str, bool]], list[tuple[str, str, list[Any]]]]:
    head: list[tuple[str, bool]] = []
    sections: list[tuple[str, str, list[Any]]] = []
    for line, bullet in lines:
        key = line.lower().rstrip(":").strip()
        if not bullet and key in _HEADING_OF:
            sections.append((_HEADING_OF[key], line.rstrip(":"), []))
        elif sections:
            sections[-1][2].append((line, bullet))
        else:
            head.append((line, bullet))
    return head, sections


def _work(lines: list[tuple[str, bool]]) -> list[dict[str, Any]]:
    dated = [i for i, (line, bullet) in enumerate(lines) if not bullet and _RANGE.search(line)]
    roles = []
    for k, d in enumerate(dated):
        floor = dated[k - 1] + 1 if k else 0
        header: list[str] = []
        i = d - 1
        while i >= floor and not lines[i][1] and len(header) < 2:
            header.insert(0, lines[i][0])
            i -= 1
        line = lines[d][0]
        match = _RANGE.search(line)
        if match is None:  # can't happen: dated lines were found with this pattern
            continue
        rest = [p.strip() for p in re.split(r"\s*\|\s*", _RANGE.sub("", line)) if p.strip(" ()|")]
        rest = [re.sub(r"\(.*?\)", "", p).strip() for p in rest]
        if len(header) == 2:
            company, position = header
        elif header:
            position, company = _split(header[0])
        else:
            position, company = "", ""
        end_text = match.group("end").lower()
        current = end_text in ("present", "current", "now")
        stop = (dated[k + 1] if k + 1 < len(dated) else len(lines))
        body = lines[d + 1:stop]
        next_header = 0
        if k + 1 < len(dated):  # the next role's header lines sit just above its dates line
            j = len(body) - 1
            while j >= 0 and not body[j][1] and next_header < 2:
                next_header += 1
                j -= 1
            if next_header == 2 and any(b for _, b in body[: len(body) - 2]):
                next_header = 1  # bulleted layout: only "Position, Company" belongs to the next role
        body = body[: len(body) - next_header] if next_header else body
        location = next((p for p in rest if p), "")
        highlights = []
        for text, _bullet in _join_wrapped(body):
            if not location and _LOCATION.match(text) and not highlights:
                location = text
            else:
                highlights.append(text)
        roles.append({"company": company, "position": position, "location": location,
                      "startDate": _date(match.group("start")), "endDate": "" if current else _date(end_text),
                      "current": current, "summary": "", "highlights": highlights, "tags": []})
    return roles


def _join_wrapped(lines: list[tuple[str, bool]]) -> list[tuple[str, bool]]:
    """PDF text wraps long bullets onto several lines; a line that doesn't end a sentence continues."""
    out: list[tuple[str, bool]] = []
    for text, bullet in lines:
        previous = out[-1][0] if out else ""
        if out and not bullet and not previous.endswith((".", "!", "?", ":")) and not _LOCATION.match(previous):
            out[-1] = (f"{previous} {text}", out[-1][1])
        else:
            out.append((text, bullet))
    return out


def _education(lines: list[tuple[str, bool]]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for line, _ in lines:
        parts = [p.strip() for p in re.split(r",\s*|\s+\|\s+|\s+-\s+", line) if p.strip()]
        institution = next((p for p in parts if _INSTITUTION.search(p)), "")
        degree = next((p for p in parts if _DEGREE.search(p)), "")
        years = _YEAR.findall(line)
        if institution or not entries:
            entries.append({"institution": institution, "studyType": "", "area": "", "startDate": "", "endDate": "",
                            "score": "", "courses": [], "honors": [], "highlights": []})
        entry = entries[-1]
        if degree:
            study, _, area = degree.partition(" in ")
            entry["studyType"], entry["area"] = study.strip(), area.strip()
            remaining = [p for p in parts if p not in (degree, institution) and not _YEAR.fullmatch(p)]
            if not entry["area"] and remaining:
                entry["area"] = remaining[0]
        if years:
            entry["endDate"] = _date(re.findall(rf"{_DATE}", line, re.IGNORECASE)[-1])
    return [e for e in entries if e["institution"] or e["studyType"]]


def _skills(lines: list[tuple[str, bool]]) -> list[dict[str, Any]]:
    skills = []
    for line, _ in lines:
        category, sep, names = line.partition(":") if ":" in line else line.partition(" | ")
        if not sep:
            category, names = "Skills", line
        for name in re.split(r",\s*|\s+[•|]\s+", names):
            if name.strip():
                skills.append({"name": name.strip(), "category": category.strip(), "level": "", "aliases": []})
    return skills


def _certifications(lines: list[tuple[str, bool]]) -> list[dict[str, Any]]:
    out = []
    for line, _ in lines:
        dates = re.findall(rf"{_DATE}", line, re.IGNORECASE)
        text = re.sub(rf"\(?{_DATE}\)?", "", line, flags=re.IGNORECASE).strip(" ,-–(")
        name, issuer = _split(text)
        out.append({"name": name, "issuer": issuer, "date": _date(dates[-1]) if dates else "", "expires": "",
                    "credentialId": "", "url": ""})
    return out


def _projects(lines: list[tuple[str, bool]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for line, bullet in lines:
        if bullet and out:
            out[-1]["highlights"].append(line)
            continue
        name, description = _split(line)
        out.append({"name": name, "description": description, "url": "", "startDate": "", "endDate": "",
                    "highlights": [], "tags": []})
    return out


def transcribe(text: str) -> dict[str, Any]:
    lines, margins = _lines(text)
    head, sections = _sections(lines)
    contact_lines = margins + [line for line, _ in head] + [line for kind, _, body in sections if kind == "contact"
                                                            for line, _ in body]
    blob = "\n".join(contact_lines)
    name = next((ln for ln in contact_lines if not re.search(r"[\d@/]", ln) and 1 < len(ln.split()) <= 5
                 and "," not in ln), "")
    after = contact_lines[contact_lines.index(name) + 1:] if name in contact_lines else []
    first = re.split(r"\s+[|•·]\s+", after[0])[0].strip() if after else ""
    label = "" if (_EMAIL.search(first) or _PHONE.search(first) or _URL.search(first) or _LOCATION.match(first)
                   ) else re.sub(r" at .*$", "", first)
    email = (m.group(0) if (m := _EMAIL.search(blob)) else "")
    phone = (m.group(0).strip() if (m := _PHONE.search(blob)) else "")
    urls = [u for u in _URL.findall(blob) if "@" not in u and u not in email]
    profiles = [{"network": "LinkedIn" if "linkedin" in u.lower() else "GitHub",
                 "username": u.rstrip("/").rsplit("/", 1)[-1], "url": u}
                for u in urls if "linkedin" in u.lower() or "github" in u.lower()]
    site = next((u for u in urls if "linkedin" not in u.lower() and "github" not in u.lower()), "")
    location_text = next((part.strip() for ln in contact_lines for part in re.split(r"\s+[|·•]\s+", ln)
                          if _LOCATION.match(part.strip())), "")
    city, _, region = location_text.partition(", ")

    draft: dict[str, Any] = {
        "basics": {"name": name, "label": label, "email": email, "phone": phone, "url": site,
                   "location": {"city": city, "region": region, "countryCode": ""}, "profiles": profiles},
        "headline": label, "summary": "", "work": [], "projects": [], "education": [], "certifications": [],
        "skills": [], "inferredSkills": [], "awards": [], "publications": [], "volunteer": [], "languages": [],
        "interests": [], "customSections": [], "importNotes": [],
    }
    for kind, title, body in sections:
        if kind == "summary":
            draft["summary"] = " ".join(line for line, _ in body)
        elif kind == "work":
            draft["work"] += _work(body)
        elif kind == "education":
            draft["education"] += _education(body)
        elif kind == "skills":
            draft["skills"] += _skills(body)
        elif kind == "certifications":
            draft["certifications"] += _certifications(body)
        elif kind == "projects":
            draft["projects"] += _projects(body)
        elif kind == "languages":
            for ln, _ in body:
                fluency = re.findall(r"\((.*?)\)", ln) or [_split(ln)[1]]
                draft["languages"].append({"language": _split(ln)[0].split(" (")[0], "fluency": fluency[0]})
        elif kind == "interests":
            draft["interests"] += [{"name": n.strip(), "keywords": []} for ln, _ in body for n in ln.split(",")
                                   if n.strip()]
        elif kind == "awards":
            draft["awards"] += [{"title": _split(ln)[0], "date": _date(ln) if _YEAR.search(ln) else "",
                                 "awarder": _split(ln)[1], "summary": ""} for ln, _ in body]
        elif kind != "contact":
            draft["customSections"].append({"title": title, "items": [
                {"title": ln, "subtitle": "", "date": "", "summary": "", "highlights": []} for ln, _ in body]})

    notes = draft["importNotes"]
    seen: dict[tuple[str, str], int] = {}
    for i, role in enumerate(draft["work"]):
        if not role["startDate"]:
            notes.append({"path": f"work[{i}].startDate", "severity": "warning", "message": "Start date missing."})
        elif len(role["startDate"]) == 4:
            notes.append({"path": f"work[{i}].startDate", "severity": "info", "message": "Only the year is given."})
        key = (role["company"].lower(), role["position"].lower())
        if key in seen:
            notes.append({"path": f"work[{i}]", "severity": "warning",
                          "message": f"Possible duplicate of work[{seen[key]}]."})
        seen.setdefault(key, i)
    listed = {s["name"].lower() for s in draft["skills"]}
    for term in _TECH:
        if term.lower() in listed:
            continue
        for role in draft["work"]:
            hit = next((h for h in role["highlights"] if re.search(rf"(?<!\w){re.escape(term)}(?!\w)", h)), None)
            if hit:
                draft["inferredSkills"].append({"name": term, "category": "Technologies", "evidence": hit[:120]})
                break
    return draft
