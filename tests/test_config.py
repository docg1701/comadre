"""Tests for the configuration module."""

import pytest
from pydantic import ValidationError

from cumadre.config import Settings, get_settings


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> None:
    """Clear the cached settings before each test."""
    get_settings.cache_clear()


class TestSettings:
    """Tests for the Settings class."""

    def test_loads_from_environment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("API_KEY", "test-key-123")
        monkeypatch.setenv("DEFAULT_VOICE", "alloy")
        monkeypatch.setenv("WORKERS", "4")
        monkeypatch.setenv("PORT", "9000")

        settings = Settings()

        assert settings.api_key.get_secret_value() == "test-key-123"
        assert settings.default_voice == "alloy"
        assert settings.workers == 4
        assert settings.port == 9000

    def test_missing_api_key_raises_validation_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("API_KEY", raising=False)
        with pytest.raises(ValidationError) as exc_info:
            Settings()
        errors = exc_info.value.errors()
        assert any(e["type"] == "missing" for e in errors)

    def test_default_values(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("API_KEY", "test-key")

        settings = Settings()

        assert settings.default_voice == "default"
        assert settings.workers == 1
        assert settings.port == 8000

    def test_case_insensitive_env_vars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("api_key", "lower-case-key")

        settings = Settings()

        assert settings.api_key.get_secret_value() == "lower-case-key"

    def test_api_key_masked_in_repr(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("API_KEY", "super-secret-key")

        settings = Settings()

        assert "super-secret-key" not in repr(settings)
        assert "super-secret-key" not in str(settings)

    def test_empty_api_key_raises_validation_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("API_KEY", "")
        with pytest.raises(ValidationError):
            Settings()

    def test_workers_rejects_zero(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("API_KEY", "test-key")
        monkeypatch.setenv("WORKERS", "0")
        with pytest.raises(ValidationError):
            Settings()

    def test_workers_rejects_negative(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("API_KEY", "test-key")
        monkeypatch.setenv("WORKERS", "-1")
        with pytest.raises(ValidationError):
            Settings()

    def test_port_rejects_zero(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("API_KEY", "test-key")
        monkeypatch.setenv("PORT", "0")
        with pytest.raises(ValidationError):
            Settings()

    def test_port_rejects_above_65535(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("API_KEY", "test-key")
        monkeypatch.setenv("PORT", "65536")
        with pytest.raises(ValidationError):
            Settings()

    def test_espeak_data_path_defaults_to_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("API_KEY", "test-key")
        monkeypatch.delenv("ESPEAK_DATA_PATH", raising=False)
        settings = Settings()
        assert settings.espeak_data_path is None

    def test_espeak_data_path_accepts_env_var(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("API_KEY", "test-key")
        monkeypatch.setenv("ESPEAK_DATA_PATH", "/custom/espeak-ng-data")
        settings = Settings()
        assert settings.espeak_data_path == "/custom/espeak-ng-data"

    def test_kokoro_model_path_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("API_KEY", "test-key")
        settings = Settings()
        assert settings.kokoro_model_path == "models/kokoro-v1.0.onnx"

    def test_kokoro_model_path_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("API_KEY", "test-key")
        monkeypatch.setenv("KOKORO_MODEL_PATH", "/opt/models/kokoro.onnx")
        settings = Settings()
        assert settings.kokoro_model_path == "/opt/models/kokoro.onnx"

    def test_kokoro_voices_path_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("API_KEY", "test-key")
        settings = Settings()
        assert settings.kokoro_voices_path == "models/voices-v1.0.bin"

    def test_kokoro_voices_path_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("API_KEY", "test-key")
        monkeypatch.setenv("KOKORO_VOICES_PATH", "/opt/models/voices.bin")
        settings = Settings()
        assert settings.kokoro_voices_path == "/opt/models/voices.bin"


class TestGetSettings:
    """Tests for the get_settings cached function."""

    def test_returns_settings_instance(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("API_KEY", "cached-key")

        result = get_settings()

        assert isinstance(result, Settings)
        assert result.api_key.get_secret_value() == "cached-key"

    def test_returns_cached_instance(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("API_KEY", "cached-key")

        first = get_settings()
        second = get_settings()

        assert first is second
