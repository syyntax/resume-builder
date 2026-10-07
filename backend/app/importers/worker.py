"""Sandboxed document extraction: ``python -m app.importers.worker pdf|docx`` with the file on stdin.

Runs in its own process with CPU, memory and file-size limits set before any parser is imported, so a
decompression bomb or a parser bug takes down only this process (DESIGN.md §10.5). Prints one JSON object:

- PDF:  ``{"kind", "pages", "hasTextLayer", "text"}``
- DOCX: ``{"kind", "text", "html"}``. ``text`` is lightly marked up (``# `` headings, ``- `` list items,
  `` | `` table cells) and includes headers, footers, text boxes (in place) and hyperlink targets.
- Failure: ``{"error": code, "message": text}``
"""

from __future__ import annotations

import contextlib
import io
import json
import re
import sys
import zipfile
from typing import Any

CPU_SECONDS = 20
MEMORY_BYTES = 512 * 1024 * 1024
MIN_TEXT_CHARS_PER_PAGE = 30

ALLOWED_TAGS = {
    "p", "br", "h1", "h2", "h3", "h4", "h5", "h6", "strong", "em", "b", "i", "u", "s", "sup", "sub", "ul", "ol",
    "li", "a", "table", "thead", "tbody", "tr", "td", "th", "blockquote",
}


class Rejected(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code, self.message = code, message


def limit_resources() -> None:
    import resource

    for which, value in ((resource.RLIMIT_CPU, CPU_SECONDS), (resource.RLIMIT_AS, MEMORY_BYTES),
                         (resource.RLIMIT_FSIZE, 0)):
        # Not every limit is supported everywhere (e.g. RLIMIT_AS on macOS); Linux containers enforce all three.
        with contextlib.suppress(ValueError, OSError):
            resource.setrlimit(which, (value, value))


# ---- PDF -------------------------------------------------------------------------------------------------


def extract_pdf(data: bytes, max_pages: int) -> dict[str, Any]:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise Rejected("encrypted", "This PDF is password-protected. Save an unlocked copy (for example, "
                                        "print it to PDF) and upload that.")
        pages = len(reader.pages)
    except PdfReadError:
        raise Rejected("unreadable", "This PDF looks damaged. Export it again and upload the new copy.") from None
    if pages == 0:
        raise Rejected("unreadable", "This PDF has no pages.")
    if pages > max_pages:
        raise Rejected("too_many_pages", f"This PDF has {pages} pages. Résumé imports are limited to {max_pages}.")
    texts = []
    for page in reader.pages:
        try:
            texts.append(page.extract_text() or "")
        except Exception:  # noqa: BLE001  (one bad page shouldn't stop the import; the model still sees it)
            texts.append("")
    text = "\n\n".join(t.strip() for t in texts).strip()
    has_text = len(re.sub(r"\s", "", text)) >= MIN_TEXT_CHARS_PER_PAGE * pages
    return {"kind": "pdf", "pages": pages, "hasTextLayer": has_text, "text": text if has_text else ""}


# ---- DOCX ------------------------------------------------------------------------------------------------


def check_parts(data: bytes, max_bytes: int) -> None:
    """Reject DTDs (no legitimate DOCX part has one) and enforce the real, not declared, unpacked size."""
    total = 0
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for entry in archive.infolist():
            with archive.open(entry) as handle:
                while chunk := handle.read(1 << 20):
                    total += len(chunk)
                    if total > max_bytes:
                        raise Rejected("too_large", "This Word file is too large once unpacked.")
                    if entry.filename.endswith((".xml", ".rels")) and (b"<!DOCTYPE" in chunk or b"<!ENTITY" in chunk):
                        raise Rejected("unsafe", "This Word file contains content we don't accept. Save it again "
                                                 "from Word and upload the new copy.")


def _paragraph_line(paragraph: Any) -> str | None:
    text = paragraph.text.strip()
    if not text:
        return None
    style = (paragraph.style.name if paragraph.style is not None else "") or ""
    p_pr = paragraph._p.pPr  # noqa: SLF001
    if style == "Title" or style.startswith("Heading"):
        text = f"# {text}"
    elif "List" in style or (p_pr is not None and p_pr.numPr is not None):
        text = f"- {text}"
    links = [h.url for h in paragraph.hyperlinks if h.url and h.url not in text]
    return f"{text} <{', '.join(links)}>" if links else text


def _table_lines(table: Any) -> list[str]:
    lines = []
    for row in table.rows:
        cells: list[str] = []
        for cell in row.cells:
            value = " / ".join(filter(None, (_paragraph_line(p) for p in cell.paragraphs)))
            if value and (not cells or cells[-1] != value):  # merged cells repeat; keep one
                cells.append(value)
        if cells:
            lines.append(" | ".join(cells))
    return lines


def _block_lines(container: Any) -> list[str]:
    """Paragraphs and tables in reading order, with any text box right after the paragraph it's anchored in."""
    from docx.table import Table

    lines: list[str] = []
    for block in container.iter_inner_content():
        if isinstance(block, Table):
            lines.extend(_table_lines(block))
        else:
            line = _paragraph_line(block)
            if line:
                lines.append(line)
            lines.extend(_text_box_lines(block._p, container))  # noqa: SLF001
    return lines


def _text_box_lines(element: Any, parent: Any) -> list[str]:
    """Paragraphs in text boxes, which ``iter_inner_content`` doesn't reach. ``parent`` supplies styles."""
    from docx.text.paragraph import Paragraph
    from lxml import etree

    w = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    lines = []
    for box in etree.XPath(".//w:txbxContent", namespaces=w)(element):
        if etree.XPath("ancestor::*[local-name()='Fallback']")(box):  # VML fallback repeats the DrawingML box
            continue
        for p in etree.XPath(".//w:p", namespaces=w)(box):
            line = _paragraph_line(Paragraph(p, parent))
            if line:
                lines.append(line)
    return lines


def extract_docx(data: bytes, max_bytes: int) -> dict[str, Any]:
    import docx
    import mammoth
    import nh3

    check_parts(data, max_bytes)
    try:
        document = docx.Document(io.BytesIO(data))
    except Exception:  # noqa: BLE001  (python-docx raises many types for malformed packages)
        raise Rejected("unreadable", "This Word file looks damaged. Open it in Word, save it again, and upload "
                                     "the new copy.") from None

    def unique(lines: list[str], seen: set[str]) -> list[str]:
        out = [line for line in lines if line not in seen]
        seen.update(out)
        return out

    seen: set[str] = set()
    headers: list[str] = []
    footers: list[str] = []
    for section in document.sections:
        for part in (section.first_page_header, section.header, section.even_page_header):
            if not part.is_linked_to_previous:
                headers += unique(_block_lines(part), seen)
        for part in (section.first_page_footer, section.footer, section.even_page_footer):
            if not part.is_linked_to_previous:
                footers += unique(_block_lines(part), seen)
    body = _block_lines(document)

    sections = [("Header", headers), ("", body), ("Footer", footers)]
    text = "\n\n".join(
        (f"[{name}]\n" if name else "") + "\n".join(lines) for name, lines in sections if lines
    )

    def no_images(_image: Any) -> dict[str, str]:
        return {}

    converted = mammoth.convert_to_html(io.BytesIO(data), convert_image=mammoth.images.img_element(no_images))
    html = nh3.clean(converted.value, tags=ALLOWED_TAGS, attributes={"a": {"href"}, "td": {"colspan", "rowspan"},
                                                                       "th": {"colspan", "rowspan"}},
                     url_schemes={"http", "https", "mailto"}, link_rel="noopener noreferrer nofollow")
    return {"kind": "docx", "text": text, "html": html}


# ---- entry point -----------------------------------------------------------------------------------------------


def main() -> None:
    limit_resources()
    kind, max_pages, max_bytes = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
    data = sys.stdin.buffer.read()
    try:
        result = extract_pdf(data, max_pages) if kind == "pdf" else extract_docx(data, max_bytes)
    except Rejected as exc:
        result = {"error": exc.code, "message": exc.message}
    except MemoryError:
        result = {"error": "too_large", "message": "This file needs too much memory to read."}
    sys.stdout.write(json.dumps(result))


if __name__ == "__main__":
    main()
