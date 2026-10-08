"""Rendering an application's documents with its chosen template and theme."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from pydantic import ValidationError

from app.errors import ApiError
from app.render.html import render_letter_html, render_resume_html
from app.render.pdf import RenderedPdf, RenderError, merge_pdfs
from app.render.theme import DEFAULT_TEMPLATE, TEMPLATES, Theme


def stored_design(template: str | None, theme: dict[str, Any] | None) -> tuple[str, Theme]:
    """The template and theme to render with: what's stored, or the defaults if that's unusable."""
    key = template if template in TEMPLATES and TEMPLATES[template].available else DEFAULT_TEMPLATE
    try:
        return key, Theme.model_validate(theme or {})
    except ValidationError:
        return key, Theme()


def resume_title(resume: dict[str, Any], job: dict[str, Any]) -> str:
    name = (resume.get("basics") or {}).get("name") or "Résumé"
    return " – ".join(p for p in (name, job.get("title"), job.get("company")) if p)


def resume_metadata(resume: dict[str, Any], job: dict[str, Any]) -> dict[str, str]:
    role = " at ".join(p for p in (job.get("title"), job.get("company")) if p)
    matched = ((resume.get("analysis") or {}).get("coverage") or {}).get("matched") or []
    return {
        "Title": resume_title(resume, job),
        "Author": (resume.get("basics") or {}).get("name") or "",
        "Subject": f"Résumé for {role}" if role else "Résumé",
        "Keywords": ", ".join(matched),
    }


async def render_resume(app: FastAPI, resume: dict[str, Any], job: dict[str, Any], template: str | None,
                        theme: dict[str, Any] | None) -> RenderedPdf:
    key, parsed = stored_design(template, theme)
    html = render_resume_html(resume, key, parsed, title=resume_title(resume, job))
    try:
        return await app.state.pdf.render(html, resume_metadata(resume, job))
    except RenderError as exc:
        raise ApiError(503, str(exc), extra={"code": "render_failed"}) from exc


def letter_metadata(letter: dict[str, Any], job: dict[str, Any]) -> dict[str, str]:
    name = (letter.get("sender") or {}).get("name") or ""
    role = " at ".join(p for p in (job.get("title"), job.get("company")) if p)
    return {"Title": " – ".join(p for p in (name, "Cover letter", job.get("company")) if p), "Author": name,
            "Subject": f"Cover letter for {role}" if role else "Cover letter"}


async def _render(app: FastAPI, html: str, metadata: dict[str, str]) -> RenderedPdf:
    try:
        return await app.state.pdf.render(html, metadata)
    except RenderError as exc:
        raise ApiError(503, str(exc), extra={"code": "render_failed"}) from exc


async def render_letter(app: FastAPI, letter: dict[str, Any], job: dict[str, Any], template: str | None,
                        theme: dict[str, Any] | None) -> RenderedPdf:
    """The cover letter with the résumé's letterhead: same template, fonts and accent (CVL-6)."""
    key, parsed = stored_design(template, theme)
    meta = letter_metadata(letter, job)
    return await _render(app, render_letter_html(letter, key, parsed, title=meta["Title"]), meta)


async def render_packet(app: FastAPI, letter: dict[str, Any], resume: dict[str, Any], job: dict[str, Any],
                        template: str | None, theme: dict[str, Any] | None) -> RenderedPdf:
    """The application packet (CVL-8): the cover letter, then the résumé, with a bookmark for each."""
    first = await render_letter(app, letter, job, template, theme)
    second = await render_resume(app, resume, job, template, theme)
    name = (resume.get("basics") or {}).get("name") or ""
    meta = {**resume_metadata(resume, job),
            "Title": " – ".join(p for p in (name, "Application", job.get("title"), job.get("company")) if p)}
    return merge_pdfs([("Cover letter", first), ("Résumé", second)], meta)
