"""Application configuration via environment variables."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Self

from cryptography.fernet import Fernet
from pydantic import Field, HttpUrl, SecretStr, field_validator, model_validator
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


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        case_sensitive=False,
        env_file=_project_env_file(),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    api_key: SecretStr = Field(min_length=1)
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
    rate_limit_speech: str = Field(
        default="30/minute",
        description="Rate limit for speech endpoint (per client IP)",
    )
    rate_limit_health: str = Field(
        default="60/minute",
        description="Rate limit for health endpoint (per client IP)",
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
    qwen3_model_url: str = Field(
        default="",
        description="URL to download Qwen3 GGUF model (empty = skip auto-download)",
    )
    qwen3_tokenizer_url: str = Field(
        default="",
        description="URL to download Qwen3 tokenizer GGUF (empty = skip auto-download)",
    )

    monetization_enabled: bool = Field(
        default=False,
        description=(
            "Enable monetization features (dynamic per-key rate limiting, "
            "billing sweeps, suspension)."
        ),
    )
    key_registry_db_path: str = Field(
        default="./data/keys/registry.db",
        min_length=1,
        description=("SQLite key registry path. Created with mode 0600 on first use."),
    )
    key_registry_encryption_key: SecretStr | None = Field(
        default=None,
        description=(
            "Fernet key for encrypting tax IDs at rest. Required when "
            "monetization_enabled=True. Generate with "
            "Fernet.generate_key().decode()."
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
        default="America/Sao_Paulo",
        min_length=1,
        description="IANA timezone for billing calculations.",
    )

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

    @field_validator("key_registry_encryption_key")
    @classmethod
    def _validate_fernet_key_shape(cls, v: SecretStr | None) -> SecretStr | None:
        """Reject malformed Fernet keys without echoing the raw value.

        Runs on the already-coerced `SecretStr`, so pydantic's error rendering
        masks the input as `**********` — AC5/NFR16 anti-enumeration guarantee
        for the key value itself. Mandatory-when-enabled check runs in the
        model validator below.
        """
        if v is None:
            return v
        try:
            Fernet(v.get_secret_value().encode())
        except (ValueError, TypeError) as exc:
            raise ValueError(
                "KEY_REGISTRY_ENCRYPTION_KEY must be a valid Fernet key"
            ) from exc
        return v

    @model_validator(mode="after")
    def _validate_encryption_key_when_monetization_enabled(self) -> Self:
        """Require the encryption key when monetization is on."""
        if self.monetization_enabled and self.key_registry_encryption_key is None:
            raise ValueError(
                "KEY_REGISTRY_ENCRYPTION_KEY is required when "
                "MONETIZATION_ENABLED=true and must be a valid Fernet key"
            )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached application settings instance."""
    return Settings()
