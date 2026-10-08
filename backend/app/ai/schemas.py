"""Structured outputs of the AI stages (DESIGN.md §7.2, §9.1).

The same Pydantic models validate the model's JSON and are stored as-is. `strict_schema()` turns a model's
JSON Schema into what structured outputs accept: every object closed (`additionalProperties: false`) with
all properties required (optional values are nullable instead), and no unsupported keywords such as
length or numeric constraints. Structured outputs may return an enum value in a different capitalization, so
every model folds enum strings to their canonical case before validating.
"""

from __future__ import annotations

from typing import Any, Literal, get_args, get_origin

from pydantic import BaseModel, ConfigDict, model_validator
from pydantic.alias_generators import to_camel


def _fold_case(annotation: Any, value: Any) -> Any:
    if get_origin(annotation) is list and isinstance(value, list):
        (item,) = get_args(annotation)
        return [_fold_case(item, v) for v in value]
    if get_origin(annotation) is Literal and isinstance(value, str):
        for option in get_args(annotation):
            if isinstance(option, str) and option.casefold() == value.casefold():
                return option
    return value


class _Out(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="ignore")

    @model_validator(mode="before")
    @classmethod
    def _canonical_enum_case(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        data = dict(data)
        for name, field in cls.model_fields.items():
            key = field.alias if field.alias in data else name
            if key in data:
                data[key] = _fold_case(field.annotation, data[key])
        return data


# ---- stage A: job analysis -----------------------------------------------------------------------

Seniority = Literal[
    "intern", "junior", "mid", "senior", "staff", "principal", "manager", "director", "executive", "unknown"
]


class Requirement(_Out):
    id: str
    text: str
    kind: Literal["required", "preferred"]
    category: Literal["skill", "experience", "education", "certification", "soft-skill", "domain", "other"]
    keywords: list[str]


class Keyword(_Out):
    term: str
    aliases: list[str]
    importance: Literal[1, 2, 3]
    category: Literal["technology", "skill", "domain", "certification", "soft-skill", "other"]
    must_include: bool


class RequirementMatch(_Out):
    requirement_id: str
    status: Literal["met", "partial", "missing"]
    evidence_ids: list[str]
    note: str


class Fit(_Out):
    rating: Literal["strong", "moderate", "weak"]
    rationale: str


class JobAnalysis(_Out):
    company: str | None
    title: str | None
    seniority: Seniority
    location: str | None
    employment_type: str | None
    role_summary: str
    requirements: list[Requirement]
    responsibilities: list[str]
    keywords: list[Keyword]
    company_signals: list[str]
    match: list[RequirementMatch]
    fit: Fit
    suggested_emphasis: list[str]


# ---- stage B: tailoring draft ----------------------------------------------------------------------

SectionName = Literal[
    "summary", "experience", "projects", "skills", "education", "certifications", "awards", "publications",
    "volunteer", "languages", "custom",
]


class SourcedText(_Out):
    text: str
    source_ids: list[str]


class DraftBullet(_Out):
    text: str
    source_ids: list[str]
    relevance: Literal[1, 2, 3, 4, 5]
    keywords: list[str]


class DraftExperience(_Out):
    work_id: str
    bullets: list[DraftBullet]


class DraftProject(_Out):
    project_id: str
    bullets: list[DraftBullet]


class DraftSkill(_Out):
    skill_id: str
    display: str


class DraftSkillGroup(_Out):
    group: str
    skills: list[DraftSkill]


class DraftCustomSection(_Out):
    section_id: str
    item_ids: list[str]


class DraftInclude(_Out):
    education: list[str]
    certifications: list[str]
    awards: list[str]
    publications: list[str]
    volunteer: list[str]
    languages: list[str]
    custom_sections: list[DraftCustomSection]


class DraftNote(_Out):
    type: Literal["gap", "suggestion"]
    text: str


class TailorDraft(_Out):
    headline: SourcedText
    summary: SourcedText
    section_order: list[SectionName]
    experience: list[DraftExperience]
    earlier_experience_ids: list[str]
    projects: list[DraftProject]
    skills: list[DraftSkillGroup]
    include: DraftInclude
    notes: list[DraftNote]


# ---- stage C: cover letter --------------------------------------------------------------------------

ParagraphRole = Literal["opening", "evidence", "motivation", "closing"]
CompanySource = Literal["posting", "notes"]


class LetterParagraph(_Out):
    role: ParagraphRole
    text: str
    source_ids: list[str]  # master items and bullets the paragraph draws on
    job_refs: list[str]  # requirement ids from the analysis (r1, r2, …)
    company_sources: list[CompanySource]  # where statements about the company come from (G6)


class LetterHighlight(_Out):
    value: str
    label: str
    source_ids: list[str]


class LetterDraft(_Out):
    subject: str
    paragraphs: list[LetterParagraph]
    highlights: list[LetterHighlight]
    notes: list[DraftNote]


# ---- stage R: refine -----------------------------------------------------------------------------------


class RefinedBullet(_Out):
    target_id: str  # the bullet rewritten; "" for a new bullet in a regenerated item
    text: str
    source_ids: list[str]
    keywords: list[str]


class RefinedItem(_Out):
    item_id: str  # a role or project whose bullets were regenerated
    bullets: list[RefinedBullet]


class RefineDraft(_Out):
    headline: SourcedText  # empty text: unchanged
    summary: SourcedText  # empty text: unchanged
    bullets: list[RefinedBullet]
    items: list[RefinedItem]
    notes: list[DraftNote]


class RefinedParagraph(_Out):
    target_id: str  # the paragraph rewritten; "" for a new one
    role: ParagraphRole
    text: str
    source_ids: list[str]
    job_refs: list[str]
    company_sources: list[CompanySource]


class LetterRefineDraft(_Out):
    paragraphs: list[RefinedParagraph]
    notes: list[DraftNote]


# ---- stage D: claim audit -------------------------------------------------------------------------------


class ClaimVerdict(_Out):
    claim_id: str
    verdict: Literal["supported", "embellished", "unsupported"]
    reason: str


class AuditResult(_Out):
    verdicts: list[ClaimVerdict]


# ---- schema conversion ---------------------------------------------------------------------------------

_UNSUPPORTED = frozenset({
    "title", "default", "examples", "minLength", "maxLength", "pattern", "minimum", "maximum",
    "exclusiveMinimum", "exclusiveMaximum", "multipleOf", "minItems", "maxItems", "uniqueItems",
})


# Keywords whose values map names to subschemas: the names are fields or definitions (e.g. a field called
# "title"), never keywords, so they must not be filtered.
_NAMED_SUBSCHEMAS = frozenset({"properties", "$defs", "definitions"})


def _strict(node: Any) -> Any:
    if isinstance(node, list):
        return [_strict(n) for n in node]
    if not isinstance(node, dict):
        return node
    out: dict[str, Any] = {}
    for key, value in node.items():
        if key in _NAMED_SUBSCHEMAS and isinstance(value, dict):
            out[key] = {name: _strict(sub) for name, sub in value.items()}
        elif key not in _UNSUPPORTED:
            out[key] = _strict(value)
    if out.get("type") == "object" or "properties" in out:
        out["additionalProperties"] = False
        out["required"] = list(out.get("properties", {}))
    return out


def strict_schema(model: type[BaseModel]) -> dict[str, Any]:
    return _strict(model.model_json_schema(by_alias=True, mode="validation"))
