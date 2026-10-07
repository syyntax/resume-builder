"""Identify uploaded résumés by their content, never by file name or declared type (DESIGN.md §10.5).

Only the ZIP central directory and `[Content_Types].xml` are read here, in the app process. Everything
that decompresses or parses document content happens in the sandboxed worker (`app.importers.worker`).
"""

from __future__ import annotations

import io
import zipfile
from typing import Literal

MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_PAGES = 10
MAX_TEXT_CHARS = 50_000
MAX_ZIP_ENTRIES = 1_000
MAX_UNCOMPRESSED_BYTES = 50 * 1024 * 1024

SourceKind = Literal["pdf", "docx", "text"]
_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


class ImportRejected(Exception):
    """A file we won't import, with a message the user can act on."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code, self.message = code, message


def sniff(data: bytes) -> Literal["pdf", "docx"]:
    if not data:
        raise ImportRejected("empty", "The file is empty.")
    if len(data) > MAX_FILE_BYTES:
        raise ImportRejected("too_large", "The file is larger than 5 MB.")
    if b"%PDF-" in data[:1024]:
        return "pdf"
    if data.startswith(b"PK\x03\x04"):
        check_docx_container(data)
        return "docx"
    if data.startswith(_OLE_MAGIC):
        raise ImportRejected("unsupported", "Older .doc files aren't supported. Save it as .docx or PDF and "
                                            "upload that.")
    raise ImportRejected("unsupported", "Upload a PDF or Word (.docx) file. For anything else, paste the text "
                                        "instead.")


def check_docx_container(data: bytes) -> None:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
        entries = archive.infolist()
    except (zipfile.BadZipFile, ValueError):
        raise ImportRejected("unreadable", "This file looks damaged. Open it in Word, save it again, and "
                                           "upload the new copy.") from None
    names = {entry.filename for entry in entries}
    if "word/document.xml" not in names:
        raise ImportRejected("unsupported", "Upload a PDF or Word (.docx) file. Other Office files, such as "
                                            "spreadsheets or slides, aren't supported.")
    if len(entries) > MAX_ZIP_ENTRIES or sum(e.file_size for e in entries) > MAX_UNCOMPRESSED_BYTES:
        raise ImportRejected("too_large", "This Word file is too large once unpacked.")
    content_types = b""
    if "[Content_Types].xml" in names:
        with archive.open("[Content_Types].xml") as handle:
            content_types = handle.read(1_048_576)
    if "word/vbaProject.bin" in names or b"macroEnabled" in content_types:
        raise ImportRejected("macros", "Files with macros (.docm) aren't accepted. Save it as a regular .docx "
                                       "(Word Document) and upload that.")
