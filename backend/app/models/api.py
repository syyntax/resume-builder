"""Request and response bodies for the HTTP API. JSON uses camelCase."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from pydantic.alias_generators import to_camel

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


class AdminUserPatchIn(CamelModel):
    role: Literal["user", "admin"] | None = None
    status: Literal["active", "disabled"] | None = None


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


class VersionMeta(CamelModel):
    id: str
    version_number: int
    sha256: str
    created_at: datetime
    summary: MasterSummary
    warnings: list[IssueOut]


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
