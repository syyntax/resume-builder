"""Runs one résumé import: transcribe → convert → normalize → fidelity check → flags (DESIGN.md §10.2).

Sniffing and extraction already happened when the file was uploaded, so a bad file is rejected right away
instead of becoming a failed job.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from fastapi import FastAPI
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import stages
from app.ai.llm import LLMError
from app.config import Settings
from app.db.models import ImportJob, UploadedFile, User
from app.db.types import utcnow
from app.errors import ApiError
from app.importers import fidelity
from app.importers.convert import Note, convert, finalize, locate
from app.importers.sniff import ImportRejected
from app.keys import service as keys
from app.masters.normalize import slugify
from app.pipeline import usage

log = logging.getLogger("resume_tailor.imports")
ACTIVE = ("queued", "transcribing", "checking")


def default_label(source_name: str) -> str:
    stem = re.sub(r"\.(pdf|docx)$", "", source_name, flags=re.IGNORECASE).strip() or "résumé"
    return f"Imported from {stem}"[:100]


def _document_order(doc: dict[str, Any]) -> dict[str, int]:
    order: dict[str, int] = {"basics": 0}

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if isinstance(node.get("id"), str):
                order.setdefault(node["id"], len(order))
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk({k: v for k, v in doc.items() if k != "skills"})
    walk(doc.get("skills"))
    return order


def build_flags(doc: dict[str, Any], notes: list[Note], report: dict[str, Any],
                inferred: list[dict[str, str]]) -> list[dict[str, Any]]:
    """Everything the review screen asks the person to check, in document order."""
    flags: list[dict[str, Any]] = []
    for i, note in enumerate(notes):
        target, field = locate(doc, note.path)
        flags.append({"key": f"note-{i}", "kind": "note", "severity": note.severity, "message": note.message,
                      "path": note.path, "targetId": target, "field": field})
    noted = {(f["targetId"], f["field"]) for f in flags}
    for m in report.get("mismatches", []):
        if (m["targetId"], m["field"]) in noted:  # one flag per field: the note already points here
            continue
        words = ", ".join(f"“{w}”" for w in m.get("missing", []))
        message = (f"Not in the original: {words}. Compare it with the document." if words else
                   f"Doesn't match the original word for word ({m['score']:.0f}% similar). Compare it with the "
                   "document.")
        flags.append({"key": f"fidelity-{m['targetId']}-{m['field']}", "kind": "fidelity", "severity": "warning",
                      "message": message,
                      "path": m["path"], "targetId": m["targetId"], "field": m["field"], "score": m["score"]})
    order = _document_order(doc)
    flags.sort(key=lambda f: order.get(f["targetId"] or "", len(order)))
    seen: set[str] = set()
    for skill in inferred:
        key = f"skill-{slugify(skill['name'])}"
        if key not in seen:
            seen.add(key)
            flags.append({"key": key, "kind": "inferredSkill", "severity": "info", "path": "skills",
                          "message": f"“{skill['name']}” is mentioned but not listed as a skill. Add it?",
                          "skill": skill})
    return flags


async def _set_status(app: FastAPI, db: AsyncSession, job: ImportJob, status: str) -> None:
    job.status, job.updated_at = status, utcnow()
    await db.commit()
    app.state.events.publish(job.id, {"type": "status", "status": status})


async def _fail(app: FastAPI, db: AsyncSession, import_id: str, code: str, message: str) -> None:
    await db.rollback()
    job = await db.get(ImportJob, import_id, populate_existing=True)
    if job is None:
        return
    job.status, job.updated_at, job.error = "failed", utcnow(), {"code": code, "message": message}
    await db.commit()
    app.state.events.publish(import_id, {"type": "error", "code": code, "message": message})


async def run_import(app: FastAPI, import_id: str) -> None:
    async with app.state.sessionmaker() as db:
        job = await db.get(ImportJob, import_id)
        if job is None or job.status not in ACTIVE:
            return
        user = await db.get(User, job.owner_id)
        if user is None:
            return
        try:
            await _execute(app, db, job, user)
        except ApiError as exc:  # no usable key, spending cap
            await _fail(app, db, import_id, (exc.extra or {}).get("code", "error"), exc.detail)
        except (LLMError, ImportRejected) as exc:
            await _fail(app, db, import_id, exc.code, exc.message)
        except Exception:
            log.exception("import %s failed", import_id)
            await _fail(app, db, import_id, "internal_error",
                        "Something went wrong on our side. Retry, and check the server log if it keeps failing.")


async def _execute(app: FastAPI, db: AsyncSession, job: ImportJob, user: User) -> None:
    settings: Settings = app.state.settings
    key = await keys.resolve(db, user, settings)
    llm = app.state.llm_factory(key.api_key)

    await _set_status(app, db, job, "transcribing")
    await usage.ensure_within_cap(db, user, key.source, settings,
                                  usage.estimate_job_cost(job.model, settings, stages=("import",)))
    pdf = None
    if job.source_kind == "pdf":
        file = await db.get(UploadedFile, job.file_id) if job.file_id else None
        if file is None:
            raise ImportRejected("missing_file", "The uploaded file was deleted. Upload it again.")
        pdf = app.state.files.read(file.storage_key)
    source_text = str(job.extraction.get("text") or "")
    try:
        result = await stages.transcribe(llm, model=job.model, effort=settings.ai_effort_import,
                                         kind=job.source_kind, text=source_text, pdf=pdf)
    except LLMError as error:
        await usage.record_call(db, owner_id=user.id, application_id=None, import_job_id=job.id, stage="import",
                                model=job.model, key_source=key.source, prompt_version="import@?",
                                settings=settings, error=error)
        if error.code == "key_rejected" and key.row is not None:
            key.row.status = "invalid"
        await db.commit()
        raise
    await usage.record_call(db, owner_id=user.id, application_id=None, import_job_id=job.id, stage="import",
                            model=job.model, key_source=key.source, prompt_version=result.prompt_version,
                            settings=settings, result=result.call)
    if key.row is not None:
        key.row.last_used_at = utcnow()
    await db.commit()

    await _set_status(app, db, job, "checking")
    converted = convert(result.value, label=default_label(job.source_name))
    document, notes = finalize(converted)
    report = fidelity.check(document, source_text)
    job.draft, job.fidelity = document, report
    job.flags = build_flags(document, notes, report, converted.inferred_skills)
    job.review, job.error = None, None
    await _set_status(app, db, job, "ready")
    app.state.events.publish(job.id, {"type": "done"})


async def mark_interrupted(db: AsyncSession) -> int:
    result = await db.execute(
        update(ImportJob).where(ImportJob.status.in_(ACTIVE)).values(
            status="failed", updated_at=utcnow(),
            error={"code": "interrupted", "message": "The app restarted while this was running. Retry it."},
        )
    )
    await db.commit()
    return int(getattr(result, "rowcount", 0) or 0)
