"""Tests for EngineRouter voice routing and unified API."""

import io
import wave
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from comadre.exceptions import InvalidRequestError, VoiceNotFoundError
from comadre.service import (
    EngineRouter,
    KokoroEngine,
    QwenEngine,
)


def _create_ref_wav(path: Path, duration_s: int = 5) -> None:
    """Create a valid reference WAV file at the given path."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(b"\x00\x00" * 16000 * duration_s)
    path.write_bytes(buf.getvalue())


@pytest.fixture()
def kokoro() -> KokoroEngine:
    """Return a KokoroEngine with mocked internals."""
    engine = KokoroEngine()
    mock = MagicMock()
    mock.get_voices.return_value = ["pm_santa", "pf_dora", "pm_alex"]
    mock.get_voice_style.return_value = np.zeros((510, 1, 256), dtype=np.float32)
    engine._kokoro = mock
    return engine


@pytest.fixture()
def qwen() -> QwenEngine:
    """Return a QwenEngine with mocked internals."""
    engine = QwenEngine()
    engine._loaded = True
    engine._cli_path = "/usr/local/bin/qwen3-tts-cli"
    engine._model_path = "models/qwen3-tts-0.6b-q8_0.gguf"
    return engine


@pytest.fixture()
def voices_dir(tmp_path: Path) -> Path:
    """Create voices directory with kokoro/ and qwen/ subdirs and test files."""
    kokoro_dir = tmp_path / "kokoro"
    kokoro_dir.mkdir()
    qwen_dir = tmp_path / "qwen"
    qwen_dir.mkdir()

    # Create a custom kokoro voice .npy file
    custom_voice = np.zeros((510, 1, 256), dtype=np.float32)
    np.save(kokoro_dir / "custom_voice.npy", custom_voice)

    # Create qwen reference WAVs
    _create_ref_wav(qwen_dir / "female-reference.wav")
    _create_ref_wav(qwen_dir / "male-reference.wav")

    return tmp_path


@pytest.fixture()
def router(kokoro: KokoroEngine, qwen: QwenEngine, voices_dir: Path) -> EngineRouter:
    """Return an EngineRouter with both mocked engines and test voices dir."""
    return EngineRouter(kokoro, qwen, voices_dir)


# --- Voice parsing ---


class TestParseVoice:
    def test_parses_kokoro_voice(self, router: EngineRouter) -> None:
        engine, name = router._parse_voice("kokoro/pm_santa")
        assert engine == "kokoro"
        assert name == "pm_santa"

    def test_parses_qwen_voice(self, router: EngineRouter) -> None:
        engine, name = router._parse_voice("qwen/galvani")
        assert engine == "qwen"
        assert name == "galvani"

    def test_rejects_no_slash(self, router: EngineRouter) -> None:
        with pytest.raises(InvalidRequestError, match="Invalid voice format"):
            router._parse_voice("santa")

    def test_rejects_unknown_engine(self, router: EngineRouter) -> None:
        with pytest.raises(InvalidRequestError, match="Unknown engine prefix"):
            router._parse_voice("chatterbox/voice")

    def test_rejects_empty_name(self, router: EngineRouter) -> None:
        with pytest.raises(InvalidRequestError, match="Invalid voice format"):
            router._parse_voice("kokoro/")

    def test_rejects_path_traversal(self, router: EngineRouter) -> None:
        with pytest.raises(InvalidRequestError, match="Invalid voice name"):
            router._parse_voice("kokoro/../etc/passwd")

    def test_rejects_special_chars(self, router: EngineRouter) -> None:
        with pytest.raises(InvalidRequestError, match="Invalid voice name"):
            router._parse_voice("kokoro/voice.npy")

    def test_allows_hyphens_and_underscores(self, router: EngineRouter) -> None:
        _engine, name = router._parse_voice("qwen/my-voice_01")
        assert name == "my-voice_01"


# --- Kokoro voice resolution ---


class TestResolveKokoroVoice:
    def test_resolves_builtin_voice(self, router: EngineRouter) -> None:
        """Built-in voices from .npz work without .npy files."""
        voice = router._resolve_kokoro_voice("pm_santa")
        assert isinstance(voice, np.ndarray)

    def test_resolves_custom_npy_file(self, router: EngineRouter) -> None:
        """Custom .npy files in voices/kokoro/ take precedence."""
        voice = router._resolve_kokoro_voice("custom_voice")
        assert isinstance(voice, np.ndarray)

    def test_unknown_voice_raises(self, router: EngineRouter) -> None:
        with pytest.raises(VoiceNotFoundError) as exc_info:
            router._resolve_kokoro_voice("nonexistent")
        assert "kokoro/nonexistent" in str(exc_info.value)


# --- Qwen voice resolution ---


class TestResolveQwenVoice:
    def test_resolves_existing_wav(self, router: EngineRouter) -> None:
        path = router._resolve_qwen_voice("female-reference")
        assert path.is_file()
        assert path.name == "female-reference.wav"

    def test_missing_wav_raises(self, router: EngineRouter) -> None:
        with pytest.raises(VoiceNotFoundError) as exc_info:
            router._resolve_qwen_voice("nonexistent")
        assert "qwen/nonexistent" in str(exc_info.value)


# --- generate_speech dispatching ---


class TestGenerateSpeechDispatch:
    def test_kokoro_voice_dispatches_to_kokoro(
        self, router: EngineRouter, kokoro: KokoroEngine
    ) -> None:
        with patch.object(kokoro, "generate_speech", return_value=b"audio") as mock_gen:
            result = router.generate_speech("Ola", "kokoro/pm_santa", "ogg", None)
            mock_gen.assert_called_once()
            assert result == b"audio"

    def test_qwen_voice_dispatches_to_qwen(
        self, router: EngineRouter, qwen: QwenEngine
    ) -> None:
        with patch.object(qwen, "generate_speech", return_value=b"audio") as mock_gen:
            result = router.generate_speech("Ola", "qwen/female-reference", "ogg", None)
            mock_gen.assert_called_once()
            assert result == b"audio"
            # Verify reference path was passed
            call_args = mock_gen.call_args
            assert isinstance(call_args[0][1], Path)

    def test_unknown_voice_raises(self, router: EngineRouter) -> None:
        with pytest.raises(InvalidRequestError):
            router.generate_speech("test", "invalid", "ogg")

    def test_seed_forwarded_to_qwen(
        self, router: EngineRouter, qwen: QwenEngine
    ) -> None:
        with patch.object(qwen, "generate_speech", return_value=b"data") as mock_gen:
            router.generate_speech("text", "qwen/female-reference", "ogg", seed=42)
            assert mock_gen.call_args[0][4] == 42  # seed is 5th positional arg

    def test_seed_not_forwarded_to_kokoro(
        self, router: EngineRouter, kokoro: KokoroEngine
    ) -> None:
        with patch.object(kokoro, "generate_speech", return_value=b"data") as mock_gen:
            router.generate_speech("text", "kokoro/pm_santa", "ogg", seed=42)
            # KokoroEngine.generate_speech() does not accept seed
            # Positional args: text, voice, format, noise_dir, speed
            assert len(mock_gen.call_args[0]) == 5

    def test_speed_forwarded_to_kokoro(
        self, router: EngineRouter, kokoro: KokoroEngine
    ) -> None:
        with patch.object(kokoro, "generate_speech", return_value=b"data") as mock_gen:
            router.generate_speech("text", "kokoro/pm_santa", "ogg", speed=2.5)
            assert mock_gen.call_args[0][4] == 2.5  # speed is 5th positional arg

    def test_speed_default_is_1(
        self, router: EngineRouter, kokoro: KokoroEngine
    ) -> None:
        with patch.object(kokoro, "generate_speech", return_value=b"data") as mock_gen:
            router.generate_speech("text", "kokoro/pm_santa", "ogg")
            assert mock_gen.call_args[0][4] == 1.0

    def test_noise_dir_forwarded(
        self, router: EngineRouter, kokoro: KokoroEngine
    ) -> None:
        noise = Path("/fake/noise")
        with patch.object(kokoro, "generate_speech", return_value=b"data") as mock_gen:
            router.generate_speech("text", "kokoro/pm_santa", "ogg", noise_dir=noise)
            assert mock_gen.call_args[0][3] == noise


# --- available_voices ---


class TestAvailableVoices:
    def test_includes_builtins_and_files(self, router: EngineRouter) -> None:
        voices = router.available_voices()
        # Built-in Kokoro voices
        assert "kokoro/pm_santa" in voices
        assert "kokoro/pf_dora" in voices
        assert "kokoro/pm_alex" in voices
        # Custom Kokoro .npy
        assert "kokoro/custom_voice" in voices
        # Qwen .wav files
        assert "qwen/female-reference" in voices
        assert "qwen/male-reference" in voices

    def test_sorted(self, router: EngineRouter) -> None:
        voices = router.available_voices()
        assert voices == sorted(voices)

    def test_no_duplicates(
        self, kokoro: KokoroEngine, qwen: QwenEngine, voices_dir: Path
    ) -> None:
        """If a .npy file has the same name as a built-in, it appears once."""
        # Create pm_santa.npy to overlap with built-in
        np.save(
            voices_dir / "kokoro" / "pm_santa.npy",
            np.zeros((510, 1, 256), dtype=np.float32),
        )
        router = EngineRouter(kokoro, qwen, voices_dir)
        voices = router.available_voices()
        assert voices.count("kokoro/pm_santa") == 1


# --- engine_status ---


class TestEngineStatus:
    def test_returns_both_engines(self, router: EngineRouter) -> None:
        status = router.engine_status()
        assert "kokoro" in status
        assert "qwen3" in status

    def test_kokoro_loaded_and_voices(self, router: EngineRouter) -> None:
        status = router.engine_status()
        assert status["kokoro"]["loaded"] is True
        assert any("kokoro/" in v for v in status["kokoro"]["voices"])  # type: ignore[union-attr]

    def test_qwen_loaded_and_voices(self, router: EngineRouter) -> None:
        status = router.engine_status()
        assert status["qwen3"]["loaded"] is True
        assert any("qwen/" in v for v in status["qwen3"]["voices"])  # type: ignore[union-attr]

    def test_no_clone_configured_field(self, router: EngineRouter) -> None:
        """clone_configured field no longer exists in engine status."""
        status = router.engine_status()
        assert "clone_configured" not in status["qwen3"]

    def test_unloaded_engines(self, voices_dir: Path) -> None:
        kokoro = KokoroEngine()
        qwen = QwenEngine()
        router = EngineRouter(kokoro, qwen, voices_dir)
        status = router.engine_status()
        assert status["kokoro"]["loaded"] is False
        assert status["qwen3"]["loaded"] is False


# --- Disabled Qwen3 (e.g. ARM hosts where the binary cannot run) ---


class TestRouterWithDisabledQwen:
    """Router behavior when QwenEngine is intentionally not loaded."""

    def test_available_voices_excludes_qwen_when_unloaded(
        self, kokoro: KokoroEngine, voices_dir: Path
    ) -> None:
        """Even when qwen .wav files exist, they are hidden when engine is off."""
        unloaded_qwen = QwenEngine()  # _loaded stays False
        router = EngineRouter(kokoro, unloaded_qwen, voices_dir)
        voices = router.available_voices()
        assert all(not v.startswith("qwen/") for v in voices)
        # Kokoro voices remain available
        assert "kokoro/pm_santa" in voices
        assert "kokoro/custom_voice" in voices

    def test_engine_status_qwen_not_loaded(
        self, kokoro: KokoroEngine, voices_dir: Path
    ) -> None:
        unloaded_qwen = QwenEngine()
        router = EngineRouter(kokoro, unloaded_qwen, voices_dir)
        status = router.engine_status()
        assert status["qwen3"]["loaded"] is False
        assert status["qwen3"]["voices"] == []

    def test_qwen_request_raises_invalid_request(
        self, kokoro: KokoroEngine, voices_dir: Path
    ) -> None:
        """Requesting a qwen voice with disabled engine returns 400, not 500."""
        unloaded_qwen = QwenEngine()
        router = EngineRouter(kokoro, unloaded_qwen, voices_dir)
        with pytest.raises(InvalidRequestError, match="Qwen3 engine is disabled"):
            router.generate_speech("Olá", "qwen/female-reference", "ogg", None)
