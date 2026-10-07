"""Password hashing (Argon2id) and policy (NIST SP 800-63B style: length + blocklist, no composition rules)."""

from __future__ import annotations

from functools import cache
from pathlib import Path

from argon2 import PasswordHasher, profiles
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

MIN_LENGTH = 12
MAX_LENGTH = 128

_hasher = PasswordHasher.from_parameters(profiles.RFC_9106_LOW_MEMORY)
_dummy_hash: str | None = None


def configure(profile: str) -> None:
    """Select the Argon2 parameters. ``cheapest`` exists only to keep the test suite fast."""
    global _hasher, _dummy_hash
    params = profiles.CHEAPEST if profile == "cheapest" else profiles.RFC_9106_LOW_MEMORY
    _hasher = PasswordHasher.from_parameters(params)
    _dummy_hash = None


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(stored_hash: str, password: str) -> tuple[bool, str | None]:
    """Return (matches, upgraded_hash). ``upgraded_hash`` is set when the parameters have changed."""
    try:
        _hasher.verify(stored_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False, None
    if _hasher.check_needs_rehash(stored_hash):
        return True, _hasher.hash(password)
    return True, None


def dummy_verify(password: str) -> None:
    """Spend the same time as a real verification so unknown emails can't be detected by timing."""
    global _dummy_hash
    if _dummy_hash is None:
        _dummy_hash = _hasher.hash("timing-equalization-placeholder")
    verify_password(_dummy_hash, password)


@cache
def _blocklist() -> frozenset[str]:
    path = Path(__file__).with_name("common_passwords.txt")
    lines = path.read_text(encoding="utf-8").splitlines()
    return frozenset(line.strip() for line in lines if line.strip() and not line.startswith("#"))


def policy_errors(password: str, *, email: str = "", display_name: str = "") -> list[str]:
    """Human-readable reasons the password is not acceptable (empty list = OK)."""
    errors: list[str] = []
    if len(password) < MIN_LENGTH:
        errors.append(f"Use at least {MIN_LENGTH} characters.")
    if len(password) > MAX_LENGTH:
        errors.append(f"Use at most {MAX_LENGTH} characters.")
    lowered = password.lower()
    if lowered in _blocklist():
        errors.append("This password is too common. Choose something less predictable.")
    elif len(set(lowered)) <= 2:
        errors.append("This password is too repetitive.")
    personal = []
    if email:
        local = email.split("@", 1)[0].lower()
        personal += [email.lower(), local]
    if display_name:
        personal += [part.lower() for part in display_name.split()]
    if any(len(p) >= 4 and p in lowered for p in personal):
        errors.append("Don't include your name or email address in your password.")
    return errors
