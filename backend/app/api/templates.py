"""Templates and theme options (DESIGN.md §11.2–11.4)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.auth.deps import current_user
from app.models.api import OptionOut, TemplateOut, TemplatesOut, ThemeOptionsOut
from app.render.fonts import PAIRINGS
from app.render.theme import ACCENTS, DEFAULT_TEMPLATE, TEMPLATES, Theme

router = APIRouter(prefix="/api/templates", tags=["templates"], dependencies=[Depends(current_user)])


@router.get("", response_model=TemplatesOut)
async def list_templates() -> TemplatesOut:
    def options(pairs: list[tuple[str, str]]) -> list[OptionOut]:
        return [OptionOut(value=v, label=label) for v, label in pairs]

    return TemplatesOut(
        templates=[TemplateOut(key=t.key, label=t.label, description=t.description, layout=t.layout, ats=t.ats,
                               available=t.available) for t in TEMPLATES.values()],
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
