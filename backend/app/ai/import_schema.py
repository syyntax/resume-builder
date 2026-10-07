"""Stage I output: a résumé transcribed into master-résumé shape (DESIGN.md §9.4, §10.3).

Structured outputs limit how many optional and union-typed fields a schema may have, so this draft has
neither: every field is required, and an empty string or list means "not in the document". The server
converts the draft into a real master résumé (`app.importers.convert`), dropping the empty values.
"""

from __future__ import annotations

from typing import Literal

from app.ai.schemas import _Out


class ImportedLocation(_Out):
    city: str
    region: str
    country_code: str


class ImportedProfile(_Out):
    network: str
    username: str
    url: str


class ImportedBasics(_Out):
    name: str
    label: str
    email: str
    phone: str
    url: str
    location: ImportedLocation
    profiles: list[ImportedProfile]


class ImportedWork(_Out):
    company: str
    position: str
    location: str
    start_date: str
    end_date: str
    current: bool
    summary: str
    highlights: list[str]
    tags: list[str]


class ImportedProject(_Out):
    name: str
    description: str
    url: str
    start_date: str
    end_date: str
    highlights: list[str]
    tags: list[str]


class ImportedEducation(_Out):
    institution: str
    study_type: str
    area: str
    start_date: str
    end_date: str
    score: str
    courses: list[str]
    honors: list[str]
    highlights: list[str]


class ImportedCertification(_Out):
    name: str
    issuer: str
    date: str
    expires: str
    credential_id: str
    url: str


class ImportedSkill(_Out):
    name: str
    category: str
    level: str
    aliases: list[str]


class InferredSkill(_Out):
    name: str
    category: str
    evidence: str


class ImportedAward(_Out):
    title: str
    date: str
    awarder: str
    summary: str


class ImportedPublication(_Out):
    name: str
    publisher: str
    release_date: str
    url: str
    summary: str


class ImportedVolunteer(_Out):
    organization: str
    position: str
    start_date: str
    end_date: str
    summary: str
    highlights: list[str]


class ImportedLanguage(_Out):
    language: str
    fluency: str


class ImportedInterest(_Out):
    name: str
    keywords: list[str]


class ImportedCustomItem(_Out):
    title: str
    subtitle: str
    date: str
    summary: str
    highlights: list[str]


class ImportedCustomSection(_Out):
    title: str
    items: list[ImportedCustomItem]


class ImportNote(_Out):
    path: str
    severity: Literal["info", "warning"]
    message: str


class MasterImportDraft(_Out):
    basics: ImportedBasics
    headline: str
    summary: str
    work: list[ImportedWork]
    projects: list[ImportedProject]
    education: list[ImportedEducation]
    certifications: list[ImportedCertification]
    skills: list[ImportedSkill]
    inferred_skills: list[InferredSkill]
    awards: list[ImportedAward]
    publications: list[ImportedPublication]
    volunteer: list[ImportedVolunteer]
    languages: list[ImportedLanguage]
    interests: list[ImportedInterest]
    custom_sections: list[ImportedCustomSection]
    import_notes: list[ImportNote]
