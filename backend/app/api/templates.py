"""Templates and theme options (DESIGN.md §11.2–11.4)."""

from __future__ import annotations

import hashlib
from functools import cache

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse

from app.auth.deps import current_user
from app.errors import ApiError
from app.models.api import OptionOut, TemplateDefaultsOut, TemplateOut, TemplatesOut, ThemeOptionsOut
from app.render.fonts import PAIRINGS
from app.render.html import TEMPLATE_DIR
from app.render.theme import ACCENTS, DEFAULT_TEMPLATE, TEMPLATES, Theme

router = APIRouter(prefix="/api/templates", tags=["templates"], dependencies=[Depends(current_user)])


@cache
def _thumbnail_version(key: str) -> str:
    """A content hash for the thumbnail's URL, so a new thumbnail isn't served from the browser's cache."""
    return hashlib.sha256((TEMPLATE_DIR / key / "thumbnail.png").read_bytes()).hexdigest()[:12]


@router.get("", response_model=TemplatesOut)
async def list_templates() -> TemplatesOut:
    def options(pairs: list[tuple[str, str]]) -> list[OptionOut]:
        return [OptionOut(value=v, label=label) for v, label in pairs]

    return TemplatesOut(
        templates=[TemplateOut(key=t.key, label=t.label, description=t.description, layout=t.layout, ats=t.ats,
                               available=t.available,
                               thumbnail_url=f"/api/templates/{t.key}/thumbnail.png?v={_thumbnail_version(t.key)}",
                               default_theme=TemplateDefaultsOut(
                                   accent=t.accent, fonts=t.fonts, contact_icons=t.contact_icons))
                   for t in TEMPLATES.values()],
        options=ThemeOptionsOut(
            accents=options([(value, name) for name, value in ACCENTS.items()]),
            fonts=options([(p.key, p.label) for p in PAIRINGS.values()]),
            densities=options([("comfortable", "Comfortable"), ("balanced", "Balanced"), ("compact", "Compact")]),
            papers=options([("letter", "US Letter"), ("a4", "A4")]),
            margins=options([("normal", "Normal"), ("narrow", "Narrow")]),
            date_formats=options([("MMM YYYY", "Mar 2021"), ("MM/YYYY", "03/2021"), ("YYYY", "2021")]),
        ),
        default_template=DEFAULT_TEMPLATE,
        default_theme=Theme(),
    )


@router.get("/{key}/thumbnail.png", response_class=FileResponse)
async def thumbnail(key: str) -> FileResponse:
    """The sample résumé in this template, for the gallery."""
    if key not in TEMPLATES:
        raise ApiError(404, "There's no such template.")
    return FileResponse(TEMPLATE_DIR / key / "thumbnail.png", media_type="image/png",
                        headers={"Cache-Control": "private, max-age=31536000, immutable"})
