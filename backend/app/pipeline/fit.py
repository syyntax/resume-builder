"""Fit to page (DESIGN.md §11.7, TPL-4).

The résumé: render, and while it runs over the target, step the layout down (tighter density, then narrow margins),
then drop the least relevant bullets that may go: never a pinned, user-written or edited one, and never below the
minimum for a recent role. Bullets are dropped as few as possible (a binary search over the removal order, one
render per step). The cover letter must fit one page: its paragraphs are condensed (stage F).

Each fit is saved with a snapshot of what came before (document_revision), so it can be undone in one step.
"""

from __future__ import annotations

import copy
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date
from io import BytesIO
from typing import Any

from pypdf import PdfReader

from app.ai.stages import DEFAULT_RECENT_YEARS
from app.pipeline.hydrate import MasterIndex
from app.render.pdf import RenderedPdf
from app.render.theme import TEMPLATES, Theme

DENSITY_STEPS = ["comfortable", "balanced", "compact"]
ROOM_TO_SPARE = 0.6  # a last page less full than this has room for more (§11.7 step 4)

Render = Callable[[dict[str, Any], Theme], Awaitable[RenderedPdf]]


@dataclass
class Measure:
    pages: int
    fill: float  # how full the last page is, 0 to 1


def measure(pdf: RenderedPdf, template: str, theme: Theme) -> Measure:
    """Page count, and how far down the last page the text reaches (ignoring the footer in the bottom margin)."""
    page = PdfReader(BytesIO(pdf.data)).pages[-1]
    height = float(page.mediabox.height)
    top, _, bottom = (m * 72 for m in TEMPLATES[template].margins[theme.margins])
    if pdf.pages == 1 and TEMPLATES[template].page == "band":
        top = 0
    lowest = height

    def visit(text: str, cm: list[float], tm: list[float], _font: Any, _size: Any) -> None:
        nonlocal lowest
        y = tm[4] * cm[1] + tm[5] * cm[3] + cm[5]
        if text.strip() and y > bottom * 0.8:
            lowest = min(lowest, y)

    page.extract_text(visitor_text=visit)
    content = height - top - bottom
    fill = (height - top - lowest) / content if content > 0 else 1.0
    return Measure(pdf.pages, max(0.0, min(1.0, fill)))


@dataclass
class FitResult:
    fits: bool
    pages: int
    fill: float
    document: dict[str, Any]
    theme: Theme
    changes: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)  # bullet ids

    @property
    def changed(self) -> bool:
        return bool(self.changes)

    @property
    def room(self) -> bool:
        return self.fits and self.fill < ROOM_TO_SPARE


def _recent(item: dict[str, Any], years: int, today: date) -> bool:
    end = item.get("endDate")
    return not end or int(str(end)[:4]) >= today.year - years


def removal_order(resume: dict[str, Any], master: dict[str, Any], today: date | None = None) -> list[str]:
    """Bullet ids that may go, least needed first: lowest relevance, then older roles, then later in a role."""
    index = MasterIndex.build(master)
    prefs = master.get("preferences") or {}
    years = prefs.get("recentYears") or DEFAULT_RECENT_YEARS
    minimum = prefs.get("minBulletsPerRecentRole")
    minimum = 2 if minimum is None else minimum
    today = today or date.today()
    pinned = {bid for bullets in index.bullets.values() for bid, b in bullets.items() if b.get("pin")}
    candidates: list[tuple[int, int, int, str]] = []
    for section in resume.get("sections") or []:
        if section.get("type") not in ("experience", "projects", "volunteer"):
            continue
        items = section.get("items") or []
        for n, item in enumerate(items):
            bullets = item.get("bullets") or []
            keep = minimum if section["type"] == "experience" and _recent(item, years, today) else 1
            movable = [(i, b) for i, b in enumerate(bullets)
                       if b.get("origin") != "user" and not b.get("edited")
                       and not any(s in pinned for s in b.get("sourceIds") or [])]
            # within a role, the least relevant (then the latest) go first, while enough are left
            movable.sort(key=lambda ib: (ib[1].get("relevance", 3), -ib[0]))
            for i, bullet in movable[:max(0, len(bullets) - keep)]:
                candidates.append((bullet.get("relevance", 3), -n, -i, bullet["id"]))
    candidates.sort()
    return [c[3] for c in candidates]


def without(resume: dict[str, Any], bullet_ids: set[str]) -> dict[str, Any]:
    out = copy.deepcopy(resume)
    for section in out.get("sections") or []:
        for item in section.get("items") or []:
            if item.get("bullets"):
                item["bullets"] = [b for b in item["bullets"] if b["id"] not in bullet_ids]
    return out


def _layout_steps(theme: Theme) -> list[Theme]:
    steps, current = [], theme
    for density in DENSITY_STEPS[DENSITY_STEPS.index(theme.density) + 1:]:
        current = current.model_copy(update={"density": density})
        steps.append(current)
    if theme.margins != "narrow":
        steps.append(current.model_copy(update={"margins": "narrow"}))
    return steps


def _layout_changes(before: Theme, after: Theme) -> list[str]:
    """The layout changes, by where they ended up ("Compact density", not each step on the way)."""
    changes = [f"{after.density.capitalize()} density"] if after.density != before.density else []
    return changes + (["Narrow margins"] if after.margins != before.margins else [])


async def fit_resume(render: Render, resume: dict[str, Any], master: dict[str, Any], template: str, theme: Theme,
                     target: int) -> FitResult:
    before = measure(await render(resume, theme), template, theme)
    if before.pages <= target:
        return FitResult(True, before.pages, before.fill, resume, theme)

    current = theme
    for step in _layout_steps(theme):
        current = step
        after = measure(await render(resume, current), template, current)
        if after.pages <= target:
            return FitResult(True, after.pages, after.fill, resume, current, _layout_changes(theme, current))

    order = removal_order(resume, master)
    if not order:
        return FitResult(False, before.pages, before.fill, resume, theme)
    most = without(resume, set(order))
    if measure(await render(most, current), template, current).pages > target:
        return FitResult(False, before.pages, before.fill, resume, theme)  # can't fit without cutting more
    low, high = 1, len(order)  # the fewest bullets to drop
    while low < high:
        mid = (low + high) // 2
        if measure(await render(without(resume, set(order[:mid])), current), template, current).pages <= target:
            high = mid
        else:
            low = mid + 1
    removed = order[:low]
    fitted = without(resume, set(removed))
    after = measure(await render(fitted, current), template, current)
    noun = "bullet" if low == 1 else "bullets"
    changes = [*_layout_changes(theme, current), f"Removed {low} less relevant {noun}"]
    return FitResult(True, after.pages, after.fill, fitted, current, changes, removed)
