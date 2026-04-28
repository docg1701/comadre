"""Application configuration via environment variables."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from cryptography.fernet import Fernet
from pydantic import Field, HttpUrl, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _project_env_file() -> Path:
    """Resolve `.env` relative to the project root, not CWD.

    Walks upward from this module until it finds the directory containing
    `pyproject.toml` (same heuristic used by `uv`, `poetry`, `pipenv`). When
    `comadre-keys` runs from an arbitrary operator CWD, anchoring to the
    project root prevents a stray `.env` from silently overriding the at-rest
    encryption key. When installed as a wheel the pyproject.toml lookup fails
    and no `.env` is loaded — deployments must set env vars explicitly (which
    they already do via compose / systemd).
    """
    for ancestor in Path(__file__).resolve().parents:
        if (ancestor / "pyproject.toml").is_file():
            return ancestor / ".env"
    return Path(".env")


_MODEL_CONFIG = SettingsConfigDict(
    case_sensitive=False,
    env_file=_project_env_file(),
    env_file_encoding="utf-8",
    extra="ignore",
)


class RegistrySettings(BaseSettings):
    """Registry, billing, and operator-contact configuration.

    F33 — split out from ``Settings`` so the ``comadre-keys`` CLI loads
    only the surface it actually consumes. The CLI never touches Kokoro /
    Qwen3 / voices / noise paths; routing it through this narrower model
    means a host that has not yet configured the TTS side (e.g. an
    operator running ``comadre-keys issue-key`` from a fresh checkout
    before deploying the FastAPI app) does not trip URL validators or
    inherit defaults that pretend to mean something.

    ``Settings`` extends this class to add the TTS-runtime surface — the
    FastAPI app reads everything from a single ``Settings`` instance, so
    no consumer is forced to load both. ``extra="ignore"`` on the model
    config means ``RegistrySettings()`` silently skips any TTS-side env
    vars the operator happens to have set; the values are still picked
    up by the FastAPI app via ``get_settings()``.
    """

    model_config = _MODEL_CONFIG

    key_registry_db_path: str = Field(
        default="./data/keys/registry.db",
        min_length=1,
        description=("SQLite key registry path. Created with mode 0600 on first use."),
    )
    key_registry_encryption_key: SecretStr = Field(
        ...,
        description=(
            "Fernet key for encrypting tax IDs at rest. Required — generate "
            'with `python -c "from cryptography.fernet import Fernet; '
            'print(Fernet.generate_key().decode())"`.'
        ),
    )
    backup_passphrase: SecretStr = Field(
        default=SecretStr(""),
        description=(
            "Passphrase for AES-256 encryption of nightly backup tarballs. "
            "Consumed only by the backup/restore ansible playbooks; NOT read "
            "by the FastAPI app or any comadre-keys CLI verb. Must be at "
            "least 16 characters when set; empty is accepted at service boot "
            "so a deployment that has not yet run bootstrap.yml with "
            "COMADRE_BACKUP_PASSPHRASE exported can still start the auth path."
        ),
    )
    operator_contact_hint: str = Field(
        default="Contact your Comadre operator for billing.",
        description="Operator contact string shown in CLI error hints.",
    )
    billing_day: int = Field(
        default=5,
        ge=1,
        le=28,
        description="Day-of-month for billing sweeps (1-28 to avoid month-end).",
    )
    billing_timezone: str = Field(
        default="UTC",
        min_length=1,
        description=(
            "IANA timezone used for billing-day calculations and the daily "
            "suspension sweep's day-boundary. Default UTC for operator-neutral "
            "predictability across international deployments; override per "
            "deployment (e.g. America/Sao_Paulo) and communicate the chosen "
            "zone to customers contractually since it governs when paid_until "
            "expires and API keys flip to 401."
        ),
    )

    @field_validator("key_registry_encryption_key")
    @classmethod
    def _validate_fernet_key_shape(cls, v: SecretStr) -> SecretStr:
        """Reject malformed Fernet keys without echoing the raw value.

        Runs on the already-coerced `SecretStr`, so pydantic's error rendering
        masks the input as `**********` — AC5/NFR16 anti-enumeration guarantee
        for the key value itself. The field itself is required (no default),
        so pydantic handles the missing-value case before this runs.
        """
        try:
            Fernet(v.get_secret_value().encode())
        except (ValueError, TypeError) as exc:
            raise ValueError(
                "KEY_REGISTRY_ENCRYPTION_KEY must be a valid Fernet key"
            ) from exc
        return v

    @field_validator("billing_timezone")
    @classmethod
    def _validate_iana_timezone(cls, v: str) -> str:
        """Reject non-IANA timezone strings at config load time.

        Without this, a typo like ``America/Sao-Paulo`` or ``BRT`` silently
        desyncs the runtime BILLING_TIMEZONE from the cron's CRON_TZ — see
        the CLAUDE.md gotcha. Failing fast at boot makes the misconfiguration
        immediately operator-visible.
        """
        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(
                f"BILLING_TIMEZONE {v!r} is not a valid IANA timezone "
                "(e.g. UTC, America/Sao_Paulo, Europe/Lisbon)"
            ) from exc
        return v

    @field_validator("backup_passphrase")
    @classmethod
    def _validate_backup_passphrase_length(cls, v: SecretStr) -> SecretStr:
        """Accept empty (deferred-bootstrap OK) or length >= 16 chars.

        Empty-at-boot is by design (Story 4.3): the passphrase is consumed
        only by the backup/restore playbooks, not the FastAPI app or any
        CLI verb. Forcing it to be required at boot would make the upgrade
        path chicken-and-egg (service won't start → can't run bootstrap →
        service won't start). The playbooks themselves enforce the length
        check via ``ansible.builtin.assert``.
        """
        secret = v.get_secret_value()
        if secret and len(secret) < 16:
            raise ValueError(
                "BACKUP_PASSPHRASE must be at least 16 characters when set; "
                "leave empty to defer configuration until bootstrap.yml runs "
                "with COMADRE_BACKUP_PASSPHRASE exported."
            )
        return v


class Settings(RegistrySettings):
    """Full application settings — registry surface plus TTS runtime.

    Consumed by the FastAPI app and any code path that needs both the
    registry/billing fields and the engine/voices/noise/port fields.
    The ``comadre-keys`` CLI uses ``RegistrySettings`` directly via
    ``get_registry_settings()``.
    """

    default_voice: str = "kokoro/pm_santa"
    port: int = Field(default=8000, ge=1, le=65535)
    espeak_data_path: str | None = Field(
        default=None,
        description="Override bundled espeak-ng data path",
    )
    kokoro_model_path: str = Field(
        default="models/kokoro-v1.0.onnx",
        description="Path to the Kokoro ONNX model file",
    )
    kokoro_voices_path: str = Field(
        default="models/voices-v1.0.bin",
        description="Path to the Kokoro voices binary file",
    )
    qwen3_enabled: bool = Field(
        default=True,
        description=(
            "Enable Qwen3 engine (set false on hosts where the binary is"
            " unavailable, e.g. aarch64). When false, Qwen3 model download,"
            " load, and warm-up are skipped at startup, and qwen/* voices"
            " are excluded from the available list."
        ),
    )
    qwen3_cli_path: str = Field(
        default="/usr/local/bin/qwen3-tts-cli",
        description="Path to the qwen3-tts-cli binary",
    )
    qwen3_model_path: str = Field(
        default="models/qwen3-tts-0.6b-q8_0.gguf",
        description="Path to the Qwen3 TTS Q8_0 model file",
    )
    qwen3_tokenizer_path: str = Field(
        default="models/qwen3-tts-tokenizer-f16.gguf",
        description="Path to the Qwen3 TTS tokenizer file",
    )
    voices_dir: str = Field(
        default="/voices",
        min_length=1,
        description="Base directory for voice files (kokoro/ and qwen/ subdirs)",
    )
    noise_dir: str = Field(
        default="/app/noise",
        min_length=1,
        description="Directory containing room/hiss noise WAV files",
    )
    qwen3_threads: int = Field(
        default=4,
        ge=1,
        description="Number of CPU threads for Qwen3 inference",
    )
    kokoro_model_url: str = Field(
        default=(
            "https://github.com/thewh1teagle/kokoro-onnx/releases/download/"
            "model-files-v1.0/kokoro-v1.0.onnx"
        ),
        description="URL to download Kokoro ONNX model",
    )
    kokoro_voices_url: str = Field(
        default=(
            "https://github.com/thewh1teagle/kokoro-onnx/releases/download/"
            "model-files-v1.0/voices-v1.0.bin"
        ),
        description="URL to download Kokoro voices binary",
    )
    # Per-IP rate limits — pre-auth gates on /health and /v1/audio/speech.
    # When all legitimate clients share a small set of IPs (NAT, office proxy),
    # raise these to avoid false 429s. Set to "999999/minute" to effectively
    # disable a gate. The per-key limit (rate_limit_rpm per API key) is the
    # primary enforcement for authenticated traffic.
    per_ip_health_rate_limit: str = Field(
        default="60/minute",
        description="Per-IP rate limit for GET /health (unauthenticated endpoint)",
    )
    per_ip_speech_rate_limit: str = Field(
        default="600/minute",
        description=(
            "Per-IP rate limit for POST /v1/audio/speech pre-auth gate. "
            "Runs before verify_api_key to bound token-spray attacks."
        ),
    )
    qwen3_model_url: str = Field(
        default="",
        description="URL to download Qwen3 GGUF model (empty = skip auto-download)",
    )
    qwen3_tokenizer_url: str = Field(
        default="",
        description="URL to download Qwen3 tokenizer GGUF (empty = skip auto-download)",
    )

    @field_validator(
        "per_ip_health_rate_limit",
        "per_ip_speech_rate_limit",
    )
    @classmethod
    def _validate_rate_limit_format(cls, v: str) -> str:
        """Accept any non-empty string; the limits library parses it at runtime.

        Invalid formats (e.g. ``"abc"``) raise from ``limits.parse()`` inside
        ``_check_per_ip_bucket`` and fail-closed (429) rather than failing
        open, so the operator sees the misconfiguration immediately.
        """
        if not v or not v.strip():
            raise ValueError("Per-IP rate limit must not be empty")
        return v.strip()

    @field_validator(
        "kokoro_model_url",
        "kokoro_voices_url",
        "qwen3_model_url",
        "qwen3_tokenizer_url",
    )
    @classmethod
    def validate_url_format(cls, v: str) -> str:
        """Validate URL format at config load time.

        Empty string is allowed for optional URLs (skip download).
        """
        if v == "":
            return v
        HttpUrl(v)
        return v


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached full application settings (TTS + registry surface)."""
    return Settings()


@lru_cache(maxsize=1)
def get_registry_settings() -> RegistrySettings:
    """Return cached registry-only settings for ``comadre-keys`` CLI.

    F33 — narrower load surface than ``get_settings()``. Reads the same
    ``.env`` (or process env), but excludes TTS-runtime fields entirely,
    so a host without Kokoro/Qwen3 paths configured can still issue keys,
    run billing reports, and operate the registry.
    """
    return RegistrySettings()
