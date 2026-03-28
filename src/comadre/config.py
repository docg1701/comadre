"""Application configuration via environment variables."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, HttpUrl, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        case_sensitive=False,
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
    qwen3_model_url: str = Field(
        default="",
        description="URL to download Qwen3 GGUF model (empty = skip auto-download)",
    )
    qwen3_tokenizer_url: str = Field(
        default="",
        description="URL to download Qwen3 tokenizer GGUF (empty = skip auto-download)",
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


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached application settings instance."""
    return Settings()
