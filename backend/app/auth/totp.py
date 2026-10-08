"""TOTP multi-factor authentication (RFC 6238; DESIGN.md §8.2) and recovery codes.

Codes are 6 digits over 30-second steps with HMAC-SHA1, as every authenticator app expects. A code is accepted
within one step either side (clock drift) and only for a step later than the last one used, so a code can't be
replayed. Secrets are stored encrypted (app.secrets) and bound to the user's id.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote, urlencode

DIGITS = 6
STEP_SECONDS = 30
DRIFT_STEPS = 1
RECOVERY_CODES = 10
_RECOVERY_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"  # no 0/o, 1/l/i: easy to copy by hand


def new_secret() -> str:
    """160 random bits, base32 (what authenticator apps take), without padding."""
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def _key(secret: str) -> bytes:
    return base64.b32decode(secret + "=" * (-len(secret) % 8), casefold=True)


def code_at(secret: str, step: int) -> str:
    digest = hmac.new(_key(secret), struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(value % 10**DIGITS).zfill(DIGITS)


def current_step(now: float | None = None) -> int:
    return int((time.time() if now is None else now) // STEP_SECONDS)


def verify(secret: str, code: str, *, last_step: int | None, now: float | None = None) -> int | None:
    """The step the code matches (to store as the last one used), or None. Spaces and dashes are ignored."""
    code = code.replace(" ", "").replace("-", "")
    if len(code) != DIGITS or not code.isdigit():
        return None
    step = current_step(now)
    for candidate in range(step - DRIFT_STEPS, step + DRIFT_STEPS + 1):
        if last_step is not None and candidate <= last_step:
            continue  # already used: no replay
        if hmac.compare_digest(code_at(secret, candidate), code):
            return candidate
    return None


def otpauth_uri(secret: str, account: str, issuer: str = "Resume Tailor") -> str:
    label = quote(f"{issuer}:{account}")
    query = urlencode({"secret": secret, "issuer": issuer, "algorithm": "SHA1", "digits": DIGITS,
                       "period": STEP_SECONDS})
    return f"otpauth://totp/{label}?{query}"


def new_recovery_codes() -> list[str]:
    """Ten single-use codes like "k7mq-2xpa-9d" (50 random bits each)."""
    codes = []
    for _ in range(RECOVERY_CODES):
        raw = "".join(secrets.choice(_RECOVERY_ALPHABET) for _ in range(10))
        codes.append(f"{raw[:4]}-{raw[4:8]}-{raw[8:]}")
    return codes


def hash_recovery_code(code: str) -> str:
    """Codes are random, so a plain hash is enough; normalized so case and dashes don't matter."""
    normalized = code.strip().lower().replace("-", "").replace(" ", "")
    return hashlib.sha256(normalized.encode("ascii", "ignore")).hexdigest()
