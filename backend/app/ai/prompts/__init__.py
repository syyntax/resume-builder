"""Versioned prompt files. Each starts with `<!-- version: N -->`; calls record `name@N`."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path

_DIR = Path(__file__).parent
_VERSION = re.compile(r"^<!--\s*version:\s*(\d+)\s*-->\s*\n", re.MULTILINE)


@dataclass(frozen=True)
class Prompt:
    name: str
    version: int
    text: str

    @property
    def tag(self) -> str:
        return f"{self.name}@{self.version}"


@cache
def load(name: str) -> Prompt:
    raw = (_DIR / f"{name}.md").read_text(encoding="utf-8")
    match = _VERSION.match(raw)
    if not match:
        raise ValueError(f"prompt {name}.md is missing its version header")
    return Prompt(name=name, version=int(match.group(1)), text=raw[match.end():].strip())
