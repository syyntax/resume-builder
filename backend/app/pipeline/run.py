"""Runs one application end to end: analyze → tailor → hydrate → validate → coverage (DESIGN.md §9.1)."""

from __future__ import annotations

import logging
from typing import Any

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
from app.pipeline.hydrate import hydrate
from app.pipeline.validators import coverage, validate

log = logging.getLogger("resume_tailor.pipeline")
ACTIVE = ("queued", "analyzing", "tailoring", "validating")


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


async def _call[T](app: FastAPI, db: AsyncSession, application: Application, user: User, key: keys.ResolvedKey,
                   stage: str, runner: Any) -> stages.StageResult[T]:
    """Run one model call, recording its usage whether it succeeds or fails after being billed."""
    settings: Settings = app.state.settings
    try:
        result: stages.StageResult[T] = await runner()
    except LLMError as error:
        await usage.record_call(db, owner_id=user.id, application_id=application.id, stage=stage,
                                model=application.model, key_source=key.source, prompt_version=f"{stage}@?",
                                settings=settings, error=error)
        if error.code == "key_rejected" and key.row is not None:
            key.row.status = "invalid"
        await db.commit()
        raise
    await usage.record_call(db, owner_id=user.id, application_id=application.id, stage=stage,
                            model=application.model, key_source=key.source, prompt_version=result.prompt_version,
                            settings=settings, result=result.call)
    if key.row is not None:
        key.row.last_used_at = utcnow()
    await db.commit()
    return result


async def run_application(app: FastAPI, application_id: str) -> None:
    async with app.state.sessionmaker() as db:
        application = await db.get(Application, application_id)
        if application is None or application.status not in ACTIVE:
            return
        user = await db.get(User, application.owner_id)
        job = await db.get(JobPosting, application.job_id)
        version = await db.get(MasterResumeVersion, application.master_version_id)
        if user is None or job is None or version is None:
            return
        try:
            await _execute(app, db, application, user, job, version)
        except ApiError as exc:  # no usable key, spending cap
            code = (exc.extra or {}).get("code", "error")
            await _fail(app, db, application_id, code, exc.detail)
        except LLMError as exc:
            await _fail(app, db, application_id, exc.code, exc.message)
        except Exception:
            log.exception("application %s failed", application_id)
            await _fail(app, db, application_id, "internal_error",
                        "Something went wrong on our side. Retry, and check the server log if it keeps failing.")


async def _execute(app: FastAPI, db: AsyncSession, application: Application, user: User, job: JobPosting,
                   version: MasterResumeVersion) -> None:
    settings: Settings = app.state.settings
    master = version.content
    key = await keys.resolve(db, user, settings)
    llm = app.state.llm_factory(key.api_key)
    model = application.model

    # ---- stage A: analyze the posting -------------------------------------------------------------
    await _set_status(app, db, application, "analyzing")
    await usage.ensure_within_cap(db, user, key.source, settings, usage.estimate_job_cost(model, settings))
    analyzed: stages.StageResult[JobAnalysis] = await _call(
        app, db, application, user, key, "analyze",
        lambda: stages.analyze(llm, model=model, effort=settings.ai_effort_analyze, master=master,
                               version_id=version.id, posting=job.raw_text),
    )
    analysis = analyzed.value
    job.analysis = analysis.model_dump(mode="json", by_alias=True)
    job.company = job.company or analysis.company
    job.title = job.title or analysis.title
    await db.commit()
    _publish(app, application, {"type": "analysis"})

    # ---- stage B: tailor (with one repair pass for unresolved references) ---------------------------
    await _set_status(app, db, application, "tailoring")
    await usage.ensure_within_cap(db, user, key.source, settings,
                                  usage.estimate_job_cost(model, settings, stages=("tailor",)))

    def tailor(repair: list[str] | None = None):  # noqa: ANN202
        return lambda: stages.tailor(llm, model=model, effort=settings.ai_effort_tailor, master=master,
                                     version_id=version.id, posting=job.raw_text, analysis=analysis,
                                     options=application.options, repair=repair)

    drafted = await _call(app, db, application, user, key, "tailor", tailor())
    await _set_status(app, db, application, "validating")
    hydrated = hydrate(drafted.value, master)
    if hydrated.problems:
        await _set_status(app, db, application, "tailoring")
        drafted = await _call(app, db, application, user, key, "tailor_repair", tailor(hydrated.problems))
        await _set_status(app, db, application, "validating")
        hydrated = hydrate(drafted.value, master)
    for problem in hydrated.problems:  # still unresolved after the repair: those parts were dropped
        hydrated.notices.append({"targetId": "draft", "code": "REFERENCE_DROPPED", "message": problem})

    # ---- validate, score, save -------------------------------------------------------------------------------
    warnings = validate(hydrated.resume, master, analysis)
    cover = coverage(hydrated.resume, master, analysis)
    resume = {
        "meta": {
            "schemaVersion": "1.0",
            "applicationId": application.id,
            "generatedAt": utcnow().isoformat(),
            "model": model,
            "promptVersion": drafted.prompt_version,
            "master": {"id": version.master_id, "versionId": version.id, "sha256": version.sha256},
            "job": {"company": job.company, "title": job.title, "url": job.url},
            "template": application.template,
            "theme": application.theme,
        },
        **hydrated.resume,
        "analysis": {
            "coverage": cover,
            "warnings": warnings,
            "notices": hydrated.notices,
            "notes": [n.model_dump(by_alias=True) for n in drafted.value.notes],
        },
    }
    document = (await db.execute(
        select(Document).where(Document.application_id == application.id, Document.kind == "resume")
    )).scalar_one_or_none()
    if document is None:
        document = Document(owner_id=user.id, application_id=application.id, kind="resume")
        db.add(document)
    document.ai_draft = drafted.value.model_dump(mode="json", by_alias=True)
    document.current = resume
    document.updated_at = utcnow()
    application.coverage_score = cover["score"]
    application.error = None
    await _set_status(app, db, application, "done")
    _publish(app, application, {"type": "done"})


async def mark_interrupted(db: AsyncSession) -> int:
    """At startup: jobs that were running when the app stopped can't resume, so mark them failed."""
    result = await db.execute(
        update(Application).where(Application.status.in_(ACTIVE)).values(
            status="failed", updated_at=utcnow(),
            error={"code": "interrupted", "message": "The app restarted while this was running. Retry it."},
        )
    )
    await db.commit()
    return int(getattr(result, "rowcount", 0) or 0)


async def master_of_version(db: AsyncSession, version_id: str) -> MasterResume | None:
    version = await db.get(MasterResumeVersion, version_id)
    return await db.get(MasterResume, version.master_id) if version else None
