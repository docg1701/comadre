"""Application configuration via environment variables."""

from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        case_sensitive=False,
    )

    api_key: SecretStr = Field(min_length=1)
    default_voice: str = "default"
    workers: int = Field(default=1, ge=1)
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
    clone_reference_path: str | None = Field(
        default=None,
        description="Path to clone reference WAV for Qwen3 voice cloning",
    )
    qwen3_female_reference_path: str = Field(
        default="voices/female-reference.wav",
        description="Path to bundled female reference WAV for Qwen3",
    )
    qwen3_male_reference_path: str = Field(
        default="voices/male-reference.wav",
        description="Path to bundled male reference WAV for Qwen3",
    )
    qwen3_threads: int = Field(
        default=4,
        ge=1,
        description="Number of CPU threads for Qwen3 inference",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached application settings instance."""
    return Settings()
