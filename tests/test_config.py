"""Tests for the configuration module."""

import pytest
from pydantic import ValidationError

from comadre.config import Settings, get_settings


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> None:
    """Clear the cached settings before each test."""
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _default_encryption_key(monkeypatch: pytest.MonkeyPatch, fernet_key: str) -> None:
    """Provide a valid ``KEY_REGISTRY_ENCRYPTION_KEY`` by default.

    Every ``Settings()`` construction requires the field. Tests that want
    to exercise the "missing" branch override this via
    ``monkeypatch.delenv`` inside the test body.
    """
    monkeypatch.setenv("KEY_REGISTRY_ENCRYPTION_KEY", fernet_key)


class TestSettings:
    """Tests for the Settings class."""

    def test_loads_from_environment(
        self, monkeypatch: pytest.MonkeyPatch, fernet_key: str
    ) -> None:
        monkeypatch.setenv("KEY_REGISTRY_ENCRYPTION_KEY", fernet_key)
        monkeypatch.setenv("DEFAULT_VOICE", "kokoro/pf_dora")
        monkeypatch.setenv("PORT", "9000")

        settings = Settings()

        assert settings.default_voice == "kokoro/pf_dora"
        assert settings.port == 9000

    def test_default_values(
        self, monkeypatch: pytest.MonkeyPatch, fernet_key: str
    ) -> None:
        monkeypatch.setenv("KEY_REGISTRY_ENCRYPTION_KEY", fernet_key)

        settings = Settings()

        assert settings.default_voice == "kokoro/pm_santa"
        assert settings.port == 8000

    def test_port_rejects_zero(
        self, monkeypatch: pytest.MonkeyPatch, fernet_key: str
    ) -> None:
        monkeypatch.setenv("KEY_REGISTRY_ENCRYPTION_KEY", fernet_key)
        monkeypatch.setenv("PORT", "0")
        with pytest.raises(ValidationError):
            Settings()

    def test_port_rejects_above_65535(
        self, monkeypatch: pytest.MonkeyPatch, fernet_key: str
    ) -> None:
        monkeypatch.setenv("KEY_REGISTRY_ENCRYPTION_KEY", fernet_key)
        monkeypatch.setenv("PORT", "65536")
        with pytest.raises(ValidationError):
            Settings()

    def test_espeak_data_path_defaults_to_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("ESPEAK_DATA_PATH", raising=False)
        settings = Settings()
        assert settings.espeak_data_path is None

    def test_espeak_data_path_accepts_env_var(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ESPEAK_DATA_PATH", "/custom/espeak-ng-data")
        settings = Settings()
        assert settings.espeak_data_path == "/custom/espeak-ng-data"

    def test_kokoro_model_path_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        settings = Settings()
        assert settings.kokoro_model_path == "models/kokoro-v1.0.onnx"

    def test_kokoro_model_path_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("KOKORO_MODEL_PATH", "/opt/models/kokoro.onnx")
        settings = Settings()
        assert settings.kokoro_model_path == "/opt/models/kokoro.onnx"

    def test_kokoro_voices_path_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        settings = Settings()
        assert settings.kokoro_voices_path == "models/voices-v1.0.bin"

    def test_kokoro_voices_path_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("KOKORO_VOICES_PATH", "/opt/models/voices.bin")
        settings = Settings()
        assert settings.kokoro_voices_path == "/opt/models/voices.bin"

    def test_qwen3_cli_path_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        settings = Settings()
        assert settings.qwen3_cli_path == "/usr/local/bin/qwen3-tts-cli"

    def test_qwen3_cli_path_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("QWEN3_CLI_PATH", "/opt/bin/qwen3-tts-cli")
        settings = Settings()
        assert settings.qwen3_cli_path == "/opt/bin/qwen3-tts-cli"

    def test_qwen3_model_path_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        settings = Settings()
        assert settings.qwen3_model_path == "models/qwen3-tts-0.6b-q8_0.gguf"

    def test_qwen3_model_path_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("QWEN3_MODEL_PATH", "/opt/models/qwen3.gguf")
        settings = Settings()
        assert settings.qwen3_model_path == "/opt/models/qwen3.gguf"

    def test_qwen3_tokenizer_path_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings = Settings()
        assert settings.qwen3_tokenizer_path == "models/qwen3-tts-tokenizer-f16.gguf"

    def test_qwen3_tokenizer_path_from_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("QWEN3_TOKENIZER_PATH", "/opt/models/tokenizer.gguf")
        settings = Settings()
        assert settings.qwen3_tokenizer_path == "/opt/models/tokenizer.gguf"

    def test_voices_dir_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        settings = Settings()
        assert settings.voices_dir == "/voices"

    def test_voices_dir_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("VOICES_DIR", "/custom/voices")
        settings = Settings()
        assert settings.voices_dir == "/custom/voices"

    def test_voices_dir_rejects_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("VOICES_DIR", "")
        with pytest.raises(ValidationError):
            Settings()

    def test_qwen3_enabled_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        settings = Settings()
        assert settings.qwen3_enabled is True

    def test_qwen3_enabled_from_env_false(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("QWEN3_ENABLED", "false")
        settings = Settings()
        assert settings.qwen3_enabled is False

    def test_qwen3_threads_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        settings = Settings()
        assert settings.qwen3_threads == 4

    def test_qwen3_threads_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("QWEN3_THREADS", "8")
        settings = Settings()
        assert settings.qwen3_threads == 8

    def test_noise_dir_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        settings = Settings()
        assert settings.noise_dir == "/app/noise"

    def test_noise_dir_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NOISE_DIR", "/custom/noise")
        settings = Settings()
        assert settings.noise_dir == "/custom/noise"

    def test_noise_dir_rejects_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NOISE_DIR", "")
        with pytest.raises(ValidationError):
            Settings()

    def test_qwen3_threads_rejects_zero(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("QWEN3_THREADS", "0")
        with pytest.raises(ValidationError):
            Settings()

    def test_kokoro_model_url_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        settings = Settings()
        assert "kokoro-v1.0.onnx" in settings.kokoro_model_url

    def test_kokoro_model_url_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("KOKORO_MODEL_URL", "https://custom/model.onnx")
        settings = Settings()
        assert settings.kokoro_model_url == "https://custom/model.onnx"

    def test_qwen3_model_url_default_empty(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings = Settings()
        assert settings.qwen3_model_url == ""

    def test_qwen3_model_url_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("QWEN3_MODEL_URL", "https://hf.co/model.gguf")
        settings = Settings()
        assert settings.qwen3_model_url == "https://hf.co/model.gguf"

    def test_invalid_kokoro_model_url_rejected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("KOKORO_MODEL_URL", "not-a-url")
        with pytest.raises(ValidationError):
            Settings()

    def test_invalid_qwen3_model_url_rejected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("QWEN3_MODEL_URL", "ftp://bad-scheme")
        with pytest.raises(ValidationError):
            Settings()

    def test_empty_qwen3_url_allowed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("QWEN3_MODEL_URL", "")
        settings = Settings()
        assert settings.qwen3_model_url == ""


class TestRegistrySettings:
    """Tests for the key-registry fields and validator (2026-04-18: registry-only)."""

    def test_key_registry_db_path_default(
        self, monkeypatch: pytest.MonkeyPatch, fernet_key: str
    ) -> None:
        monkeypatch.setenv("KEY_REGISTRY_ENCRYPTION_KEY", fernet_key)
        settings = Settings()
        assert settings.key_registry_db_path == "./data/keys/registry.db"

    def test_key_registry_db_path_from_env(
        self, monkeypatch: pytest.MonkeyPatch, fernet_key: str
    ) -> None:
        monkeypatch.setenv("KEY_REGISTRY_ENCRYPTION_KEY", fernet_key)
        monkeypatch.setenv("KEY_REGISTRY_DB_PATH", "/srv/keys/r.db")
        settings = Settings()
        assert settings.key_registry_db_path == "/srv/keys/r.db"

    def test_operator_contact_hint_default(
        self, monkeypatch: pytest.MonkeyPatch, fernet_key: str
    ) -> None:
        monkeypatch.setenv("KEY_REGISTRY_ENCRYPTION_KEY", fernet_key)
        settings = Settings()
        assert "operator" in settings.operator_contact_hint.lower()

    def test_billing_day_default(
        self, monkeypatch: pytest.MonkeyPatch, fernet_key: str
    ) -> None:
        monkeypatch.setenv("KEY_REGISTRY_ENCRYPTION_KEY", fernet_key)
        settings = Settings()
        assert settings.billing_day == 5

    def test_billing_day_rejects_zero(
        self, monkeypatch: pytest.MonkeyPatch, fernet_key: str
    ) -> None:
        monkeypatch.setenv("KEY_REGISTRY_ENCRYPTION_KEY", fernet_key)
        monkeypatch.setenv("BILLING_DAY", "0")
        with pytest.raises(ValidationError):
            Settings()

    def test_billing_day_rejects_above_28(
        self, monkeypatch: pytest.MonkeyPatch, fernet_key: str
    ) -> None:
        monkeypatch.setenv("KEY_REGISTRY_ENCRYPTION_KEY", fernet_key)
        monkeypatch.setenv("BILLING_DAY", "29")
        with pytest.raises(ValidationError):
            Settings()

    def test_billing_timezone_default(
        self, monkeypatch: pytest.MonkeyPatch, fernet_key: str
    ) -> None:
        monkeypatch.setenv("KEY_REGISTRY_ENCRYPTION_KEY", fernet_key)
        settings = Settings()
        assert settings.billing_timezone == "America/Sao_Paulo"

    def test_encryption_key_missing_rejected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """2.0.0: KEY_REGISTRY_ENCRYPTION_KEY is required (no default)."""
        monkeypatch.delenv("KEY_REGISTRY_ENCRYPTION_KEY", raising=False)
        with pytest.raises(ValidationError) as exc_info:
            Settings()
        assert "key_registry_encryption_key" in str(exc_info.value).lower()

    def test_encryption_key_rejects_malformed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("KEY_REGISTRY_ENCRYPTION_KEY", "not-a-fernet-key")
        with pytest.raises(ValidationError) as exc_info:
            Settings()
        errors = exc_info.value.errors()
        assert any(
            "KEY_REGISTRY_ENCRYPTION_KEY" in err.get("msg", "") for err in errors
        )
        for err in errors:
            assert "not-a-fernet-key" not in err.get("msg", "")

    def test_encryption_key_accepts_valid(
        self, monkeypatch: pytest.MonkeyPatch, fernet_key: str
    ) -> None:
        monkeypatch.setenv("KEY_REGISTRY_ENCRYPTION_KEY", fernet_key)
        settings = Settings()
        assert settings.key_registry_encryption_key is not None


class TestGetSettings:
    """Tests for the get_settings cached function."""

    def test_returns_settings_instance(
        self, monkeypatch: pytest.MonkeyPatch, fernet_key: str
    ) -> None:
        monkeypatch.setenv("KEY_REGISTRY_ENCRYPTION_KEY", fernet_key)

        result = get_settings()

        assert isinstance(result, Settings)

    def test_returns_cached_instance(
        self, monkeypatch: pytest.MonkeyPatch, fernet_key: str
    ) -> None:
        monkeypatch.setenv("KEY_REGISTRY_ENCRYPTION_KEY", fernet_key)

        first = get_settings()
        second = get_settings()

        assert first is second
