"""HTML → PDF with headless Chromium (DESIGN.md §11.1, §11.5).

One browser is shared by every render (started on first use, or at startup when warming up); each render
gets a fresh, isolated browser context with JavaScript off and every network request blocked, since the
HTML is self-contained (fonts are inlined). Concurrency is capped, and recent results are cached so the
preview and the export of the same document are one render.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import io
import json
import logging
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

log = logging.getLogger("resume_tailor.render")

LAUNCH_ARGS = ["--disable-dev-shm-usage", "--disable-gpu", "--no-first-run", "--disable-extensions",
               "--font-render-hinting=none", "--disable-background-networking"]
RENDER_TIMEOUT_MS = 30_000


class RenderError(Exception):
    """Rendering failed; the message is safe to show."""


@dataclass(frozen=True)
class RenderedPdf:
    data: bytes
    pages: int


def finish_pdf(raw: bytes, metadata: dict[str, str]) -> RenderedPdf:
    """Set the document metadata (Chromium only sets the title) and count pages."""
    from pypdf import PdfReader, PdfWriter

    pages = len(PdfReader(io.BytesIO(raw)).pages)
    # An incremental update appends the new Info dictionary and leaves Chromium's objects untouched; rewriting
    # the file (clone_from) would drop the structure tree that makes it a tagged PDF.
    writer = PdfWriter(io.BytesIO(raw), incremental=True)
    writer.add_metadata({f"/{key}": value for key, value in metadata.items() if value})
    out = io.BytesIO()
    writer.write(out)
    return RenderedPdf(out.getvalue(), pages)


def merge_pdfs(parts: list[tuple[str, RenderedPdf]], metadata: dict[str, str]) -> RenderedPdf:
    """Concatenate PDFs with a top-level bookmark per part. (pypdf doesn't merge structure trees, so the
    packet isn't tagged; the separate documents are.)"""
    from pypdf import PdfReader, PdfWriter

    writer = PdfWriter()
    for title, part in parts:
        start = len(writer.pages)
        writer.append(PdfReader(io.BytesIO(part.data)), import_outline=False)
        writer.add_outline_item(title, start)
    writer.add_metadata({f"/{key}": value for key, value in {**metadata, "Creator": "Resume Tailor"}.items() if value})
    writer.page_mode = "/UseOutlines"
    out = io.BytesIO()
    writer.write(out)
    return RenderedPdf(out.getvalue(), len(writer.pages))


class PdfRenderer:
    def __init__(self, *, concurrency: int = 2, cache_size: int = 24) -> None:
        self._slots = asyncio.Semaphore(max(1, concurrency))
        self._lock = asyncio.Lock()
        self._playwright: Any = None
        self._browser: Any = None
        self._cache: OrderedDict[str, RenderedPdf] = OrderedDict()
        self._cache_size = cache_size
        self.blocked: list[str] = []  # requests a document tried to make (always refused); for tests and logs

    async def _get_browser(self) -> Any:
        async with self._lock:
            if self._browser is not None and self._browser.is_connected():
                return self._browser
            from playwright.async_api import Error, async_playwright

            try:
                if self._playwright is None:
                    self._playwright = await async_playwright().start()
                self._browser = await self._playwright.chromium.launch(args=LAUNCH_ARGS)
            except Error as exc:
                log.error("Couldn't start Chromium for PDF rendering: %s", exc)
                raise RenderError("PDF rendering isn't available on this server (Chromium couldn't start). "
                                  "Check the server log.") from exc
            return self._browser

    async def warm_up(self) -> None:
        with contextlib.suppress(RenderError):  # already logged; renders will report it
            await self._get_browser()

    async def _abort(self, route: Any) -> None:
        self.blocked.append(route.request.url)
        await route.abort("blockedbyclient")

    async def render(self, html: str, metadata: dict[str, str]) -> RenderedPdf:
        key = hashlib.sha256((html + json.dumps(metadata, sort_keys=True)).encode()).hexdigest()
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        from playwright.async_api import Error

        async with self._slots:
            browser = await self._get_browser()
            try:
                context = await browser.new_context(java_script_enabled=False)
                try:
                    page = await context.new_page()
                    await page.route("**/*", self._abort)
                    await page.set_content(html, wait_until="load", timeout=RENDER_TIMEOUT_MS)
                    await page.evaluate("document.fonts.ready.then(() => true)")
                    raw = await page.pdf(prefer_css_page_size=True, print_background=True, tagged=True,
                                         outline=True)
                finally:
                    await context.close()
            except Error as exc:
                log.warning("PDF render failed: %s", exc)
                raise RenderError("The PDF couldn't be rendered. Try again in a moment.") from exc
        result = await asyncio.to_thread(finish_pdf, raw, {**metadata, "Creator": "Resume Tailor",
                                                           "Producer": "Resume Tailor (Chromium)"})
        self._cache[key] = result
        while len(self._cache) > self._cache_size:
            self._cache.popitem(last=False)
        return result

    async def close(self) -> None:
        async with self._lock:
            # Shutting down: bounded, and errors are irrelevant (the process is about to exit anyway).
            if self._browser is not None:
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(self._browser.close(), timeout=10)
                self._browser = None
            if self._playwright is not None:
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(self._playwright.stop(), timeout=10)
                self._playwright = None
