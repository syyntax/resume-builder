"""Runs an application (DESIGN.md §9.1): analyze → [review] → tailor → hydrate → validate → letter → audit.

Phases:
- ``full``: from the posting. With ``options.reviewAnalysis`` it stops after the analysis (status
  ``review``) so the candidate can edit it (JOB-4, JOB-5); ``continue`` then runs the ``tailor`` phase.
- ``tailor``: from the stored (possibly edited) analysis: résumé, then letter and audit. Also used to
  regenerate.

The cover letter (stage C) and the claim audit (stage D) never fail the application: the résumé is
delivered, and the letter or audit shows its own error and can be retried (DESIGN.md §9.7). Both can also
run on their own: ``run_letter`` and ``run_audit``.
"""

from __future__ import annotations

import copy
import logging
from typing import Any, Literal

from fastapi import FastAPI
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import stages
from app.ai.llm import LLMError
from app.ai.schemas import JobAnalysis
from app.config import Settings
from app.db.models import Application, Document, JobPosting, MasterResume, MasterResumeVersion, User
from app.db.types import utcnow
from app.errors import ApiError
from app.keys import service as keys
from app.pipeline import usage
from app.pipeline.audit import letter_claims, resume_claims, store_results
from app.pipeline.editing import annotate_resume
from app.pipeline.hydrate import MasterIndex, hydrate
from app.pipeline.letter import annotate_letter, build_letter

log = logging.getLogger("resume_tailor.pipeline")
ACTIVE = ("queued", "analyzing", "tailoring", "validating", "writing", "auditing")
Phase = Literal["full", "tailor"]


def _publish(app: FastAPI, application: Application, event: dict[str, Any]) -> None:
    app.state.events.publish(application.id, event)


async def _set_status(app: FastAPI, db: AsyncSession, application: Application, status: str) -> None:
    application.status, application.updated_at = status, utcnow()
    await db.commit()
    _publish(app, application, {"type": "status", "status": status})


async def _fail(app: FastAPI, db: AsyncSession, application_id: str, code: str, message: str) -> None:
    await db.rollback()  # drop anything half-done; then reload, since rollback expires loaded objects
    application = await db.get(Application, application_id, populate_existing=True)
    if application is None:  # deleted while running
        return
    application.status, application.updated_at = "failed", utcnow()
    application.error = {"code": code, "message": message}
    await db.commit()
    app.state.events.publish(application_id, {"type": "error", "code": code, "message": message})


class Context:
    """What every stage of one run needs, loaded once."""

    def __init__(self, app: FastAPI, db: AsyncSession, application: Application, user: User, job: JobPosting,
                 version: MasterResumeVersion) -> None:
        self.app, self.db, self.application = app, db, application
        self.user, self.job, self.version = user, job, version
        self.settings: Settings = app.state.settings
        self.master: dict[str, Any] = version.content
        self.key: keys.ResolvedKey | None = None

    async def llm(self) -> Any:
        if self.key is None:
            self.key = await keys.resolve(self.db, self.user, self.settings)
        return self.app.state.llm_factory(self.key.api_key)

    async def call[T](self, stage: str, runner: Any) -> stages.StageResult[T]:
        """Run one model call, recording its usage whether it succeeds or fails after being billed."""
        assert self.key is not None  # noqa: S101  (llm() runs first)
        try:
            result: stages.StageResult[T] = await runner()
        except LLMError as error:
            await usage.record_call(self.db, owner_id=self.user.id, application_id=self.application.id, stage=stage,
                                    model=self.application.model, key_source=self.key.source,
                                    prompt_version=f"{stage}@?", settings=self.settings, error=error)
            if error.code == "key_rejected" and self.key.row is not None:
                self.key.row.status = "invalid"
            await self.db.commit()
            raise
        await usage.record_call(self.db, owner_id=self.user.id, application_id=self.application.id, stage=stage,
                                model=self.application.model, key_source=self.key.source,
                                prompt_version=result.prompt_version, settings=self.settings, result=result.call)
        if self.key.row is not None:
            self.key.row.last_used_at = utcnow()
        await self.db.commit()
        return result

    async def ensure_cap(self, *stage_names: str) -> None:
        assert self.key is not None  # noqa: S101
        estimate = usage.estimate_job_cost(self.application.model, self.settings, stages=stage_names)
        await usage.ensure_within_cap(self.db, self.user, self.key.source, self.settings, estimate)

    def analysis(self) -> JobAnalysis:
        return JobAnalysis.model_validate(self.job.analysis)

    async def document(self, kind: str) -> Document | None:
        return (await self.db.execute(select(Document).where(
            Document.application_id == self.application.id, Document.kind == kind))).scalar_one_or_none()

    def meta(self, prompt_version: str) -> dict[str, Any]:
        return {
            "schemaVersion": "1.0", "applicationId": self.application.id, "generatedAt": utcnow().isoformat(),
            "model": self.application.model, "promptVersion": prompt_version,
            "master": {"id": self.version.master_id, "versionId": self.version.id, "sha256": self.version.sha256},
            "job": {"company": self.job.company, "title": self.job.title, "url": self.job.url},
            "template": self.application.template, "theme": self.application.theme,
        }


async def _load(app: FastAPI, db: AsyncSession, application_id: str) -> Context | None:
    application = await db.get(Application, application_id)
    if application is None:
        return None
    user = await db.get(User, application.owner_id)
    job = await db.get(JobPosting, application.job_id)
    version = await db.get(MasterResumeVersion, application.master_version_id)
    if user is None or job is None or version is None:
        return None
    return Context(app, db, application, user, job, version)


async def run_application(app: FastAPI, application_id: str, phase: Phase = "full") -> None:
    async with app.state.sessionmaker() as db:
        ctx = await _load(app, db, application_id)
        if ctx is None or ctx.application.status not in ACTIVE:
            return
        try:
            if phase == "full":
                await _analyze(ctx)
                if (ctx.application.options or {}).get("reviewAnalysis"):
                    await _set_status(app, db, ctx.application, "review")
                    _publish(app, ctx.application, {"type": "review"})
                    return
            await _tailor(ctx)
            letter_options = (ctx.application.options or {}).get("coverLetter") or {}
            if letter_options.get("generate"):
                await _set_status(app, db, ctx.application, "writing")
                await _write_letter(ctx, letter_options)
            if ctx.settings.ai_claim_audit:
                await _set_status(app, db, ctx.application, "auditing")
                await _audit(ctx, resume=True, letter=True)
            ctx.application.error = None
            await _set_status(app, db, ctx.application, "done")
            _publish(app, ctx.application, {"type": "done"})
        except ApiError as exc:  # no usable key, spending cap
            await _fail(app, db, application_id, (exc.extra or {}).get("code", "error"), exc.detail)
        except LLMError as exc:
            await _fail(app, db, application_id, exc.code, exc.message)
        except Exception:
            log.exception("application %s failed", application_id)
            await _fail(app, db, application_id, "internal_error",
                        "Something went wrong on our side. Retry, and check the server log if it keeps failing.")


async def _analyze(ctx: Context) -> None:
    llm = await ctx.llm()
    await _set_status(ctx.app, ctx.db, ctx.application, "analyzing")
    await ctx.ensure_cap("analyze", "tailor")
    analyzed = await ctx.call("analyze", lambda: stages.analyze(
        llm, model=ctx.application.model, effort=ctx.settings.ai_effort_analyze, master=ctx.master,
        version_id=ctx.version.id, posting=ctx.job.raw_text))
    ctx.job.analysis = analyzed.value.model_dump(mode="json", by_alias=True)
    ctx.job.analysis_edited = False
    ctx.job.company = ctx.job.company or analyzed.value.company
    ctx.job.title = ctx.job.title or analyzed.value.title
    await ctx.db.commit()
    _publish(ctx.app, ctx.application, {"type": "analysis"})


async def _tailor(ctx: Context) -> None:
    llm = await ctx.llm()
    analysis = ctx.analysis()
    await _set_status(ctx.app, ctx.db, ctx.application, "tailoring")
    await ctx.ensure_cap("tailor")

    def tailor(repair: list[str] | None = None):  # noqa: ANN202
        return lambda: stages.tailor(llm, model=ctx.application.model, effort=ctx.settings.ai_effort_tailor,
                                     master=ctx.master, version_id=ctx.version.id, posting=ctx.job.raw_text,
                                     analysis=analysis, options=ctx.application.options, repair=repair)

    drafted = await ctx.call("tailor", tailor())
    await _set_status(ctx.app, ctx.db, ctx.application, "validating")
    hydrated = hydrate(drafted.value, ctx.master)
    if hydrated.problems:
        await _set_status(ctx.app, ctx.db, ctx.application, "tailoring")
        drafted = await ctx.call("tailor_repair", tailor(hydrated.problems))
        await _set_status(ctx.app, ctx.db, ctx.application, "validating")
        hydrated = hydrate(drafted.value, ctx.master)
    for problem in hydrated.problems:  # still unresolved after the repair: those parts were dropped
        hydrated.notices.append({"targetId": "draft", "code": "REFERENCE_DROPPED", "message": problem})

    resume = {"meta": ctx.meta(drafted.prompt_version), **hydrated.resume,
              "analysis": {"notices": hydrated.notices, "notes": [n.model_dump(by_alias=True)
                                                                  for n in drafted.value.notes]}}
    annotate_resume(resume, ctx.master, analysis)
    document = await ctx.document("resume")
    if document is None:
        document = Document(owner_id=ctx.user.id, application_id=ctx.application.id, kind="resume")
        ctx.db.add(document)
    document.ai_draft = drafted.value.model_dump(mode="json", by_alias=True)
    document.current, document.status, document.error = resume, "ready", None
    document.updated_at = utcnow()
    ctx.application.coverage_score = resume["analysis"]["coverage"]["score"]
    await ctx.db.commit()
    _publish(ctx.app, ctx.application, {"type": "resume"})


async def _write_letter(ctx: Context, options: dict[str, Any]) -> None:
    """Stage C. A failure is recorded on the letter document; the application carries on."""
    document = await ctx.document("cover_letter")
    if document is None:
        document = Document(owner_id=ctx.user.id, application_id=ctx.application.id, kind="cover_letter")
        ctx.db.add(document)
    document.status, document.error, document.options, document.updated_at = "generating", None, options, utcnow()
    await ctx.db.commit()
    try:
        llm = await ctx.llm()
        await ctx.ensure_cap("letter")
        resume_doc = await ctx.document("resume")
        resume = resume_doc.current if resume_doc and resume_doc.current else None
        prefs = ctx.master.get("preferences") or {}
        drafted = await ctx.call("letter", lambda: stages.letter(
            llm, model=ctx.application.model, effort=ctx.settings.ai_effort_letter, master=ctx.master,
            version_id=ctx.version.id, posting=ctx.job.raw_text, analysis=ctx.analysis(), resume=resume or {},
            options=options, spelling=prefs.get("spelling") or "en-US"))
        letter = build_letter(drafted.value, master=ctx.master, resume=resume, analysis=ctx.analysis(),
                              options=options, job_company=ctx.job.company, meta=ctx.meta(drafted.prompt_version))
        annotate_letter(letter, ctx.master, ctx.analysis(), ctx.job.raw_text)
        document = await ctx.document("cover_letter")  # reload: the call above committed
        assert document is not None  # noqa: S101
        document.ai_draft = drafted.value.model_dump(mode="json", by_alias=True)
        document.current, document.status, document.error, document.updated_at = letter, "ready", None, utcnow()
        await ctx.db.commit()
        _publish(ctx.app, ctx.application, {"type": "letter", "status": "ready"})
    except (LLMError, ApiError) as exc:
        code = exc.code if isinstance(exc, LLMError) else (exc.extra or {}).get("code", "error")
        message = exc.message if isinstance(exc, LLMError) else exc.detail
        await ctx.db.rollback()
        document = await ctx.document("cover_letter")
        if document is not None:
            document.status, document.error = "failed", {"code": code, "message": message}
            document.updated_at = utcnow()
            await ctx.db.commit()
        _publish(ctx.app, ctx.application, {"type": "letter", "status": "failed"})


async def _audit(ctx: Context, *, resume: bool, letter: bool) -> None:
    """Stage D over the résumé and/or the letter. Never fatal: a failure leaves an "unavailable" note."""
    index = MasterIndex.build(ctx.master)
    resume_doc = await ctx.document("resume") if resume else None
    letter_doc = await ctx.document("cover_letter") if letter else None
    if letter_doc is not None and (letter_doc.status != "ready" or not letter_doc.current):
        letter_doc = None
    parts: list[tuple[Document, list[dict[str, Any]]]] = []
    if resume_doc is not None and resume_doc.current:
        parts.append((resume_doc, resume_claims(resume_doc.current, index)))
    if letter_doc is not None:
        parts.append((letter_doc, letter_claims(letter_doc.current or {}, index, ctx.job.raw_text)))
    claims = [c for _, cs in parts for c in cs]
    if not claims:
        return
    result, error = None, None
    try:
        llm = await ctx.llm()
        await ctx.ensure_cap("audit")
        result = (await ctx.call("audit", lambda: stages.audit(
            llm, model=ctx.application.model, effort=ctx.settings.ai_effort_audit, claims=claims))).value
    except (LLMError, ApiError) as exc:
        error = exc.message if isinstance(exc, LLMError) else exc.detail
        await ctx.db.rollback()
    analysis = ctx.analysis()
    for document, doc_claims in parts:
        document = await ctx.db.get(Document, document.id, populate_existing=True) or document
        # A deep copy: changing the stored JSON in place would make SQLAlchemy see "no change" and skip the write.
        current = copy.deepcopy(document.current or {})
        store_results(current, doc_claims, result, error=error)
        if document.kind == "resume":
            annotate_resume(current, ctx.master, analysis)
        else:
            annotate_letter(current, ctx.master, analysis, ctx.job.raw_text)
        document.current, document.updated_at = current, utcnow()
    await ctx.db.commit()
    _publish(ctx.app, ctx.application, {"type": "audit", "status": "done" if result else "unavailable"})


# ---- on-demand jobs (the application itself stays "done") ---------------------------------------------------


async def run_letter(app: FastAPI, application_id: str, options: dict[str, Any]) -> None:
    async with app.state.sessionmaker() as db:
        ctx = await _load(app, db, application_id)
        if ctx is None:
            return
        try:
            await _write_letter(ctx, options)
            letter_doc = await ctx.document("cover_letter")
            if ctx.settings.ai_claim_audit and letter_doc is not None and letter_doc.status == "ready":
                await _audit(ctx, resume=False, letter=True)
        except Exception:
            log.exception("cover letter for %s failed", application_id)
            await db.rollback()
            document = await ctx.document("cover_letter")
            if document is not None and document.status == "generating":
                document.status = "failed"
                document.error = {"code": "internal_error", "message": "Something went wrong on our side. Retry."}
                await db.commit()


async def run_audit(app: FastAPI, application_id: str) -> None:
    async with app.state.sessionmaker() as db:
        ctx = await _load(app, db, application_id)
        if ctx is None:
            return
        try:
            await _audit(ctx, resume=True, letter=True)
        except Exception:
            log.exception("claim audit for %s failed", application_id)


async def mark_interrupted(db: AsyncSession) -> int:
    """At startup: jobs that were running when the app stopped can't resume, so mark them failed."""
    result = await db.execute(
        update(Application).where(Application.status.in_(ACTIVE)).values(
            status="failed", updated_at=utcnow(),
            error={"code": "interrupted", "message": "The app restarted while this was running. Retry it."},
        )
    )
    letters = await db.execute(
        update(Document).where(Document.status == "generating").values(
            status="failed", error={"code": "interrupted", "message": "The app restarted while this was running. "
                                                                      "Retry it."},
        )
    )
    await db.commit()
    return int(getattr(result, "rowcount", 0) or 0) + int(getattr(letters, "rowcount", 0) or 0)


async def master_of_version(db: AsyncSession, version_id: str) -> MasterResume | None:
    version = await db.get(MasterResumeVersion, version_id)
    return await db.get(MasterResume, version.master_id) if version else None
