"""Fit to page (DESIGN.md §11.7, TPL-4): layout steps, then the fewest bullets; the letter condensed; undo."""

from __future__ import annotations

import asyncio
import copy
import io
from datetime import date
from typing import Any

from fastapi import FastAPI
from pypdf import PdfReader
from sqlalchemy import func, select

from app.db.models import AiCall, DocumentRevision
from app.pipeline.fit import fit_resume, measure, removal_order, without
from app.render.html import render_resume_html
from app.render.pdf import PdfRenderer, RenderedPdf
from app.render.samples import RESUME, long_resume
from app.render.theme import Theme
from tests.conftest import TEST_KEY, USER_PASSWORD, Api, drain
from tests.test_workspace import application, bullets

MASTER = {
    "basics": {"name": "Jordan Rivera"},
    "preferences": {"minBulletsPerRecentRole": 2, "recentYears": 10},
    "work": [{"id": "acme", "highlights": [{"id": "acme.b1", "text": "x", "pin": True}]}],
}


def sample() -> dict[str, Any]:
    """Two roles: a current one with five bullets and an old one with three, at varied relevance."""
    def bullet(bid: str, relevance: int, **extra: Any) -> dict[str, Any]:
        return {"id": bid, "text": f"Bullet {bid}.", "sourceIds": [f"src.{bid}"], "relevance": relevance,
                "keywords": [], "origin": "ai", "edited": False, "warnings": [], **extra}

    return {"sections": [{"type": "experience", "title": "Experience", "items": [
        {"sourceId": "acme", "startDate": "2021-03", "bullets": [
            bullet("a1", 5, sourceIds=["acme.b1"]), bullet("a2", 2), bullet("a3", 1, origin="user"),
            bullet("a4", 1), bullet("a5", 3, edited=True)]},
        {"sourceId": "old", "startDate": "2008-01", "endDate": "2010-01", "bullets": [
            bullet("o1", 4), bullet("o2", 2), bullet("o3", 2)]},
    ]}]}


def test_removal_order_keeps_what_must_stay() -> None:
    order = removal_order(sample(), MASTER, today=date(2026, 10, 7))
    # pinned (a1), the user's own (a3) and edited (a5) bullets never go (but count toward the current role's two);
    # the old role keeps one; lower relevance first, then older roles, then later bullets
    assert order == ["a4", "o3", "o2", "a2"]
    assert [b["id"] for b in without(sample(), set(order))["sections"][0]["items"][1]["bullets"]] == ["o1"]


def test_fit_steps_the_layout_then_drops_the_fewest_bullets() -> None:
    async def run() -> tuple[Any, Any, list[int]]:
        renderer = PdfRenderer()
        pages: list[int] = []

        async def render(resume: dict[str, Any], theme: Theme) -> RenderedPdf:
            pdf = await renderer.render(render_resume_html(resume, "meridian", theme, title="T"), {})
            pages.append(pdf.pages)
            return pdf

        try:
            short = await fit_resume(render, RESUME, {}, "meridian", Theme(), 1)
            master = {"preferences": {"recentYears": 5}}  # the added roles are old: they may go down to one bullet
            long = await fit_resume(render, long_resume(2), master, "meridian", Theme(density="comfortable"), 1)
            return short, long, pages
        finally:
            await renderer.close()

    short, long, _ = asyncio.run(run())
    assert short.fits and not short.changed and short.pages == 1  # already fits: nothing changes
    assert long.fits and long.pages == 1
    assert long.changes[:2] == ["Compact density", "Narrow margins"]  # where the layout ended up
    assert long.theme.density == "compact" and long.theme.margins == "narrow"
    assert long.changes[-1].startswith("Removed ") and long.removed
    # the fewest: putting back the last bullet removed runs over again
    assert len(bullets(long.document)) == len(bullets(long_resume(2))) - len(long.removed)


def test_measure_reads_how_full_the_last_page_is() -> None:
    async def run() -> list[RenderedPdf]:
        renderer = PdfRenderer()
        try:
            return [await renderer.render(render_resume_html(r, "meridian", Theme(), title="T"), {})
                    for r in (RESUME, {**RESUME, "sections": []})]
        finally:
            await renderer.close()

    full, short = (measure(pdf, "meridian", Theme()) for pdf in asyncio.run(run()))
    assert full.pages == short.pages == 1 and 0.8 < full.fill <= 1 and short.fill < 0.3


def test_fit_resume_api_and_undo(app: FastAPI, keyed_user: Api, example: dict[str, Any]) -> None:
    detail = application(app, keyed_user, example, pageLimit=1)
    app_id = detail["id"]
    keyed_user.put(f"/api/applications/{app_id}/design",
                   json={"template": "atlas", "theme": {"density": "comfortable", "accent": "#0F766E"}})
    before = keyed_user.get(f"/api/applications/{app_id}").json()
    pages = int(keyed_user.get(f"/api/applications/{app_id}/preview.pdf").headers["x-page-count"])
    assert pages > 1

    fitted = keyed_user.post(f"/api/applications/{app_id}/resume/fit", json={})
    assert fitted.status_code == 200, fitted.text
    out = fitted.json()
    assert out["fits"] and out["pages"] == 1 and out["changes"] and out["revisionId"]
    assert out["theme"]["density"] == "compact" and out["template"] == "atlas"
    preview = keyed_user.get(f"/api/applications/{app_id}/preview.pdf")
    assert preview.headers["x-page-count"] == "1" and len(PdfReader(io.BytesIO(preview.content)).pages) == 1
    after = keyed_user.get(f"/api/applications/{app_id}").json()
    assert after["theme"] == out["theme"] and after["resume"]["meta"]["theme"] == out["theme"]
    assert len(bullets(after["resume"])) == len(bullets(before["resume"])) - len(out["removed"])

    # fitting again changes nothing
    again = keyed_user.post(f"/api/applications/{app_id}/resume/fit", json={}).json()
    assert again["changes"] == [] and again["revisionId"] is None

    # undo: the résumé and the design as they were, once
    restored = keyed_user.post(f"/api/applications/{app_id}/revisions/{out['revisionId']}/restore")
    assert restored.status_code == 200, restored.text
    assert restored.json()["theme"]["density"] == "comfortable"
    now = keyed_user.get(f"/api/applications/{app_id}").json()
    assert now["theme"] == before["theme"] and len(bullets(now["resume"])) == len(bullets(before["resume"]))
    assert keyed_user.post(f"/api/applications/{app_id}/revisions/{out['revisionId']}/restore").status_code == 404


def test_fit_letter_condenses_it(app: FastAPI, keyed_user: Api, example: dict[str, Any]) -> None:
    detail = application(app, keyed_user, example, letter={"notes": "I like Globex."})
    app_id, letter = detail["id"], copy.deepcopy(detail["coverLetter"])
    for p in letter["paragraphs"]:  # long enough to run onto a second page
        p["text"] = " ".join([p["text"]] + [f"I also worked on item {n} with the platform team." for n in range(12)])
    assert keyed_user.put(f"/api/applications/{app_id}/cover-letter", json={"document": letter}).status_code == 200
    preview = keyed_user.get(f"/api/applications/{app_id}/preview.pdf", params={"doc": "cover-letter"})
    assert int(preview.headers["x-page-count"]) > 1
    words = sum(len(p["text"].split()) for p in letter["paragraphs"])

    out = keyed_user.post(f"/api/applications/{app_id}/cover-letter/fit")
    assert out.status_code == 200, out.text
    result = out.json()
    shorter = sum(len(p["text"].split()) for p in result["document"]["paragraphs"])
    assert shorter < words and result["revisionId"] and result["changes"][0].startswith("Condensed")
    assert result["costUsd"] > 0

    async def condense_calls() -> int:
        async with app.state.sessionmaker() as db:
            return (await db.execute(select(func.count()).select_from(AiCall).where(
                AiCall.stage == "condense", AiCall.application_id == app_id))).scalar_one()

    assert app.state.test_portal.call(condense_calls) in (1, 2)
    restored = keyed_user.post(f"/api/applications/{app_id}/revisions/{result['revisionId']}/restore").json()
    assert restored["kind"] == "cover_letter"
    assert sum(len(p["text"].split()) for p in restored["document"]["paragraphs"]) == words


def test_a_revision_cant_be_restored_through_another_application(app: FastAPI, make_user, example) -> None:
    alice, bob = make_user("alice@example.com"), make_user("bob@example.com")
    for user in (alice, bob):
        user.put("/api/account/api-key", json={"apiKey": TEST_KEY, "password": USER_PASSWORD})
    mine, theirs = (application(app, user, example, pageLimit=1) for user in (alice, bob))
    alice.put(f"/api/applications/{mine['id']}/design", json={"template": "atlas",
                                                             "theme": {"density": "comfortable"}})
    revision = alice.post(f"/api/applications/{mine['id']}/resume/fit", json={}).json()["revisionId"]
    assert revision
    assert bob.post(f"/api/applications/{theirs['id']}/revisions/{revision}/restore").status_code == 404
    assert bob.post(f"/api/applications/{mine['id']}/revisions/{revision}/restore").status_code == 404

    async def count() -> int:
        async with app.state.sessionmaker() as db:
            return (await db.execute(select(func.count()).select_from(DocumentRevision))).scalar_one()

    assert app.state.test_portal.call(count) == 1
    drain(app)
