"""Encryption of the API key at rest. The Fernet key is derived from `SECRET_KEY`, so a copy of
the database alone doesn't reveal the key (rotating `DJANGO_SECRET_KEY` means entering it again)."""

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings


def _fernet() -> Fernet:
    digest = hashlib.sha256(f"ai-settings:{settings.SECRET_KEY}".encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt(token: str) -> str:
    """The stored key, or "" when there is none or it can't be read with the current secret."""
    if not token:
        return ""
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        return ""
