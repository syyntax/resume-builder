"""Rendering an application's documents with its chosen template and theme."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from pydantic import ValidationError

from app.errors import ApiError
from app.render.html import render_resume_html
from app.render.pdf import RenderedPdf, RenderError
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
