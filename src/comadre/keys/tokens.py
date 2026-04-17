"""Plaintext key generation, hashing, and prefix extraction.

Lives in its own module (not db.py) because Story 2.1's auth path will
import `hash_api_key` to hash inbound Bearer tokens. CLI (this story)
imports `generate_api_key_plaintext` + `key_prefix_from_plaintext` +
`hash_api_key`; the auth path will import only `hash_api_key`. Keeping
the module dep-free (stdlib only) prevents circular imports when
`auth.py` is added.
"""

from __future__ import annotations

import hashlib
import secrets

API_KEY_PREFIX = "cmdr_live_"
# First 8 chars AFTER the fixed `cmdr_live_` prefix — the unique part.
API_KEY_PREFIX_STORED_LEN = 8


def generate_api_key_plaintext() -> str:
    """Return a fresh plaintext API key: ``cmdr_live_`` + 43-char token.

    ``secrets.token_urlsafe(32)`` returns 43 URL-safe base64 characters
    without padding, so the full plaintext is 53 chars.
    """
    return f"{API_KEY_PREFIX}{secrets.token_urlsafe(32)}"


def hash_api_key(plaintext: str) -> str:
    """Return lowercase hex SHA-256 digest of the plaintext.

    Always ``.hexdigest()`` (never raw bytes) — the DB stores this in a
    ``TEXT UNIQUE`` column and Story 2.1's auth path must hash inbound
    Bearer tokens identically.
    """
    return hashlib.sha256(plaintext.encode("ascii")).hexdigest()


def key_prefix_from_plaintext(plaintext: str) -> str:
    """Return the 8-char public prefix after the fixed ``cmdr_live_`` tag."""
    start = len(API_KEY_PREFIX)
    return plaintext[start : start + API_KEY_PREFIX_STORED_LEN]
