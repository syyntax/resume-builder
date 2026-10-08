"""ORM tables. See DESIGN.md §7.5. Every table holding user content carries an indexed ``owner_id``."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.types import JSONType, UTCDateTime, utcnow
from app.ids import new_id

# ---- identity & administration ---------------------------------------------------------------


class User(Base):
    __tablename__ = "user"
    __table_args__ = (
        CheckConstraint("role IN ('user', 'admin')", name="role"),
        CheckConstraint("status IN ('active', 'disabled')", name="status"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("usr"))
    email: Mapped[str] = mapped_column(String(254), unique=True)
    display_name: Mapped[str] = mapped_column(String(100))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), default="user")
    status: Mapped[str] = mapped_column(String(16), default="active")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    # Monthly AI spending caps in estimated USD; NULL means the deployment default, 0 means unlimited.
    monthly_cap_usd: Mapped[float | None] = mapped_column(Float, nullable=True)  # own key, set by the user
    shared_cap_usd: Mapped[float | None] = mapped_column(Float, nullable=True)  # shared key, set by an admin
    preferred_model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Set once the address is confirmed by an emailed link (only asked for when SMTP is configured)
    email_verified_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    # TOTP (DESIGN.md §8.2): the secret encrypted like API keys; it exists before mfa_enabled while being set up
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    totp_ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    totp_nonce: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    totp_key_fingerprint: Mapped[str | None] = mapped_column(String(16), nullable=True)
    totp_last_step: Mapped[int | None] = mapped_column(Integer, nullable=True)  # the last code used: no replay
    # Defaults for new applications and the export file name pattern (models.api.Preferences)
    preferences: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)


class RecoveryCode(Base):
    """Single-use MFA recovery codes, stored hashed."""

    __tablename__ = "recovery_code"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("rec"))
    user_id: Mapped[str] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), index=True)
    code_hash: Mapped[str] = mapped_column(String(64))
    used_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class UserApiKey(Base):
    """A user's own Anthropic API key, encrypted (app.secrets). Never returned to clients."""

    __tablename__ = "user_api_key"
    __table_args__ = (CheckConstraint("status IN ('valid', 'invalid')", name="status"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("key"))
    user_id: Mapped[str] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), unique=True)
    provider: Mapped[str] = mapped_column(String(20), default="anthropic")
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary)
    nonce: Mapped[bytes] = mapped_column(LargeBinary)
    key_fingerprint: Mapped[str] = mapped_column(String(16))
    hint: Mapped[str] = mapped_column(String(8))
    status: Mapped[str] = mapped_column(String(10), default="valid")
    verified_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class UserSession(Base):
    __tablename__ = "session"
    __table_args__ = (CheckConstraint("stage IN ('active', 'mfa', 'enroll')", name="stage"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("ses"))
    user_id: Mapped[str] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    csrf_token: Mapped[str] = mapped_column(String(64))
    remember: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    idle_expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    absolute_expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(300), nullable=True)
    # active · mfa: the password was right, the code is next (expires in minutes) · enroll: MFA is required and
    # must be set up before anything else
    stage: Mapped[str] = mapped_column(String(8), default="active", server_default="active")


class AuthToken(Base):
    """Single-use tokens for first-run setup, invites and password resets. Only the hash is stored."""

    __tablename__ = "auth_token"
    __table_args__ = (
        CheckConstraint("purpose IN ('setup', 'invite', 'password_reset', 'email_verify')", name="purpose"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("tok"))
    purpose: Mapped[str] = mapped_column(String(20), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    user_id: Mapped[str | None] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"), nullable=True, index=True
    )
    email: Mapped[str | None] = mapped_column(String(254), nullable=True)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    used_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class AuditLog(Base):
    """Security events only. Never document content or secrets."""

    __tablename__ = "audit_log"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("aud"))
    actor_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("user.id", ondelete="SET NULL"), nullable=True, index=True
    )
    target_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("user.id", ondelete="SET NULL"), nullable=True, index=True
    )
    event: Mapped[str] = mapped_column(String(64), index=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(300), nullable=True)
    details: Mapped[dict[str, Any]] = mapped_column("metadata", JSONType, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True)


class SystemSetting(Base):
    __tablename__ = "system_setting"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[Any] = mapped_column(JSONType)
    updated_by: Mapped[str | None] = mapped_column(ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


# ---- content (owner-scoped) ------------------------------------------------------------------


class MasterResume(Base):
    __tablename__ = "master_resume"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("mst"))
    owner_id: Mapped[str] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), index=True)
    label: Mapped[str] = mapped_column(String(100))
    current_version_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class MasterResumeVersion(Base):
    """An immutable snapshot of a master résumé. Applications point at a version, never at the master."""

    __tablename__ = "master_resume_version"
    __table_args__ = (UniqueConstraint("master_id", "version_number", name="uq_master_version_number"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("mstv"))
    master_id: Mapped[str] = mapped_column(ForeignKey("master_resume.id", ondelete="CASCADE"), index=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), index=True)
    version_number: Mapped[int] = mapped_column(Integer)
    content: Mapped[dict[str, Any]] = mapped_column(JSONType)
    sha256: Mapped[str] = mapped_column(String(64))
    schema_version: Mapped[str] = mapped_column(String(10))
    warnings: Mapped[list[dict[str, str]]] = mapped_column(JSONType, default=list)
    # The résumé file this version was imported from (IMP-8); the user can delete the file and keep the version.
    source_file_id: Mapped[str | None] = mapped_column(
        ForeignKey("uploaded_file.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class UploadedFile(Base):
    """An uploaded résumé. The bytes live under DATA_DIR/uploads (see `app.importers.storage`)."""

    __tablename__ = "uploaded_file"
    __table_args__ = (CheckConstraint("kind IN ('pdf', 'docx')", name="kind"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("fil"))
    owner_id: Mapped[str] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(8))
    original_name: Mapped[str] = mapped_column(String(255))
    size: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    storage_key: Mapped[str] = mapped_column(String(120), unique=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class ImportJob(Base):
    """One résumé import: the upload (or pasted text), what was extracted, the AI draft and the review."""

    __tablename__ = "import_job"
    __table_args__ = (
        CheckConstraint("status IN ('queued', 'transcribing', 'checking', 'ready', 'failed', 'accepted')",
                        name="status"),
        CheckConstraint("source_kind IN ('pdf', 'docx', 'text')", name="source_kind"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("imp"))
    owner_id: Mapped[str] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), index=True)
    file_id: Mapped[str | None] = mapped_column(ForeignKey("uploaded_file.id", ondelete="SET NULL"), nullable=True)
    source_kind: Mapped[str] = mapped_column(String(8))
    source_name: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(16), default="queued")
    error: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    model: Mapped[str] = mapped_column(String(64))
    extraction: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)  # text, pages, html (DOCX)
    draft: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)  # normalized master
    flags: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list)
    fidelity: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    review: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)  # {document, resolved}
    result_master_id: Mapped[str | None] = mapped_column(
        ForeignKey("master_resume.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class JobPosting(Base):
    __tablename__ = "job_posting"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("job"))
    owner_id: Mapped[str] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), index=True)
    company: Mapped[str | None] = mapped_column(String(200), nullable=True)
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    raw_text: Mapped[str] = mapped_column(Text)
    analysis: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    analysis_edited: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class Application(Base):
    """One job: a posting, the master version it was tailored from, and its documents."""

    __tablename__ = "application"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'analyzing', 'review', 'tailoring', 'validating', 'writing', 'auditing', 'done', "
            "'failed')", name="status"
        ),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("apl"))
    owner_id: Mapped[str] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), index=True)
    master_version_id: Mapped[str] = mapped_column(ForeignKey("master_resume_version.id", ondelete="CASCADE"))
    job_id: Mapped[str] = mapped_column(ForeignKey("job_posting.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(16), default="queued")
    error: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    options: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    model: Mapped[str] = mapped_column(String(64))
    template: Mapped[str] = mapped_column(String(32), default="meridian")
    theme: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    coverage_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class Document(Base):
    __tablename__ = "document"
    __table_args__ = (
        UniqueConstraint("application_id", "kind", name="uq_document_application_kind"),
        CheckConstraint("kind IN ('resume', 'cover_letter')", name="kind"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("doc"))
    owner_id: Mapped[str] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), index=True)
    application_id: Mapped[str] = mapped_column(ForeignKey("application.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    options: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    ai_draft: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    current: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    # The cover letter is generated separately and can fail on its own: generating | ready | failed
    status: Mapped[str] = mapped_column(String(16), default="ready", server_default="ready")
    error: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class DocumentRevision(Base):
    """What a document (and the design) looked like before an automatic change such as fit to page, to undo it."""

    __tablename__ = "document_revision"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("rev"))
    owner_id: Mapped[str] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), index=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("document.id", ondelete="CASCADE"), index=True)
    content: Mapped[dict[str, Any]] = mapped_column(JSONType)
    design: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)  # {template, theme}
    reason: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class AiCall(Base):
    """Usage ledger for every model call. Kept when an application is deleted so spending caps hold."""

    __tablename__ = "ai_call"
    __table_args__ = (Index("ix_ai_call_owner_created", "owner_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("aic"))
    owner_id: Mapped[str] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"))
    application_id: Mapped[str | None] = mapped_column(
        ForeignKey("application.id", ondelete="SET NULL"), nullable=True, index=True
    )
    import_job_id: Mapped[str | None] = mapped_column(
        ForeignKey("import_job.id", ondelete="SET NULL"), nullable=True, index=True
    )
    stage: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(64))
    key_source: Mapped[str] = mapped_column(String(8))
    prompt_version: Mapped[str] = mapped_column(String(32))
    request_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_read_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_write_tokens: Mapped[int] = mapped_column(Integer, default=0)
    stop_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    est_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    error: Mapped[str | None] = mapped_column(String(300), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
