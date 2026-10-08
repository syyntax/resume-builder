"""The eval cases (DESIGN.md §17): (master, posting) pairs, and import documents with known contents.

The pairs cover strong fits, stretch roles, postings that ask for skills the master doesn't have (the model
must not invent them), and a posting with a prompt injection. Each names the page target it must meet.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tests import corpus

HERE = Path(__file__).parent
EXAMPLE_MASTER = HERE.parents[1] / "app" / "masters" / "example_master.json"
MASTERS = {
    "jordan": EXAMPLE_MASTER,
    "avery": HERE / "masters" / "avery-chen.json",
    "marcus": HERE / "masters" / "marcus-bell.json",
}


@dataclass(frozen=True)
class Case:
    id: str
    master: str
    posting: str  # file name in postings/
    company: str
    title: str
    page_limit: int = 1
    letter: dict[str, Any] = field(default_factory=dict)  # cover letter options (CoverLetterOptions)
    must_not_mention: tuple[str, ...] = ()  # claims the posting tries to plant

    def master_document(self) -> dict[str, Any]:
        return json.loads(MASTERS[self.master].read_text(encoding="utf-8"))

    def posting_text(self) -> str:
        return (HERE / "postings" / self.posting).read_text(encoding="utf-8")


CASES = [
    Case("globex-staff-platform", "jordan", "globex-staff-platform.txt", "Globex", "Staff Platform Engineer",
         letter={"notes": "I've used Globex's open-source SDKs for years and admire how well documented they are."}),
    Case("northwind-bank-sre", "jordan", "northwind-bank-sre.txt", "Northwind Bank", "Senior Site Reliability Engineer",
         letter={"recipient": {"name": "Dana Ortiz", "title": "Director of SRE"}, "tone": "formal"}),
    Case("contoso-health-devops", "jordan", "contoso-health-devops.txt", "Contoso Health", "DevOps Engineer"),
    Case("umbrella-eng-manager", "jordan", "umbrella-eng-manager.txt", "Umbrella Logistics",
         "Engineering Manager, Infrastructure", page_limit=2, letter={"length": "detailed"}),
    Case("initrode-platform-injection", "jordan", "initrode-platform-injection.txt", "Initrode", "Platform Engineer",
         must_not_mention=("Rust", "PhD", "Fellow")),
    Case("fernwood-senior-product-designer", "avery", "fernwood-senior-product-designer.txt", "Fernwood",
         "Senior Product Designer", letter={"tone": "warm", "notes": "My parents manage a small apartment "
                                                                     "building, so I've seen this work up close."}),
    Case("kestrel-design-systems-lead", "avery", "kestrel-design-systems-lead.txt", "Kestrel Bank",
         "Design Systems Lead", letter={"length": "short"}),
    Case("orbit-ux-researcher", "avery", "orbit-ux-researcher.txt", "Orbit Mobility", "UX Researcher"),
    Case("pinecrest-senior-data-analyst", "marcus", "pinecrest-senior-data-analyst.txt", "Pinecrest Grocers",
         "Senior Data Analyst", letter={"recipient": {"name": "Hiring Team"}}),
    Case("tidewater-analytics-engineer", "marcus", "tidewater-analytics-engineer.txt", "Tidewater Media",
         "Analytics Engineer"),
]


# ---- imports ------------------------------------------------------------------------------------------------

_SKILLS = tuple(s.strip() for _, names in corpus.SKILLS for s in names.split(","))
_BULLETS = [b for *_, bullets in corpus.WORK for b in bullets]


@dataclass(frozen=True)
class ImportCase:
    """A corpus document and the facts in it that an import must recover (each counts once toward fidelity)."""

    id: str
    filename: str
    build: Callable[[], bytes]
    project: bool = True
    phone: str | None = corpus.CONTACT[2]  # compared by digits: formatting may change
    skills: tuple[str, ...] = _SKILLS  # skill names, exactly
    line_limit: int | None = None  # the scan cuts lines off: only what's visible can be recovered

    def text(self) -> list[str]:
        """Text that appears in the imported document word for word (after normalizing whitespace and quotes)."""
        lines = [(corpus.NAME, ""), (corpus.CONTACT[1], ""), (corpus.SUMMARY, ""), *((b, "- ") for b in _BULLETS),
                 ("University of Colorado Boulder", ""), ("Certified Kubernetes Administrator", "")]
        if self.project:
            lines += [(corpus.PROJECT[0], ""), *((b, "- ") for b in corpus.PROJECT[2])]
        if self.line_limit is None:
            return [text for text, _ in lines]
        # what's left of each line, up to its last whole word
        limit = self.line_limit
        return [text if len(prefix + text) <= limit else text[:limit - len(prefix)].rsplit(" ", 1)[0]
                for text, prefix in lines]


IMPORTS = [
    ImportCase("text-pdf", "resume.pdf", corpus.text_pdf),
    ImportCase("two-column-pdf", "two-column.pdf", corpus.two_column_pdf, project=False),
    ImportCase("linkedin-pdf", "Profile.pdf", corpus.linkedin_pdf, project=False, phone=None,
               skills=("Kubernetes", "Terraform", "AWS")),
    ImportCase("scanned-pdf", "scan.pdf", corpus.scanned_pdf, line_limit=110),
    ImportCase("docx", "resume.docx", corpus.full_docx),
]
IMPORT_WORK = {  # company -> (position, start date as the import should normalize it); in every document
    "Acme Payments": ("Senior Platform Engineer", "2021-03"),
    "Initech": ("Software Engineer", "2017-06"),
    "Globex": ("Junior Developer", "2015"),
}
