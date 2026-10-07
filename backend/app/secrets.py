"""Encryption for secrets stored in the database (users' API keys; later TOTP secrets).

AES-256-GCM with a key derived (HKDF-SHA256) from APP_SECRET_KEY, a random 96-bit nonce per record, and the
owning user's id as associated data, so a ciphertext copied onto another user's row fails to decrypt. Each
record stores a fingerprint of the secret it was encrypted under, which lets `resume-tailor keys rotate`
re-encrypt everything after APP_SECRET_KEY changes (DESIGN.md §8.6).
"""

from __future__ import annotations

import hashlib
import hmac
import os
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


class DecryptionError(Exception):
    """The ciphertext can't be decrypted with the available secret(s)."""


def fingerprint(secret: bytes) -> str:
    return hmac.new(secret, b"resume-tailor/secret-fingerprint", hashlib.sha256).hexdigest()[:16]


def _derive(secret: bytes, purpose: str) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=f"resume-tailor/{purpose}/v1".encode()).derive(
        secret
    )


@dataclass(frozen=True)
class Sealed:
    ciphertext: bytes
    nonce: bytes
    key_fingerprint: str


class SecretBox:
    def __init__(self, secret: bytes, purpose: str, *, previous: bytes | None = None) -> None:
        self._current = (fingerprint(secret), AESGCM(_derive(secret, purpose)))
        self._previous = (fingerprint(previous), AESGCM(_derive(previous, purpose))) if previous else None

    @property
    def current_fingerprint(self) -> str:
        return self._current[0]

    def seal(self, plaintext: str, *, bound_to: str) -> Sealed:
        nonce = os.urandom(12)
        ciphertext = self._current[1].encrypt(nonce, plaintext.encode("utf-8"), bound_to.encode("utf-8"))
        return Sealed(ciphertext=ciphertext, nonce=nonce, key_fingerprint=self._current[0])

    def open(self, sealed: Sealed, *, bound_to: str) -> str:
        candidates = [self._current] + ([self._previous] if self._previous else [])
        for fp, aead in candidates:
            if fp != sealed.key_fingerprint:
                continue
            try:
                return aead.decrypt(sealed.nonce, sealed.ciphertext, bound_to.encode("utf-8")).decode("utf-8")
            except InvalidTag:
                raise DecryptionError("ciphertext failed authentication") from None
        raise DecryptionError("encrypted with an unknown APP_SECRET_KEY")
