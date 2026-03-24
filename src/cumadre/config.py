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


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached application settings instance."""
    return Settings()
