"""Request and response bodies for the HTTP API. JSON uses camelCase."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from pydantic.alias_generators import to_camel

from app.render.theme import Theme

Email = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=254)]
Password = Annotated[str, StringConstraints(min_length=1, max_length=1024)]
DisplayName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Token = Annotated[str, StringConstraints(strip_whitespace=True, min_length=10, max_length=200)]


class CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


# ---- auth ----------------------------------------------------------------------------------------


class UserOut(CamelModel):
    id: str
    email: str
    display_name: str
    role: Literal["user", "admin"]
    status: Literal["active", "disabled"]
    created_at: datetime
    last_login_at: datetime | None = None


class MeOut(CamelModel):
    user: UserOut
    csrf_token: str
    notices: list[str] = []


class SetupStatusOut(CamelModel):
    needs_setup: bool


class RegistrationInfoOut(CamelModel):
    needs_setup: bool
    mode: Literal["open", "invite", "closed"]
    domain_restricted: bool


class SetupIn(CamelModel):
    token: Token
    email: Email
    password: Password
    display_name: DisplayName


class RegisterIn(CamelModel):
    email: Email
    password: Password
    display_name: DisplayName
    invite_token: Token | None = None


class LoginIn(CamelModel):
    email: Email
    password: Password
    remember: bool = False


class PasswordChangeIn(CamelModel):
    current_password: Password
    new_password: Password


class PasswordResetIn(CamelModel):
    token: Token
    new_password: Password


class TokenCheckOut(CamelModel):
    valid: bool
    email: str | None = None


class SessionOut(CamelModel):
    id: str
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime
    ip: str | None
    user_agent: str | None
    current: bool


# ---- account -------------------------------------------------------------------------------------


class ProfileIn(CamelModel):
    display_name: DisplayName | None = None
    email: Email | None = None
    current_password: Password | None = Field(default=None, description="Required to change the email.")


class DeleteAccountIn(CamelModel):
    password: Password


# ---- admin ---------------------------------------------------------------------------------------


class InviteCreateIn(CamelModel):
    email: Email | None = None


class InviteOut(CamelModel):
    id: str
    email: str | None
    created_at: datetime
    expires_at: datetime
    created_by: str | None
    url: str | None = Field(default=None, description="Only returned when the invite is created.")


class LinkOut(CamelModel):
    url: str
    expires_at: datetime


class SystemSettingsOut(CamelModel):
    registration_mode: Literal["open", "invite", "closed"]
    registration_email_domains: list[str]
    open_registration_exposed: bool


class SystemSettingsIn(CamelModel):
    registration_mode: Literal["open", "invite", "closed"] | None = None
    registration_email_domains: Annotated[
        list[Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=253)]],
        Field(max_length=50),
    ] | None = None


class AuditEntryOut(CamelModel):
    id: str
    event: str
    actor_email: str | None
    target_email: str | None
    ip: str | None
    user_agent: str | None
    details: dict[str, Any]
    created_at: datetime


# ---- master résumés --------------------------------------------------------------------------------


class IssueOut(CamelModel):
    path: str
    message: str


class MasterSummary(CamelModel):
    name: str | None
    label: str | None
    counts: dict[str, int]


class ValidationOut(CamelModel):
    valid: bool
    errors: list[IssueOut]
    warnings: list[IssueOut]
    summary: MasterSummary | None = None
    normalized: dict[str, Any] | None = None


class SourceFileOut(CamelModel):
    id: str
    name: str
    kind: Literal["pdf", "docx"]
    size: int


class VersionMeta(CamelModel):
    id: str
    version_number: int
    sha256: str
    created_at: datetime
    summary: MasterSummary
    warnings: list[IssueOut]
    source_file: SourceFileOut | None = Field(default=None,
                                              description="The résumé file this version was imported from.")


class VersionOut(VersionMeta):
    content: dict[str, Any]


class MasterOut(CamelModel):
    id: str
    label: str
    created_at: datetime
    updated_at: datetime
    version_count: int
    current_version: VersionMeta | None


class MasterDetailOut(MasterOut):
    content: dict[str, Any] | None


class MasterSaveOut(CamelModel):
    master: MasterOut
    version: VersionMeta
    created_new_version: bool
    changes: dict[str, Any] | None = None


class MasterPatchIn(CamelModel):
    label: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


# ---- AI keys, settings and usage (DESIGN.md §4.2) ------------------------------------------------------


class ApiKeyStatusOut(CamelModel):
    has_key: bool
    hint: str | None = None
    status: Literal["valid", "invalid"] | None = None
    verified_at: datetime | None = None
    last_used_at: datetime | None = None
    shared_key_available: bool = False
    using: Literal["own", "shared"] | None = Field(default=None, description="Which key AI calls will use.")


class ApiKeyIn(CamelModel):
    api_key: Annotated[str, StringConstraints(strip_whitespace=True, min_length=10, max_length=400)]
    password: Password


class PasswordConfirmIn(CamelModel):
    password: Password


class AiSettingsOut(CamelModel):
    model: str
    allowed_models: list[str]
    default_model: str
    monthly_cap_usd: float | None = Field(description="Your cap for your own key; null means the default.")
    default_cap_usd: float


class AiSettingsIn(CamelModel):
    model: str | None = None
    monthly_cap_usd: Annotated[float, Field(ge=0, le=100_000)] | None = None
    reset_cap: bool = False


class SpendOut(CamelModel):
    spent_usd: float
    cap_usd: float | None
    percent: float | None


class StageUsageOut(CamelModel):
    stage: str
    calls: int
    input_tokens: int
    output_tokens: int
    cost_usd: float


class UsageOut(CamelModel):
    month: str
    own: SpendOut
    shared: SpendOut | None
    by_stage: list[StageUsageOut]


# ---- imports (DESIGN.md §10) --------------------------------------------------------------------------

ImportStatus = Literal["queued", "transcribing", "checking", "ready", "failed", "accepted"]


class ImportTextIn(CamelModel):
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=100, max_length=50_000)]
    name: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] | None = None


class ImportOut(CamelModel):
    id: str
    status: ImportStatus
    error: dict[str, Any] | None
    source_kind: Literal["pdf", "docx", "text"]
    source_name: str
    model: str
    result_master_id: str | None
    created_at: datetime
    updated_at: datetime


class ImportFlagOut(CamelModel):
    key: str
    kind: Literal["note", "fidelity", "inferredSkill"]
    severity: Literal["info", "warning"]
    message: str
    path: str | None = None
    target_id: str | None = None
    field: str | None = None
    score: float | None = None
    skill: dict[str, str] | None = Field(default=None, description="For inferredSkill flags: name, category, evidence.")


class FidelityOut(CamelModel):
    available: bool
    threshold: float
    checked: int
    passed: int
    score: float | None


class ImportDetailOut(ImportOut):
    pages: int | None
    has_text_layer: bool
    draft: dict[str, Any] | None = Field(description="The transcription as first converted (for reverting).")
    document: dict[str, Any] | None = Field(description="The document under review: the draft plus saved edits.")
    flags: list[ImportFlagOut]
    resolved: dict[str, Literal["accepted", "dismissed"]]
    fidelity: FidelityOut | None
    cost_usd: float


class ImportPreviewOut(CamelModel):
    kind: Literal["pdf", "docx", "text"]
    html: str | None = Field(description="Sanitized HTML of a Word file.")
    text: str | None = Field(description="Pasted text, or the text extracted from the file.")
    pages: int | None


Resolution = Literal["accepted", "dismissed"]


class ImportReviewIn(CamelModel):
    document: dict[str, Any]
    resolved: Annotated[dict[Annotated[str, StringConstraints(max_length=200)], Resolution],
                        Field(max_length=2000)] = {}


class ImportReviewOut(CamelModel):
    updated_at: datetime


class ImportAcceptIn(CamelModel):
    label: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    document: dict[str, Any]


# ---- applications -----------------------------------------------------------------------------------


class JobIn(CamelModel):
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=40, max_length=50_000)]
    company: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] | None = None
    title: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] | None = None
    url: Annotated[str, StringConstraints(strip_whitespace=True, max_length=2048)] | None = None


class GenerationOptions(CamelModel):
    page_limit: Literal[1, 2, "auto"] | None = None
    tone: Literal["neutral", "confident", "conservative"] | None = None
    instructions: Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)] | None = None


class ApplicationCreateIn(CamelModel):
    master_id: str
    job: JobIn
    options: GenerationOptions = GenerationOptions()


class JobRef(CamelModel):
    id: str
    company: str | None
    title: str | None
    url: str | None


class MasterRef(CamelModel):
    id: str | None
    label: str | None
    version_id: str
    version_number: int


class ApplicationOut(CamelModel):
    id: str
    status: Literal["queued", "analyzing", "tailoring", "validating", "done", "failed"]
    error: dict[str, Any] | None
    model: str
    options: dict[str, Any]
    coverage_score: float | None
    created_at: datetime
    updated_at: datetime
    job: JobRef
    master: MasterRef
    template: str
    theme: Theme


class DesignIn(CamelModel):
    template: Annotated[str, StringConstraints(max_length=32)]
    theme: Theme


class DesignOut(CamelModel):
    template: str
    theme: Theme


# ---- templates (DESIGN.md §11.2–11.4) ------------------------------------------------------------------


class TemplateOut(CamelModel):
    key: str
    label: str
    description: str
    layout: str
    ats: str
    available: bool = Field(description="False for templates that arrive in a later release.")


class OptionOut(CamelModel):
    value: str
    label: str


class ThemeOptionsOut(CamelModel):
    accents: list[OptionOut]
    fonts: list[OptionOut]
    densities: list[OptionOut]
    papers: list[OptionOut]
    margins: list[OptionOut]
    date_formats: list[OptionOut]


class TemplatesOut(CamelModel):
    templates: list[TemplateOut]
    options: ThemeOptionsOut
    default_template: str
    default_theme: Theme


class ApplicationDetailOut(ApplicationOut):
    posting: str
    analysis: dict[str, Any] | None
    resume: dict[str, Any] | None
    cost_usd: float


# ---- admin (AI) ------------------------------------------------------------------------------------------


class AdminUserOut(UserOut):
    has_api_key: bool
    shared_cap_usd: float | None


class AdminUserPatchIn(CamelModel):
    role: Literal["user", "admin"] | None = None
    status: Literal["active", "disabled"] | None = None
    shared_cap_usd: Annotated[float, Field(ge=0, le=100_000)] | None = None
    reset_shared_cap: bool = False


class AdminAiSettingsOut(CamelModel):
    shared_key_configured: bool
    allow_shared_key: bool
    default_model: str
    allowed_models: list[str]
    known_models: list[str]
    default_cap_usd: float


class UserUsageOut(CamelModel):
    user_id: str
    email: str
    display_name: str
    has_api_key: bool
    own_spend_usd: float
    shared_spend_usd: float
    calls: int
    applications: int


class AdminAiSettingsIn(CamelModel):
    allow_shared_key: bool | None = None
    default_model: Annotated[str, StringConstraints(pattern=r"^claude-[a-z0-9.\-]{1,60}$")] | None = None
    allowed_models: Annotated[
        list[Annotated[str, StringConstraints(pattern=r"^claude-[a-z0-9.\-]{1,60}$")]],
        Field(min_length=1, max_length=20),
    ] | None = None
