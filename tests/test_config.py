"""Tests for ``comadre.config`` — only custom validators / business rules.

Lean by design (test-suite review 2026-04-25): per-field default + env-var
read tests collapsed away — those are pydantic-settings framework
guarantees. What survives are the custom validator bodies (Fernet,
IANA timezone, backup passphrase length, pocket language, voice-ref
bounds) plus the LRU cache.
"""

from __future__ import annotations

import pytest
from pydantic import SecretStr, ValidationError

from comadre.config import Settings, get_settings


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> None:
    get_settings.cache_clear()


def test_settings_loads_env_vars_and_defaults(
    monkeypatch: pytest.MonkeyPatch, fernet_key: str
) -> None:
    """One smoke confirming env-var pickup + defaults wire through."""
    monkeypatch.setenv("KEY_REGISTRY_ENCRYPTION_KEY", fernet_key)
    monkeypatch.setenv("DEFAULT_VOICE", "pocket/galvani")
    monkeypatch.setenv("PORT", "9000")

    s = Settings()
    assert s.default_voice == "pocket/galvani"
    assert s.port == 9000
    # Defaults wire through.
    assert s.pocket_model_path == "models/pocket-tts/portuguese/model.safetensors"
    assert s.billing_timezone == "UTC"


def test_v2_engine_fields_are_gone(
    monkeypatch: pytest.MonkeyPatch, fernet_key: str
) -> None:
    """v3 removed the v2 engine surface — no kokoro/qwen/espeak fields."""
    monkeypatch.setenv("KEY_REGISTRY_ENCRYPTION_KEY", fernet_key)
    s = Settings()
    for removed in (
        "espeak_data_path",
        "kokoro_model_path",
        "kokoro_voices_path",
        "qwen3_enabled",
        "qwen3_cli_path",
        "qwen3_model_path",
        "qwen3_tokenizer_path",
        "qwen3_threads",
        "kokoro_model_url",
        "kokoro_voices_url",
        "qwen3_model_url",
        "qwen3_tokenizer_url",
    ):
        assert not hasattr(s, removed), f"removed field still present: {removed}"


def test_pocket_language_validator(
    monkeypatch: pytest.MonkeyPatch, fernet_key: str
) -> None:
    """POCKET_LANGUAGE accepts only portuguese / portuguese_24l."""
    monkeypatch.setenv("KEY_REGISTRY_ENCRYPTION_KEY", fernet_key)
    for value in ("portuguese", "portuguese_24l"):
        monkeypatch.setenv("POCKET_LANGUAGE", value)
        assert Settings().pocket_language == value
    monkeypatch.setenv("POCKET_LANGUAGE", "english")
    with pytest.raises(ValidationError, match="POCKET_LANGUAGE"):
        Settings()


def test_voice_ref_bounds_validator(
    monkeypatch: pytest.MonkeyPatch, fernet_key: str
) -> None:
    """VOICE_REF_MAX_SECONDS must be >= VOICE_REF_MIN_SECONDS."""
    monkeypatch.setenv("KEY_REGISTRY_ENCRYPTION_KEY", fernet_key)
    monkeypatch.setenv("VOICE_REF_MIN_SECONDS", "10")
    monkeypatch.setenv("VOICE_REF_MAX_SECONDS", "5")
    with pytest.raises(ValidationError, match="VOICE_REF_MAX_SECONDS"):
        Settings()


def test_missing_encryption_key_raises_validation_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """KEY_REGISTRY_ENCRYPTION_KEY is required-no-default."""
    monkeypatch.delenv("KEY_REGISTRY_ENCRYPTION_KEY", raising=False)
    with pytest.raises(ValidationError):
        Settings()


def test_malformed_fernet_key_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """The validator rejects bad Fernet shapes."""
    monkeypatch.setenv("KEY_REGISTRY_ENCRYPTION_KEY", "not-a-fernet-key")
    with pytest.raises(ValidationError) as exc_info:
        Settings()
    assert "Fernet" in str(exc_info.value)


def test_invalid_iana_timezone_rejected(
    monkeypatch: pytest.MonkeyPatch, fernet_key: str
) -> None:
    """``BILLING_TIMEZONE`` must be IANA — typos like ``BRT`` or
    ``America/Sao-Paulo`` (hyphen) fail closed at boot."""
    monkeypatch.setenv("KEY_REGISTRY_ENCRYPTION_KEY", fernet_key)
    monkeypatch.setenv("BILLING_TIMEZONE", "America/Sao-Paulo")
    with pytest.raises(ValidationError):
        Settings()


def test_short_backup_passphrase_rejected_empty_accepted(
    monkeypatch: pytest.MonkeyPatch, fernet_key: str
) -> None:
    """Empty passphrase accepted at boot (deferred-bootstrap OK);
    < 16 chars rejected."""
    monkeypatch.setenv("KEY_REGISTRY_ENCRYPTION_KEY", fernet_key)
    monkeypatch.setenv("BACKUP_PASSPHRASE", "")
    s = Settings()
    assert s.backup_passphrase == SecretStr("")  # empty allowed

    monkeypatch.setenv("BACKUP_PASSPHRASE", "too-short")
    with pytest.raises(ValidationError):
        Settings()


def test_get_settings_is_lru_cached_returns_same_instance(
    monkeypatch: pytest.MonkeyPatch, fernet_key: str
) -> None:
    monkeypatch.setenv("KEY_REGISTRY_ENCRYPTION_KEY", fernet_key)
    a = get_settings()
    b = get_settings()
    assert a is b
