"""Template thumbnails for the gallery (TPL-2): the sample résumé in each template, with its own colors and fonts.

A development tool, run after changing a template: ``python -m app.render.thumbnails`` (needs the dev extra,
for pypdfium2). It writes app/render/templates/<name>/thumbnail.png.
"""

from __future__ import annotations

import asyncio

from app.render.html import TEMPLATE_DIR, render_resume_html
from app.render.pdf import PdfRenderer
from app.render.samples import RESUME
from app.render.theme import TEMPLATES, Theme

WIDTH = 400  # pixels: shown at 200 CSS pixels, so sharp on high-density screens


async def main() -> None:
    import pypdfium2  # noqa: PLC0415  (dev only)

    renderer = PdfRenderer()
    try:
        for key, info in TEMPLATES.items():
            theme = Theme(accent=info.accent, fonts=info.fonts, contact_icons=info.contact_icons)
            pdf = await renderer.render(render_resume_html(RESUME, key, theme, title=info.label), {})
            page = pypdfium2.PdfDocument(pdf.data)[0]
            image = page.render(scale=WIDTH / page.get_width()).to_pil()
            out = TEMPLATE_DIR / key / "thumbnail.png"
            image.save(out, optimize=True)
            print(out, image.size)  # noqa: T201
    finally:
        await renderer.close()


if __name__ == "__main__":
    asyncio.run(main())
