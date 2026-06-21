"""Token vault — Fernet symmetric encryption for OAuth tokens at rest.

In production set TOKEN_ENCRYPTION_KEY (any strong secret; a key is derived from it).
A fixed dev key is used otherwise so the app runs locally — never ship without one.
"""
from __future__ import annotations

import base64
import hashlib
import logging

from cryptography.fernet import Fernet, InvalidToken

from ..config import settings

log = logging.getLogger("copilot.crypto")


def _derive_key(secret: str) -> bytes:
    return base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())


if settings.token_encryption_key:
    _fernet = Fernet(_derive_key(settings.token_encryption_key))
else:
    log.warning("TOKEN_ENCRYPTION_KEY not set — using an insecure dev key. Do not use in production.")
    _fernet = Fernet(_derive_key("copilot-dev-insecure-key"))


def encrypt(plaintext: str | None) -> str | None:
    if not plaintext:
        return None
    return _fernet.encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str | None) -> str | None:
    if not ciphertext:
        return None
    try:
        return _fernet.decrypt(ciphertext.encode()).decode()
    except InvalidToken:
        log.error("Failed to decrypt a stored token (key rotated?)")
        return None
