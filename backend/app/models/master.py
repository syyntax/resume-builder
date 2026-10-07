"""The master résumé schema (DESIGN.md §7.1): a superset of JSON Resume v1.

These models describe the *input* format, so they're deliberately forgiving: IDs are optional (they're
assigned during normalization), bullets may be plain strings, and unknown keys are kept and reported as
warnings. ``app.masters.normalize`` turns a parsed document into its normalized form.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Annotated, Any, Literal

from pydantic import (
    AliasChoices,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Discriminator,
    Field,
    StringConstraints,
    Tag,
)
from pydantic.alias_generators import to_camel

SCHEMA_VERSION = "1.0"
ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$"

# Tags used for the "string or object" bullet union. They show up in validation error locations, so they
# are chosen to be impossible as field names and are stripped when errors are formatted.
TEXT_TAG = "~text"
OBJECT_TAG = "~object"

Short = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=5000)]
Url = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2048)]
ItemId = Annotated[
    str,
    StringConstraints(strip_whitespace=True, pattern=ID_PATTERN),
    Field(description="Unique within the document. Letters, digits, '.', '_' or '-'. Assigned if omitted."),
]
TagList = Annotated[list[Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]],
                    Field(max_length=50, description="Topics used for relevance matching, e.g. 'leadership'.")]
ShortList = Annotated[list[Short], Field(max_length=100)]

_DATE_RE = re.compile(r"^(\d{4})(?:-(\d{1,2})(?:-(\d{1,2}))?)?$")
_PRESENT = frozenset({"present", "current", "now", "ongoing"})


def _parse_date(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, int) and not isinstance(value, bool) and 1900 <= value <= 2200:
        return str(value)
    if not isinstance(value, str):
        raise ValueError(f"expected a date string like YYYY-MM, got {value!r}")
    text = value.strip()
    match = _DATE_RE.match(text)
    if not match:
        raise ValueError(f'expected YYYY, YYYY-MM, or YYYY-MM-DD, got "{value}"')
    year, month, day = match.groups()
    if month is None:
        return year
    if not 1 <= int(month) <= 12:
        raise ValueError(f'month must be 01-12, got "{value}"')
    if day is None:
        return f"{year}-{int(month):02d}"
    try:
        date(int(year), int(month), int(day))
    except ValueError:
        raise ValueError(f'not a real date: "{value}"') from None
    return f"{year}-{int(month):02d}-{int(day):02d}"


def _parse_end_date(value: Any) -> Any:
    if isinstance(value, str) and value.strip().lower() in _PRESENT:
        return None
    return _parse_date(value)


_DATE_DOC = "YYYY, YYYY-MM, or YYYY-MM-DD"
PartialDate = Annotated[
    str, BeforeValidator(_parse_date), Field(description=_DATE_DOC, examples=["2021-03"])
]
EndDate = Annotated[
    str | None,
    BeforeValidator(_parse_end_date),
    Field(description=f"{_DATE_DOC}. Omit, or use null or \"present\", for a current role.", examples=["2023-06"]),
]


class _Base(BaseModel):
    model_config = ConfigDict(
        extra="allow", populate_by_name=True, alias_generator=to_camel, str_strip_whitespace=True
    )


class _Item(_Base):
    id: ItemId | None = None
    tags: TagList = []
    priority: Annotated[int, Field(ge=1, le=5, description="1-5; higher = prefer when relevance is similar.")] = 3
    pin: Annotated[bool, Field(description="Always include this item.")] = False
    hidden: Annotated[bool, Field(description="Never include this item (but keep it in the master).")] = False


# ---- bullets ------------------------------------------------------------------------------------


class Variant(_Base):
    """An alternative phrasing of a bullet that the AI may choose instead of the main text."""

    text: Text
    tags: TagList = []


class Highlight(_Item):
    text: Text
    skills: Annotated[ShortList, Field(description="Skill ids (or names) this bullet demonstrates.")] = []
    variants: Annotated[list[Variant], Field(max_length=10)] = []


def _highlight_kind(value: Any) -> str:
    return TEXT_TAG if isinstance(value, str) else OBJECT_TAG


HighlightEntry = Annotated[
    Annotated[Text, Tag(TEXT_TAG)] | Annotated[Highlight, Tag(OBJECT_TAG)],
    Discriminator(_highlight_kind),
]
Highlights = Annotated[
    list[HighlightEntry], Field(max_length=100, description="Bullets: plain strings or objects.")
]


# ---- sections -----------------------------------------------------------------------------------


class Meta(_Base):
    schema_version: Annotated[str, Field(pattern=r"^1\.\d+$")] = SCHEMA_VERSION
    label: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)] | None = None
    canonical: Url | None = None
    version: Short | None = None
    last_modified: Short | None = None


class Location(_Base):
    address: Short | None = None
    postal_code: Short | None = None
    city: Short | None = None
    country_code: Short | None = None
    region: Short | None = None
    remote: bool | None = None


class Profile(_Base):
    network: Short | None = None
    username: Short | None = None
    url: Url | None = None


class Basics(_Base):
    name: Short
    label: Short | None = None
    image: Url | None = None
    email: Short | None = None
    phone: Short | None = None
    url: Url | None = None
    summary: Text | None = None
    location: Location | None = None
    profiles: Annotated[list[Profile], Field(max_length=20)] = []
    work_authorization: Short | None = None


class Headline(_Item):
    text: Short


class Summary(_Item):
    text: Text


class Work(_Item):
    company: Short = Field(
        validation_alias=AliasChoices("company", "name"), serialization_alias="company",
        description="Employer. JSON Resume's 'name' is also accepted.",
    )
    position: Short
    location: Short | None = None
    url: Url | None = None
    start_date: PartialDate | None = None
    end_date: EndDate = None
    employment_type: Short | None = None
    summary: Text | None = None
    description: Text | None = None
    skills: Annotated[ShortList, Field(description="Skill ids (or names) used in this role.")] = []
    highlights: Highlights = []


class Project(_Item):
    name: Short
    description: Text | None = None
    url: Url | None = None
    start_date: PartialDate | None = None
    end_date: EndDate = None
    roles: ShortList = []
    entity: Short | None = None
    type: Short | None = None
    keywords: ShortList = []
    skills: ShortList = []
    highlights: Highlights = []


class Education(_Item):
    institution: Short
    url: Url | None = None
    area: Short | None = None
    study_type: Short | None = None
    start_date: PartialDate | None = None
    end_date: EndDate = None
    score: Short | None = None
    courses: ShortList = []
    honors: ShortList = []
    highlights: Highlights = []


class Certification(_Item):
    name: Short
    issuer: Short | None = None
    date: PartialDate | None = None
    expires: PartialDate | None = None
    url: Url | None = None
    credential_id: Short | None = None


class Skill(_Item):
    name: Short
    category: Short | None = None
    level: Annotated[Short | None, Field(description="e.g. expert, advanced, intermediate, familiar")] = None
    years: Annotated[float | None, Field(ge=0, le=80)] = None
    aliases: Annotated[ShortList, Field(description="Other names, e.g. 'K8s' for Kubernetes.")] = []
    keywords: ShortList = []


class Award(_Item):
    title: Short
    date: PartialDate | None = None
    awarder: Short | None = None
    summary: Text | None = None


class Publication(_Item):
    name: Short
    publisher: Short | None = None
    release_date: PartialDate | None = None
    url: Url | None = None
    summary: Text | None = None


class Volunteer(_Item):
    organization: Short
    position: Short | None = None
    url: Url | None = None
    start_date: PartialDate | None = None
    end_date: EndDate = None
    summary: Text | None = None
    highlights: Highlights = []


class Language(_Item):
    language: Short
    fluency: Short | None = None


class Interest(_Item):
    name: Short
    keywords: ShortList = []


class Reference(_Item):
    name: Short
    reference: Text | None = None


class CustomItem(_Item):
    title: Short
    subtitle: Short | None = None
    date: PartialDate | None = None
    start_date: PartialDate | None = None
    end_date: EndDate = None
    url: Url | None = None
    summary: Text | None = None
    highlights: Highlights = []


class CustomSection(_Item):
    title: Short
    items: Annotated[list[CustomItem], Field(max_length=100)] = []


class Preferences(_Base):
    page_limit: Literal[1, 2, "auto"] | None = None
    recent_years: Annotated[int | None, Field(ge=1, le=60)] = None
    min_bullets_per_recent_role: Annotated[int | None, Field(ge=0, le=10)] = None
    tone: Literal["neutral", "confident", "conservative"] | None = None
    spelling: Short | None = None
    show_work_authorization: bool | None = None


class MasterResume(_Base):
    """Master résumé (Resume Tailor schema 1.0, a superset of JSON Resume v1)."""

    model_config = ConfigDict(title="Resume Tailor master résumé")

    json_schema_ref: str | None = Field(default=None, alias="$schema")
    meta: Meta | None = None
    basics: Basics
    headlines: Annotated[list[Headline], Field(max_length=20)] = []
    summaries: Annotated[list[Summary], Field(max_length=20)] = []
    work: Annotated[list[Work], Field(max_length=100)] = []
    projects: Annotated[list[Project], Field(max_length=100)] = []
    education: Annotated[list[Education], Field(max_length=50)] = []
    certifications: Annotated[list[Certification], Field(max_length=100)] = Field(
        default=[],
        validation_alias=AliasChoices("certifications", "certificates"),
        serialization_alias="certifications",
    )
    skills: Annotated[list[Skill], Field(max_length=300)] = []
    awards: Annotated[list[Award], Field(max_length=100)] = []
    publications: Annotated[list[Publication], Field(max_length=100)] = []
    volunteer: Annotated[list[Volunteer], Field(max_length=50)] = []
    languages: Annotated[list[Language], Field(max_length=50)] = []
    interests: Annotated[list[Interest], Field(max_length=50)] = []
    references: Annotated[list[Reference], Field(max_length=50)] = []
    custom_sections: Annotated[list[CustomSection], Field(max_length=30)] = []
    preferences: Preferences | None = None


def json_schema() -> dict[str, Any]:
    schema = MasterResume.model_json_schema(by_alias=True, mode="validation")
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://resume-tailor.local/schema/master-resume.schema.json",
        **schema,
    }
