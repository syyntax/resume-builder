"""Rendering (DESIGN.md §11): themes, the HTML view, and the PDF against the ATS checklist (§11.8)."""

from __future__ import annotations

import asyncio
import copy
import io
import re
from typing import Any

import pytest
from fastapi import FastAPI
from pdfminer.high_level import extract_text as pdfminer_text
from pydantic import ValidationError
from pypdf import PdfReader

from app.render.html import date_range, format_date, page_css, render_letter_html, render_resume_html, resume_view
from app.render.pdf import PdfRenderer, RenderedPdf
from app.render.theme import Theme
from tests.conftest import POSTING, Api, drain
from tests.render_samples import LETTER, RESUME, long_resume

LIGATURES = re.compile("[ﬀ-ﬆ]")


def render_all(*jobs: tuple[str, dict[str, str]]) -> tuple[list[RenderedPdf], list[str]]:
    """Render HTML documents with one renderer (one Chromium launch); returns PDFs and blocked requests."""

    async def run() -> tuple[list[RenderedPdf], list[str]]:
        renderer = PdfRenderer()
        try:
            return [await renderer.render(html, meta) for html, meta in jobs], renderer.blocked
        finally:
            await renderer.close()

    return asyncio.run(run())


def resume_html(resume: dict[str, Any] = RESUME, **theme: Any) -> str:
    return render_resume_html(resume, "meridian", Theme(**theme), title="Jordan Rivera – Résumé")


def outline_titles(outline: list[Any]) -> list[str]:
    titles: list[str] = []
    for entry in outline:
        titles.extend(outline_titles(entry) if isinstance(entry, list) else [entry.title])
    return titles


def fonts_of(reader: PdfReader) -> dict[str, bool]:
    """Base font name → whether the font program is embedded, for the text fonts on every page. (Type3 fonts
    are glyph drawings: Chromium uses them only for fallback glyphs from fonts it can't embed.)"""
    out: dict[str, bool] = {}
    for page in reader.pages:
        for ref in (page["/Resources"].get("/Font") or {}).values():
            font = ref.get_object()
            if font["/Subtype"] == "/Type3":
                continue
            descendant = font["/DescendantFonts"][0].get_object() if "/DescendantFonts" in font else font
            descriptor = descendant.get("/FontDescriptor")
            embedded = bool(descriptor) and any(k in descriptor.get_object() for k in ("/FontFile", "/FontFile2",
                                                                                         "/FontFile3"))
            out[str(font["/BaseFont"])] = embedded
    return out


# ---- themes and the view ------------------------------------------------------------------------------------


def test_theme_validation() -> None:
    assert Theme(accent="#0f766e").accent == "#0F766E"
    with pytest.raises(ValidationError, match="too light"):
        Theme(accent="#FFD700")  # gold on white: unreadable
    with pytest.raises(ValidationError, match="hex color"):
        Theme(accent="navy")
    with pytest.raises(ValidationError):
        Theme.model_validate({"fonts": "comic-sans"})
    assert Theme.model_validate({"dateFormat": "YYYY", "contactIcons": False}).date_format == "YYYY"


@pytest.mark.parametrize(("fmt", "expected"), [("MMM YYYY", "Mar 2021 – Present"), ("MM/YYYY", "03/2021 – Present"),
                                               ("YYYY", "2021 – Present")])
def test_date_formats(fmt: str, expected: str) -> None:
    assert date_range({"startDate": "2021-03"}, fmt) == expected
    assert date_range({"startDate": "2016", "endDate": "2016"}, fmt) == "2016"
    assert date_range({"endDate": "2016-05"}, fmt, current=False) == format_date("2016-05", fmt)
    assert date_range({"startDate": "2012-09"}, fmt, current=False) == format_date("2012-09", fmt)  # degree


def test_view_groups_promotions_and_builds_safe_links() -> None:
    resume = copy.deepcopy(RESUME)
    resume["basics"]["profiles"].append({"network": "Portfolio", "url": "javascript:alert(1)"})
    view = resume_view(resume, Theme())
    experience = view["sections"][0]
    assert [g["company"] for g in experience["groups"]] == ["Acme Payments", "Initech"]
    assert [r["position"] for r in experience["groups"][1]["roles"]] == ["Software Engineer II", "Software Engineer"]
    links = {c["text"]: c["href"] for c in view["contact"]}
    assert links["jordan@example.com"] == "mailto:jordan@example.com"
    assert links["(555) 010-0199"] == "tel:5550100199"
    assert links["linkedin.com/in/jrivera"] == "https://linkedin.com/in/jrivera"
    assert links["javascript:alert(1)"] is None  # shown, never linked
    assert view["sections"][-1]["kind"] == "split"  # certifications beside education


def test_html_escapes_everything_from_the_document() -> None:
    resume = copy.deepcopy(RESUME)
    resume["basics"]["name"] = 'Eve</style><script>alert(1)</script>"'
    resume["summary"]["text"] = "Shipped **fast**; <img src=x onerror=alert(1)> *carefully*."
    html = resume_html(resume)
    assert "<script>alert(1)" not in html and "<img src=x" not in html
    assert "Shipped <strong>fast</strong>; &lt;img src=x onerror=alert(1)&gt; <em>carefully</em>." in html
    footer = page_css("meridian", Theme(), resume["basics"]["name"])
    assert "</style>" not in footer and '\\"' in footer  # the footer's CSS string can't break out
    assert html.count("<script") == 0 and "Content-Security-Policy" in html


# ---- PDFs ---------------------------------------------------------------------------------------------------


def test_resume_pdf_meets_the_ats_checklist() -> None:
    meta = {"Title": "Jordan Rivera – Staff Platform Engineer – Globex", "Author": "Jordan Rivera",
            "Subject": "Résumé for Staff Platform Engineer at Globex", "Keywords": "Kubernetes, Terraform"}
    (pdf,), blocked = render_all((resume_html(), meta))
    reader = PdfReader(io.BytesIO(pdf.data))
    assert pdf.pages == 1  # the mockup's content fits on one Letter page, as approved
    assert [round(float(x)) for x in reader.pages[0].mediabox[2:]] == [612, 792]

    # Two extractors, as résumé parsers differ: both must read whole headings, in order, without ligatures.
    order = ["Jordan Rivera", "Senior Platform Engineer", "SUMMARY", "Platform engineer with 9 years", "EXPERIENCE",
             "Acme Payments", "Led migration of 40 payment services", "Initech", "PROJECTS", "tf-guard", "SKILLS",
             "CERTIFICATIONS", "EDUCATION"]
    for text in (reader.pages[0].extract_text(), pdfminer_text(io.BytesIO(pdf.data))):
        flat = " ".join(text.split())
        positions = [m.start() if (m := re.search(rf"\b{re.escape(t)}\b", flat, re.IGNORECASE)) else -1 for t in order]
        assert -1 not in positions and positions == sorted(positions), dict(zip(order, positions, strict=True))
        assert "jordan@example.com" in flat  # contact details are body text, not a page header
        assert not LIGATURES.search(flat), "ligatures would break keyword matching"
        assert "configuration" in flat  # "fi" stays two letters

    fonts = fonts_of(reader)
    assert fonts and all(fonts.values()), f"every font embedded: {fonts}"
    assert any("Inter" in name for name in fonts)

    info = reader.metadata
    assert (info.title, info.author, info.subject) == (meta["Title"], meta["Author"], meta["Subject"])
    assert info["/Keywords"] == "Kubernetes, Terraform" and info.creator == "Resume Tailor"
    root = reader.trailer["/Root"]
    assert "/StructTreeRoot" in root and bool(root["/MarkInfo"]["/Marked"]) and root["/Lang"] == "en"  # tagged
    assert [t.lower() for t in outline_titles(reader.outline)[:3]] == ["jordan rivera", "summary", "experience"]
    uris = {a.get_object()["/A"]["/URI"] for a in reader.pages[0].get("/Annots", []) if "/A" in a.get_object()}
    assert {"mailto:jordan@example.com", "https://linkedin.com/in/jrivera"} <= uris
    assert blocked == []


def test_long_resumes_paginate_with_a_footer_from_page_two() -> None:
    (pdf,), _ = render_all((resume_html(long_resume()), {"Title": "Long"}))
    reader = PdfReader(io.BytesIO(pdf.data))
    assert pdf.pages >= 2
    assert "Page 1 of" not in reader.pages[0].extract_text()
    assert f"Jordan Rivera · Page 2 of {pdf.pages}" in reader.pages[1].extract_text()


def test_theme_options_change_the_output() -> None:
    jobs = [(resume_html(paper="a4"), {}), (resume_html(fonts="garamond", accent="#7A1F3D"), {}),
            (resume_html(fonts="lato", density="compact"), {}), (resume_html(fonts="plex"), {}),
            (resume_html(fonts="source", contact_icons=False, date_format="YYYY"), {})]
    pdfs, _ = render_all(*jobs)
    readers = [PdfReader(io.BytesIO(p.data)) for p in pdfs]
    assert [round(float(x)) for x in readers[0].pages[0].mediabox[2:]] == [595, 842]
    for reader, family in zip(readers[1:], ["Garamond", "Merriweather", "Plex", "Source"], strict=True):
        fonts = fonts_of(reader)
        assert any(family.replace(" ", "") in name.replace(" ", "") for name in fonts), (family, fonts)
        assert all(fonts.values())
    years_only = readers[4].pages[0].extract_text()
    assert "Mar 2021" not in years_only and "2021 – Present" in years_only


def test_documents_cannot_reach_the_network_and_renders_are_cached() -> None:
    hostile = ("<!doctype html><html><head><link rel=stylesheet href='https://example.com/x.css'>"
               "<style>@import url('https://example.com/y.css'); body{background:url(http://example.com/z.png)}</style>"
               "</head><body><img src='https://example.com/a.png'><iframe src='file:///etc/passwd'></iframe>"
               "<p>hi</p></body></html>")
    pdfs, blocked = render_all((hostile, {}), (hostile, {}))
    assert pdfs[0] is pdfs[1]  # the second render came from the cache
    assert {"https://example.com/x.css", "https://example.com/a.png"} <= set(blocked)
    assert "root:" not in PdfReader(io.BytesIO(pdfs[0].data)).pages[0].extract_text()


def test_cover_letter_renders() -> None:
    html = render_letter_html(LETTER, "meridian", Theme(), title="Cover letter")
    (pdf,), _ = render_all((html, {"Title": "Cover letter"}))
    text = PdfReader(io.BytesIO(pdf.data)).pages[0].extract_text()
    assert pdf.pages == 1
    for expected in ("October 6, 2026", "Priya Shah", "Re: Staff Platform Engineer", "Dear Priya Shah,",
                     "Sincerely,"):
        assert expected.lower() in text.lower(), expected


# ---- the API ----------------------------------------------------------------------------------------------------


def test_preview_export_and_design(app: FastAPI, keyed_user: Api, example: dict[str, Any]) -> None:
    master_id = keyed_user.post("/api/master-resumes", json=example).json()["master"]["id"]
    app_id = keyed_user.post("/api/applications", json={"masterId": master_id, "job": {"text": POSTING}}).json()["id"]
    detail = keyed_user.get(f"/api/applications/{app_id}").json()
    assert detail["template"] == "meridian" and detail["theme"]["accent"] == "#1F3A5F"
    assert keyed_user.get(f"/api/applications/{app_id}/preview.pdf").status_code == 409  # still generating
    drain(app)

    preview = keyed_user.get(f"/api/applications/{app_id}/preview.pdf")
    assert preview.status_code == 200 and preview.headers["content-type"] == "application/pdf"
    assert preview.content.startswith(b"%PDF-")
    assert preview.headers["x-page-count"] == str(len(PdfReader(io.BytesIO(preview.content)).pages))
    export = keyed_user.get(f"/api/applications/{app_id}/export", params={"format": "pdf"})
    assert export.content == preview.content  # the preview is the export
    assert export.headers["content-disposition"] == \
        'attachment; filename="Jordan-Rivera_Globex_Staff-Platform-Engineer_Resume.pdf"'
    info = PdfReader(io.BytesIO(export.content)).metadata
    assert info.title == "Jordan Rivera – Staff Platform Engineer – Globex" and "Kubernetes" in info["/Keywords"]

    theme = {"accent": "#0F766E", "fonts": "plex", "density": "compact", "paper": "a4", "margins": "narrow",
             "dateFormat": "MM/YYYY", "contactIcons": False}
    saved = keyed_user.put(f"/api/applications/{app_id}/design", json={"template": "meridian", "theme": theme})
    assert saved.status_code == 200 and saved.json()["theme"] == theme
    assert keyed_user.get(f"/api/applications/{app_id}").json()["theme"] == theme
    a4 = PdfReader(io.BytesIO(keyed_user.get(f"/api/applications/{app_id}/preview.pdf").content))
    assert [round(float(x)) for x in a4.pages[0].mediabox[2:]] == [595, 842]
    exported = keyed_user.get(f"/api/applications/{app_id}/export", params={"format": "json"}).json()
    assert exported["meta"]["theme"] == theme

    bad = keyed_user.put(f"/api/applications/{app_id}/design",
                         json={"template": "meridian", "theme": {"accent": "#FFFF00"}})
    assert bad.status_code == 422 and "too light" in bad.text
    soon = keyed_user.put(f"/api/applications/{app_id}/design", json={"template": "atlas", "theme": {}})
    assert soon.status_code == 422 and "isn't available yet" in soon.json()["detail"]


def test_template_catalog(app: FastAPI, keyed_user: Api) -> None:
    catalog = keyed_user.get("/api/templates").json()
    assert [t["key"] for t in catalog["templates"]] == ["meridian", "atlas", "ledger", "vanguard"]
    assert [t["available"] for t in catalog["templates"]] == [True, False, False, False]
    assert len(catalog["options"]["accents"]) == 8 and len(catalog["options"]["fonts"]) == 5
    assert catalog["defaultTheme"]["paper"] == "letter" and catalog["defaultTemplate"] == "meridian"
