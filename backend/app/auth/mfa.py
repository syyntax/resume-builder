"""Two-step verification (TOTP) for an account: the encrypted secret, checking codes, and recovery codes."""

from __future__ import annotations

import io

import segno
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import totp
from app.config import Settings
from app.db.models import RecoveryCode, User
from app.db.types import utcnow
from app.secrets import Sealed, SecretBox

PURPOSE = "totp-secret"


def secret_box(settings: Settings) -> SecretBox:
    return SecretBox(settings.secret_key(), PURPOSE, previous=settings.previous_secret_key())


def store_secret(user: User, secret: str, settings: Settings) -> None:
    sealed = secret_box(settings).seal(secret, bound_to=user.id)
    user.totp_ciphertext, user.totp_nonce, user.totp_key_fingerprint = (sealed.ciphertext, sealed.nonce,
                                                                         sealed.key_fingerprint)
    user.totp_last_step = None


def read_secret(user: User, settings: Settings) -> str | None:
    if not user.totp_ciphertext or not user.totp_nonce or not user.totp_key_fingerprint:
        return None
    return secret_box(settings).open(Sealed(user.totp_ciphertext, user.totp_nonce, user.totp_key_fingerprint),
                                     bound_to=user.id)


def qr_svg(uri: str) -> str:
    """The otpauth URI as an SVG QR code, for authenticator apps to scan."""
    out = io.BytesIO()
    segno.make(uri, error="m").save(out, kind="svg", scale=5, border=2, xmldecl=False, svgns=True,
                                    dark="#0f172a", light="#ffffff")
    return out.getvalue().decode("utf-8")


async def check_code(db: AsyncSession, user: User, code: str, settings: Settings) -> str | None:
    """"totp" or "recovery" when the code is good (and is now used up), or None."""
    code = code.strip()
    if any(c.isalpha() for c in code):  # recovery codes have letters, authenticator codes don't
        wanted = totp.hash_recovery_code(code)
        row = (await db.execute(select(RecoveryCode).where(
            RecoveryCode.user_id == user.id, RecoveryCode.code_hash == wanted,
            RecoveryCode.used_at.is_(None)))).scalar_one_or_none()
        if row is None:
            return None
        row.used_at = utcnow()
        return "recovery"
    secret = read_secret(user, settings)
    step = totp.verify(secret, code, last_step=user.totp_last_step) if secret else None
    if step is None:
        return None
    user.totp_last_step = step
    return "totp"


async def new_recovery_codes(db: AsyncSession, user: User) -> list[str]:
    """Replace any recovery codes with ten new ones; returns them (shown once, stored hashed)."""
    await db.execute(delete(RecoveryCode).where(RecoveryCode.user_id == user.id))
    codes = totp.new_recovery_codes()
    now = utcnow()
    for code in codes:
        db.add(RecoveryCode(user_id=user.id, code_hash=totp.hash_recovery_code(code), created_at=now))
    return codes


async def recovery_codes_left(db: AsyncSession, user: User) -> int:
    rows = await db.execute(select(RecoveryCode.id).where(RecoveryCode.user_id == user.id,
                                                          RecoveryCode.used_at.is_(None)))
    return len(rows.all())


async def turn_off(db: AsyncSession, user: User) -> None:
    user.mfa_enabled = False
    user.totp_ciphertext = user.totp_nonce = user.totp_key_fingerprint = None
    user.totp_last_step = None
    await db.execute(delete(RecoveryCode).where(RecoveryCode.user_id == user.id))
