"""Run the extraction worker in a subprocess and turn its output into an `Extraction`."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from app.importers.sniff import MAX_PAGES, MAX_UNCOMPRESSED_BYTES, ImportRejected

WALL_SECONDS = 30
_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_UNREADABLE = "We couldn't read this file safely. Export it again (or save it as PDF) and upload the new copy."


@dataclass
class Extraction:
    kind: Literal["pdf", "docx", "text"]
    text: str  # the source text for the fidelity check ("" for scanned PDFs)
    pages: int | None = None
    has_text_layer: bool = True
    html: str | None = None  # DOCX preview, sanitized

    def as_json(self) -> dict[str, object]:
        return {"kind": self.kind, "text": self.text, "pages": self.pages, "hasTextLayer": self.has_text_layer,
                "html": self.html}

    @classmethod
    def from_json(cls, data: dict[str, object]) -> Extraction:
        return cls(kind=data["kind"], text=str(data.get("text") or ""), pages=data.get("pages"),  # type: ignore[arg-type]
                   has_text_layer=bool(data.get("hasTextLayer", True)), html=data.get("html"))  # type: ignore[arg-type]


def _worker_env() -> dict[str, str]:
    # A clean environment: the worker needs no configuration, and must never see secrets.
    return {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPATH": str(_BACKEND_ROOT), "LANG": "C.UTF-8"}


async def extract(kind: Literal["pdf", "docx"], data: bytes) -> Extraction:
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "app.importers.worker", kind, str(MAX_PAGES), str(MAX_UNCOMPRESSED_BYTES),
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        cwd=_BACKEND_ROOT, env=_worker_env(),
    )
    try:
        out, _ = await asyncio.wait_for(process.communicate(data), timeout=WALL_SECONDS)
    except TimeoutError:
        process.kill()
        await process.wait()
        raise ImportRejected("timeout", "This file took too long to read. Export it again, or save it as PDF, "
                                        "and upload the new copy.") from None
    if process.returncode != 0:  # killed by a resource limit, or crashed
        raise ImportRejected("unreadable", _UNREADABLE)
    try:
        result = json.loads(out)
    except json.JSONDecodeError:
        raise ImportRejected("unreadable", _UNREADABLE) from None
    if "error" in result:
        raise ImportRejected(result["error"], result.get("message") or _UNREADABLE)
    return Extraction.from_json(result)
