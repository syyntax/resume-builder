"""Prefixed, time-sortable identifiers (ULIDs), e.g. ``usr_01j9z3k8c4w5x6y7z8a9b0c1d2``."""

from __future__ import annotations

import os
import time

_CROCKFORD = "0123456789abcdefghjkmnpqrstvwxyz"


def ulid() -> str:
    """Return a 26-character lowercase ULID: 48-bit millisecond timestamp + 80 random bits."""
    value = ((int(time.time() * 1000) & ((1 << 48) - 1)) << 80) | int.from_bytes(os.urandom(10), "big")
    chars = []
    for _ in range(26):
        chars.append(_CROCKFORD[value & 31])
        value >>= 5
    return "".join(reversed(chars))


def new_id(prefix: str) -> str:
    return f"{prefix}_{ulid()}"
