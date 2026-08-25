"""Shared helpers for extracting user-facing messages from ValidationError.

Leading-underscore module name signals "CLI-internal, not a public API" —
same convention used by ``_reset_for_tests`` in ``output.py``.
"""

from __future__ import annotations

from pydantic import ValidationError


def first_error_msg(exc: ValidationError) -> str:
    """Return the first sub-error message with the offending field, or a fallback.

    Example outputs:
        "api_key: Field required"
        "key_registry_db_path: Path does not exist"
    Falls back to the bare message if no field location is available.
    """
    errors = exc.errors()
    if not errors:
        return "Check the input values."
    first = errors[0]
    msg = str(first.get("msg", "Check the input values."))
    loc = first.get("loc", ())
    if loc:
        field = ".".join(str(part) for part in loc)
        return f"{field}: {msg}"
    return msg


def is_missing_encryption_key(exc: ValidationError) -> bool:
    """Return True when the ValidationError is specifically about the encryption key.

    Matches either the custom model-level validator message or a direct
    ``key_registry_encryption_key`` field error.
    """
    for err in exc.errors():
        loc = err.get("loc", ())
        if loc and loc[0] == "key_registry_encryption_key":
            return True
        msg = str(err.get("msg", ""))
        if "KEY_REGISTRY_ENCRYPTION_KEY" in msg:
            return True
    return False


def validate_single_line(
    value: str, *, field: str, max_len: int, hint: str | None = None
) -> str:
    """Validate that *value* is a single-line string without NUL/C0 controls.

    Returns the stripped value. Raises ``ValueError(message)`` with a
    caller-supplied *hint* tuple via ``(message, hint)`` so Typer sites can
    ``except ValueError as e: render_error(*e.args); raise Exit(2)`` without
    duplicating the NUL/newline/length ladder. Used by all CLI single-line
    free-text flags (notes, reason).
    """
    # ponytail: one shared ladder for 10+ CLI flags; add when a new flag needs it.
    if "\x00" in value:
        raise ValueError(f"{field} must not contain NUL bytes")
    if "\n" in value or "\r" in value:
        raise ValueError(f"{field} must be a single line")
    stripped = value.strip()
    if not stripped:
        raise ValueError(f"{field} must not be empty or whitespace-only")
    if len(stripped) > max_len:
        raise ValueError(f"{field} exceeds {max_len} characters")
    if any(ord(ch) < 0x20 and ch not in ("\t",) for ch in stripped):
        raise ValueError(f"{field} contains illegal control characters")
    return stripped
