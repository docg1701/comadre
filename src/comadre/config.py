"""Application configuration via environment variables."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from cryptography.fernet import Fernet
from pydantic import Field, SecretStr, field_validator, model_validator
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

    F33 — split out from Settings so the comadre-keys CLI loads
    only the surface it actually consumes. The CLI never touches the TTS
    engine / noise paths; routing it through this narrower model means a
    host that has not yet configured the TTS side (e.g. an operator
    running comadre-keys issue-key from a fresh checkout before
    deploying the FastAPI app) does not inherit defaults that pretend to
    mean something.

    v3 exception to the F33 CLI-never-touches-voices invariant: the
    LGPD data-subject operations (export-customer voice listing and
    delete-customer --hard voice purge) read voices_dir — stored
    clones are biometric personal data under LGPD and must be exported
    and purged alongside the registry rows.

    Settings extends this class to add the TTS-runtime surface — the
    FastAPI app reads everything from a single Settings instance, so
    no consumer is forced to load both. extra=ignore on the model
    config means RegistrySettings() silently skips any TTS-side env
    vars the operator happens to have set; the values are still picked
    up by the FastAPI app via get_settings().
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
            "with: python -c 'from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())'."
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
    voices_dir: str = Field(
        default="/voices",
        min_length=1,
        description=(
            "Base directory for voice files (pocket/ subdir). Consumed by "
            "the LGPD data-subject operations: export-customer lists the "
            "customer's stored clones, delete-customer --hard purges them."
        ),
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

        Runs on the already-coerced SecretStr, so pydantic's error rendering
        masks the input as ********** — AC5/NFR16 anti-enumeration guarantee
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

        Without this, a typo like America/Sao-Paulo or BRT silently
        desyncs the runtime BILLING_TIMEZONE from the cron's CRON_TZ — see
        the AGENTS.md gotcha. Failing fast at boot makes the misconfiguration
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
        path chicken-and-egg (service won't start, can't run bootstrap,
        service won't start). The playbooks themselves enforce the length
        check via ansible.builtin.assert.
        """
        secret = v.get_secret_value()
        if secret and len(secret) < 16:
            raise ValueError(
                "BACKUP_PASSPHRASE must be at least 16 characters when set; "
                "leave empty to defer configuration until bootstrap.yml runs "
                "with COMADRE_BACKUP_PASSPHRASE exported."
            )
        return v


_POCKET_LANGUAGES = frozenset({"portuguese", "portuguese_24l"})


class Settings(RegistrySettings):
    """Full application settings — registry surface plus TTS runtime.

    Consumed by the FastAPI app and any code path that needs both the
    registry/billing fields and the engine/voices/noise/port fields.
    The comadre-keys CLI uses RegistrySettings directly via
    get_registry_settings().

    v3 — single-engine surface: pocket-tts is the only TTS. All fields
    below are pocket-tts or voice-cloning configuration; the v2 dual-engine
    fields were removed in 3.0.0.
    """

    default_voice: str = "pocket/rafael"
    port: int = Field(default=8000, ge=1, le=65535)
    pocket_language: str = Field(
        default="portuguese",
        description="Pocket TTS language variant: portuguese or portuguese_24l.",
    )
    pocket_config_path: str = Field(
        default="models/pocket-tts-config/portuguese.yaml",
        description="Pocket TTS config YAML (baked in image, local paths)",
    )
    pocket_model_path: str = Field(
        default="models/pocket-tts/portuguese/model.safetensors",
        description="Pocket TTS flow-LM + Mimi model weights",
    )
    pocket_tokenizer_path: str = Field(
        default="models/pocket-tts/portuguese/tokenizer.model",
        description="Pocket TTS sentencepiece tokenizer",
    )
    pocket_default_voice_path: str = Field(
        default="models/pocket-tts/portuguese/embeddings/rafael.safetensors",
        description="Default catalog voice state (rafael)",
    )
    pocket_threads: int = Field(
        default=4,
        ge=1,
        description="CPU threads applied via torch.set_num_threads",
    )
    pocket_quantize: bool = Field(
        default=False,
        description="Apply int8 quantization (torchao) to attention + FFN layers",
    )
    pocket_temperature: float = Field(
        default=0.7,
        ge=0,
        description="Generation temperature (the pocket-tts default)",
    )
    pocket_sigla_spacing: bool = Field(
        default=True,
        description=(
            "Apply expand_siglas (spaced letters, e.g. CNPJ -> C N P J) "
            "before generation. The sigla pronunciation lever for pocket-tts."
        ),
    )
    voice_upload_max_mb: int = Field(
        default=10,
        ge=1,
        le=50,
        description="Maximum upload size in MB for voice-clone audio files",
    )
    voice_ref_min_seconds: int = Field(
        default=3,
        ge=1,
        description="Minimum reference-audio duration in seconds (reject below)",
    )
    voice_ref_max_seconds: int = Field(
        default=30,
        ge=1,
        description=(
            "Maximum reference-audio duration in seconds. The library "
            "truncates at 30 s (truncate=True); this must be >= min."
        ),
    )
    voice_ephemeral_idle_ttl_seconds: int = Field(
        default=3600,
        description="Ephemeral clone idle TTL (swept when unused longer)",
    )
    voice_ephemeral_absolute_ttl_seconds: int = Field(
        default=86400,
        description="Ephemeral clone absolute TTL (swept regardless of use)",
    )
    voice_ephemeral_max_per_key: int = Field(
        default=5,
        description="Maximum ephemeral clones per API key",
    )
    voice_ephemeral_global_max: int = Field(
        default=50,
        description="Global LRU cap for ephemeral clones across all keys",
    )
    voice_stored_max_per_customer: int = Field(
        default=20,
        description="Maximum stored (persisted) clones per customer",
    )
    noise_dir: str = Field(
        default="/app/noise",
        min_length=1,
        description="Directory containing room/hiss noise WAV files",
    )
    # Per-IP rate limits — pre-auth gates on /health, /v1/audio/speech and
    # POST /v1/voices. When all legitimate clients share a small set of IPs
    # (NAT, office proxy), raise these to avoid false 429s. Set to
    # 999999/minute to effectively disable a gate. The per-key limit
    # (rate_limit_rpm per API key) is the primary enforcement for
    # authenticated traffic.
    per_ip_health_rate_limit: str = Field(
        default="60/minute",
        description="Per-IP rate limit for GET /health (unauthenticated endpoint)",
    )
    per_ip_speech_rate_limit: str = Field(
        default="600/minute",
        description=(
            "Per-IP rate limit for POST /v1/audio/speech and POST /v1/voices "
            "pre-auth gates. Runs before verify_api_key to bound token-spray attacks."
        ),
    )

    @field_validator("pocket_language")
    @classmethod
    def _validate_pocket_language(cls, v: str) -> str:
        """Restrict the language variant to the two supported values."""
        if v not in _POCKET_LANGUAGES:
            raise ValueError(
                f"POCKET_LANGUAGE {v!r} is not supported; "
                "use one of: portuguese, portuguese_24l"
            )
        return v

    @model_validator(mode="after")
    def _validate_voice_ref_bounds(self) -> Settings:
        """Enforce VOICE_REF_MAX_SECONDS >= VOICE_REF_MIN_SECONDS."""
        if self.voice_ref_max_seconds < self.voice_ref_min_seconds:
            raise ValueError(
                "VOICE_REF_MAX_SECONDS must be >= VOICE_REF_MIN_SECONDS "
                f"(got max={self.voice_ref_max_seconds}, "
                f"min={self.voice_ref_min_seconds})"
            )
        return self

    @field_validator(
        "per_ip_health_rate_limit",
        "per_ip_speech_rate_limit",
    )
    @classmethod
    def _validate_rate_limit_format(cls, v: str) -> str:
        """Accept any non-empty string; the limits library parses it at runtime.

        Invalid formats raise from limits.parse() inside
        _check_per_ip_bucket and fail-closed (429) rather than failing
        open, so the operator sees the misconfiguration immediately.
        """
        if not v or not v.strip():
            raise ValueError("Per-IP rate limit must not be empty")
        return v.strip()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached full application settings (TTS + registry surface)."""
    return Settings()


@lru_cache(maxsize=1)
def get_registry_settings() -> RegistrySettings:
    """Return cached registry-only settings for comadre-keys CLI.

    F33 — narrower load surface than get_settings(). Reads the same
    .env (or process env), but excludes TTS-runtime fields entirely,
    so a host without pocket-tts paths configured can still issue keys,
    run billing reports, and operate the registry.
    """
    return RegistrySettings()
