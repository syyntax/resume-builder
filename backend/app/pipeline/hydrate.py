"""Turn a TailorDraft into a TailoredResume (DESIGN.md §7.3, guardrails G1, G2, G5).

The draft only *references* master items. Every hard fact (employer, title, dates, degree, contact details)
is copied from the master version here, so the model can't change it. References that don't resolve are
reported as `problems` (the caller asks the model to repair them once) and dropped.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.ai.schemas import DraftBullet, TailorDraft

FACT_FIELDS = {
    "work": ("company", "position", "location", "url", "startDate", "endDate", "employmentType"),
    "projects": ("name", "description", "url", "startDate", "endDate", "roles"),
    "education": ("institution", "url", "area", "studyType", "startDate", "endDate", "score", "honors"),
    "certifications": ("name", "issuer", "date", "expires", "url", "credentialId"),
    "awards": ("title", "date", "awarder", "summary"),
    "publications": ("name", "publisher", "releaseDate", "url"),
    "volunteer": ("organization", "position", "url", "startDate", "endDate"),
    "languages": ("language", "fluency"),
}
SECTION_TITLES = {
    "experience": "Experience", "earlier-experience": "Earlier Experience", "projects": "Projects",
    "skills": "Skills", "education": "Education", "certifications": "Certifications", "awards": "Awards",
    "publications": "Publications", "volunteer": "Volunteering", "languages": "Languages",
}
INCLUDE_SECTIONS = ("education", "certifications", "awards", "publications", "volunteer", "languages")


@dataclass
class MasterIndex:
    doc: dict[str, Any]
    items: dict[str, dict[str, dict[str, Any]]] = field(default_factory=dict)  # section -> id -> item
    bullets: dict[str, dict[str, dict[str, Any]]] = field(default_factory=dict)  # item id -> bullet id -> bullet
    owner_of: dict[str, str] = field(default_factory=dict)  # bullet id -> item id
    all_ids: set[str] = field(default_factory=set)
    hidden: set[str] = field(default_factory=set)

    @classmethod
    def build(cls, doc: dict[str, Any]) -> MasterIndex:
        index = cls(doc=doc)
        for section in ("headlines", "summaries", "work", "projects", "education", "certifications", "skills",
                        "awards", "publications", "volunteer", "languages", "customSections"):
            index.items[section] = {}
            for item in doc.get(section) or []:
                index._add(section, item)
                for bullet in item.get("highlights") or []:
                    if isinstance(bullet, dict) and bullet.get("id"):
                        index.bullets.setdefault(item["id"], {})[bullet["id"]] = bullet
                        index.owner_of[bullet["id"]] = item["id"]
                        index.all_ids.add(bullet["id"])
                        if bullet.get("hidden") or item.get("hidden"):
                            index.hidden.add(bullet["id"])
                for child in item.get("items") or []:  # custom section items
                    index.items.setdefault(f"custom:{item['id']}", {})[child["id"]] = child
                    index.all_ids.add(child["id"])
                    if child.get("hidden") or item.get("hidden"):
                        index.hidden.add(child["id"])
        return index

    def _add(self, section: str, item: dict[str, Any]) -> None:
        self.items[section][item["id"]] = item
        self.all_ids.add(item["id"])
        if item.get("hidden"):
            self.hidden.add(item["id"])

    def usable(self, section: str, item_id: str) -> dict[str, Any] | None:
        item = self.items.get(section, {}).get(item_id)
        return None if item is None or item_id in self.hidden else item


@dataclass
class Hydrated:
    resume: dict[str, Any]
    problems: list[str] = field(default_factory=list)  # unresolved references (sent back for one repair)
    notices: list[dict[str, str]] = field(default_factory=list)  # automatic fixes the user should know about


def _facts(section: str, item: dict[str, Any]) -> dict[str, Any]:
    return {"sourceId": item["id"], **{k: item[k] for k in FACT_FIELDS[section] if k in item}}


class _Hydrator:
    def __init__(self, draft: TailorDraft, index: MasterIndex) -> None:
        self.draft, self.index = draft, index
        self.problems: list[str] = []
        self.notices: list[dict[str, str]] = []
        self._next_bullet = 0

    def bullet_id(self) -> str:
        self._next_bullet += 1
        return f"tb-{self._next_bullet}"

    def sourced(self, label: str, text: str, source_ids: list[str]) -> dict[str, Any]:
        bad = [s for s in source_ids if s not in self.index.all_ids or s in self.index.hidden]
        for s in bad:
            self.problems.append(f"{label} cites {s!r}, which isn't a visible item in the master résumé")
        return {"text": text.strip(), "sourceIds": [s for s in source_ids if s not in bad], "edited": False,
                "aiText": text.strip()}

    def bullets(self, section: str, item: dict[str, Any], drafted: list[DraftBullet]) -> list[dict[str, Any]]:
        own = self.index.bullets.get(item["id"], {})
        out, cited = [], set()
        for n, b in enumerate(drafted, start=1):
            foreign = [s for s in b.source_ids if s != item["id"] and (s not in own or s in self.index.hidden)]
            if not b.source_ids or foreign or not b.text.strip():
                what = ", ".join(repr(s) for s in foreign) or "nothing"
                self.problems.append(
                    f"{section} {item['id']!r} bullet {n} cites {what}; bullets must cite bullets of that same item"
                )
                continue
            cited.update(b.source_ids)
            out.append({"id": self.bullet_id(), "text": b.text.strip(), "sourceIds": b.source_ids,
                        "relevance": b.relevance, "keywords": b.keywords, "origin": "ai", "edited": False,
                        "aiText": b.text.strip(), "warnings": []})
        for bid, bullet in own.items():  # pinned bullets are always included
            if bullet.get("pin") and bid not in cited and bid not in self.index.hidden:
                out.append({"id": self.bullet_id(), "text": bullet["text"], "sourceIds": [bid], "relevance": 5,
                            "keywords": [], "origin": "master", "edited": False, "warnings": []})
                self.notices.append({"targetId": bid, "code": "PINNED_ADDED",
                                     "message": "Pinned bullet added from your master résumé."})
        return out

    def entries(self, section: str, drafted: list[Any], id_attr: str) -> list[dict[str, Any]]:
        out, seen = [], set()
        for d in drafted:
            item_id = getattr(d, id_attr)
            item = self.index.usable(section, item_id)
            if item is None:
                self.problems.append(f"{section}: {item_id!r} isn't a visible {section} item in the master résumé")
                continue
            if item_id in seen:
                continue
            seen.add(item_id)
            out.append({**_facts(section, item), "bullets": self.bullets(section, item, d.bullets)})
        return out

    def run(self) -> dict[str, Any]:
        d, ix = self.draft, self.index
        experience = self.entries("work", d.experience, "work_id")
        projects = self.entries("projects", d.projects, "project_id")
        included = {e["sourceId"] for e in experience}
        for work in (ix.doc.get("work") or []):  # pinned roles are always included
            if work.get("pin") and not work.get("hidden") and work["id"] not in included:
                experience.append({**_facts("work", work), "bullets": self.bullets("work", work, [])})
                self.notices.append({"targetId": work["id"], "code": "PINNED_ADDED",
                                     "message": "Pinned role added from your master résumé."})
        # Keep roles in master order regardless of the draft's order.
        order = {w["id"]: i for i, w in enumerate(ix.doc.get("work") or [])}
        experience.sort(key=lambda e: order.get(e["sourceId"], 0))
        included = {e["sourceId"] for e in experience}

        earlier = []
        for wid in d.earlier_experience_ids:
            work = ix.usable("work", wid)
            if work is None:
                self.problems.append(f"earlierExperienceIds: {wid!r} isn't a visible work item")
            elif wid not in included:
                earlier.append(_facts("work", work))
                included.add(wid)

        skills = []
        for group in d.skills:
            items = []
            for s in group.skills:
                skill = ix.usable("skills", s.skill_id)
                if skill is None:
                    self.problems.append(f"skills: {s.skill_id!r} isn't a visible skill in the master résumé")
                    continue
                names = {skill["name"].lower(), *(a.lower() for a in skill.get("aliases") or [])}
                display = s.display.strip()
                if display.lower() not in names:  # G5: only the skill's name or a listed alias
                    self.notices.append({"targetId": skill["id"], "code": "SKILL_DISPLAY_REPLACED",
                                         "message": f'"{display}" isn\'t a name or alias of {skill["name"]}; '
                                                    "used the skill's name."})
                    display = skill["name"]
                items.append({"skillId": skill["id"], "display": display})
            if items:
                skills.append({"name": group.group.strip() or "Skills", "items": items})

        simple: dict[str, list[dict[str, Any]]] = {}
        for section in INCLUDE_SECTIONS:
            simple[section] = []
            for item_id in getattr(d.include, section):
                item = ix.usable(section, item_id)
                if item is None:
                    self.problems.append(f"include.{section}: {item_id!r} isn't a visible {section} item")
                else:
                    simple[section].append(_facts(section, item))

        custom = []
        for cs in d.include.custom_sections:
            section = ix.usable("customSections", cs.section_id)
            if section is None:
                self.problems.append(f"customSections: {cs.section_id!r} isn't a visible custom section")
                continue
            children = []
            for item_id in cs.item_ids:
                child = ix.usable(f"custom:{section['id']}", item_id)
                if child is None:
                    self.problems.append(f"customSections {section['id']!r}: {item_id!r} isn't one of its items")
                else:
                    keep = ("title", "subtitle", "date", "startDate", "endDate", "url", "summary")
                    children.append({"sourceId": child["id"], **{k: child[k] for k in keep if k in child}})
            if children:
                custom.append({"type": "custom", "title": section["title"], "sourceId": section["id"],
                               "items": children})

        built: dict[str, list[dict[str, Any]]] = {
            "experience": [{"type": "experience", "title": SECTION_TITLES["experience"], "items": experience}]
            + ([{"type": "earlier-experience", "title": SECTION_TITLES["earlier-experience"], "items": earlier}]
               if earlier else []),
            "projects": [{"type": "projects", "title": "Projects", "items": projects}] if projects else [],
            "skills": [{"type": "skills", "title": "Skills", "groups": skills}] if skills else [],
            "custom": custom,
        }
        for section in INCLUDE_SECTIONS:
            if simple[section]:
                built[section] = [{"type": section, "title": SECTION_TITLES[section], "items": simple[section]}]

        sections: list[dict[str, Any]] = []
        placed: set[str] = set()
        for name in [*d.section_order, *built]:  # the draft's order first, then anything it forgot
            if name in built and name not in placed:
                sections.extend(built[name])
                placed.add(name)

        headline = self.sourced("headline", d.headline.text, d.headline.source_ids)
        if not headline["text"]:
            first = next(iter(ix.items.get("headlines", {}).values()), None)
            headline = {"text": first["text"], "sourceIds": [first["id"]], "edited": False} if first else headline
        summary = self.sourced("summary", d.summary.text, d.summary.source_ids)
        return {"headline": headline, "summary": summary, "sections": [s for s in sections if s.get("items") or
                                                                      s.get("groups")]}


def hydrate(draft: TailorDraft, master: dict[str, Any]) -> Hydrated:
    index = MasterIndex.build(master)
    hydrator = _Hydrator(draft, index)
    body = hydrator.run()
    basics = dict(master.get("basics") or {})
    if not (master.get("preferences") or {}).get("showWorkAuthorization"):
        basics.pop("workAuthorization", None)
    resume = {"basics": basics, **body}
    return Hydrated(resume=resume, problems=hydrator.problems, notices=hydrator.notices)
