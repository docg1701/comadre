"""Tests for EngineRouter voice routing and unified API."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from cumadre.exceptions import VoiceNotFoundError
from cumadre.service import (
    KOKORO_VOICES,
    EngineRouter,
    KokoroEngine,
    QwenEngine,
)


@pytest.fixture()
def kokoro() -> KokoroEngine:
    """Return a KokoroEngine with mocked internals."""
    engine = KokoroEngine()
    engine._kokoro = MagicMock()
    return engine


@pytest.fixture()
def qwen() -> QwenEngine:
    """Return a QwenEngine with mocked internals."""
    engine = QwenEngine()
    engine._loaded = True
    engine._voice_references = {
        "qwen-female": "/fake/female.wav",
        "qwen-male": "/fake/male.wav",
        "clone": "/fake/clone.wav",
    }
    return engine


@pytest.fixture()
def qwen_no_clone() -> QwenEngine:
    """Return a QwenEngine without clone configured."""
    engine = QwenEngine()
    engine._loaded = True
    engine._voice_references = {
        "qwen-female": "/fake/female.wav",
        "qwen-male": "/fake/male.wav",
    }
    return engine


@pytest.fixture()
def router(kokoro: KokoroEngine, qwen: QwenEngine) -> EngineRouter:
    """Return an EngineRouter with both mocked engines."""
    return EngineRouter(kokoro, qwen)


@pytest.fixture()
def router_no_clone(kokoro: KokoroEngine, qwen_no_clone: QwenEngine) -> EngineRouter:
    """Return an EngineRouter without clone configured."""
    return EngineRouter(kokoro, qwen_no_clone)


# --- Task 3.1: Kokoro voice routing ---


@pytest.mark.parametrize("voice", ["santa", "dora", "alex"])
def test_kokoro_voice_routes_to_kokoro_engine(router: EngineRouter, voice: str) -> None:
    """Each Kokoro voice should resolve to KokoroEngine."""
    engine = router._resolve_engine(voice)
    assert isinstance(engine, KokoroEngine)


@pytest.mark.parametrize("voice", ["santa", "dora", "alex"])
def test_kokoro_voice_calls_kokoro_generate(
    router: EngineRouter, kokoro: KokoroEngine, voice: str
) -> None:
    """generate_speech() dispatches to KokoroEngine for Kokoro voices."""
    with patch.object(kokoro, "generate_speech", return_value=b"wav-data") as mock_gen:
        result = router.generate_speech("Olá", voice, "ogg", None)
        mock_gen.assert_called_once_with("Olá", voice, "ogg", None)
        assert result == b"wav-data"


# --- Task 3.2: Qwen3 voice routing ---


@pytest.mark.parametrize("voice", ["clone", "qwen-female", "qwen-male"])
def test_qwen_voice_routes_to_qwen_engine(router: EngineRouter, voice: str) -> None:
    """Each Qwen3 voice should resolve to QwenEngine."""
    engine = router._resolve_engine(voice)
    assert isinstance(engine, QwenEngine)


@pytest.mark.parametrize("voice", ["clone", "qwen-female", "qwen-male"])
def test_qwen_voice_calls_qwen_generate(
    router: EngineRouter, qwen: QwenEngine, voice: str
) -> None:
    """generate_speech() dispatches to QwenEngine for Qwen3 voices."""
    with patch.object(qwen, "generate_speech", return_value=b"qwen-data") as mock_gen:
        result = router.generate_speech("Olá", voice, "ogg", None, seed=42)
        mock_gen.assert_called_once_with("Olá", voice, "ogg", None, 42)
        assert result == b"qwen-data"


# --- Task 3.3: Unknown voice raises VoiceNotFoundError ---


def test_unknown_voice_raises_voice_not_found(router: EngineRouter) -> None:
    """Unknown voice should raise VoiceNotFoundError with available voices."""
    with pytest.raises(VoiceNotFoundError) as exc_info:
        router.generate_speech("test", "unknown-voice", "ogg")
    assert "unknown-voice" in str(exc_info.value)
    assert exc_info.value.available == router.available_voices()


def test_resolve_unknown_voice_raises_error(router: EngineRouter) -> None:
    """_resolve_engine with unknown voice raises VoiceNotFoundError."""
    with pytest.raises(VoiceNotFoundError) as exc_info:
        router._resolve_engine("nonexistent")
    assert "nonexistent" in str(exc_info.value)


# --- Task 3.4: available_voices() returns sorted combined list ---


def test_available_voices_sorted_with_clone(router: EngineRouter) -> None:
    """available_voices() returns sorted list including clone when configured."""
    voices = router.available_voices()
    assert voices == sorted(voices)
    for kokoro_voice in KOKORO_VOICES:
        assert kokoro_voice in voices
    assert "qwen-female" in voices
    assert "qwen-male" in voices
    assert "clone" in voices


def test_available_voices_sorted_without_clone(
    router_no_clone: EngineRouter,
) -> None:
    """available_voices() excludes clone when not configured."""
    voices = router_no_clone.available_voices()
    assert voices == sorted(voices)
    assert "clone" not in voices
    assert "qwen-female" in voices
    assert "qwen-male" in voices


# --- Task 3.5: engine_status() returns correct per-engine status ---


def test_engine_status_both_loaded(router: EngineRouter) -> None:
    """engine_status() returns correct shape with both engines loaded."""
    status = router.engine_status()
    assert status["kokoro"]["loaded"] is True
    assert sorted(status["kokoro"]["voices"]) == ["alex", "dora", "santa"]  # type: ignore[call-overload]
    assert status["qwen3"]["loaded"] is True
    assert status["qwen3"]["clone_configured"] is True
    assert "clone" in status["qwen3"]["voices"]  # type: ignore[operator]


def test_engine_status_clone_not_configured(
    router_no_clone: EngineRouter,
) -> None:
    """engine_status() excludes clone when not configured."""
    status = router_no_clone.engine_status()
    assert status["qwen3"]["clone_configured"] is False
    assert "clone" not in status["qwen3"]["voices"]  # type: ignore[operator]


def test_engine_status_not_loaded() -> None:
    """engine_status() reports loaded=False for unloaded engines."""
    kokoro = KokoroEngine()
    qwen = QwenEngine()
    router = EngineRouter(kokoro, qwen)
    status = router.engine_status()
    assert status["kokoro"]["loaded"] is False
    assert status["qwen3"]["loaded"] is False


# --- Task 3.6: Clone voice raises error when not configured ---


def test_clone_voice_raises_when_not_configured(
    router_no_clone: EngineRouter,
) -> None:
    """Clone voice should raise VoiceNotFoundError when clone not configured."""
    with pytest.raises(VoiceNotFoundError) as exc_info:
        router_no_clone.generate_speech("test", "clone", "ogg")
    assert "clone" in str(exc_info.value)
    assert "clone" not in exc_info.value.available


def test_clone_resolve_raises_when_not_configured(
    router_no_clone: EngineRouter,
) -> None:
    """_resolve_engine rejects clone when not configured."""
    with pytest.raises(VoiceNotFoundError) as exc_info:
        router_no_clone._resolve_engine("clone")
    assert exc_info.value.available == router_no_clone.available_voices()


# --- Task 3.7: Seed parameter forwarded to Qwen3 only ---


def test_seed_forwarded_to_qwen_engine(router: EngineRouter, qwen: QwenEngine) -> None:
    """Seed parameter should be forwarded to QwenEngine.generate_speech()."""
    with patch.object(qwen, "generate_speech", return_value=b"data") as mock_gen:
        router.generate_speech("text", "qwen-female", "ogg", seed=123)
        mock_gen.assert_called_once_with("text", "qwen-female", "ogg", None, 123)


def test_seed_not_forwarded_to_kokoro_engine(
    router: EngineRouter, kokoro: KokoroEngine
) -> None:
    """Seed parameter should NOT be forwarded to KokoroEngine."""
    with patch.object(kokoro, "generate_speech", return_value=b"data") as mock_gen:
        router.generate_speech("text", "santa", "ogg", seed=123)
        # KokoroEngine.generate_speech() does not accept seed
        mock_gen.assert_called_once_with("text", "santa", "ogg", None)


def test_default_seed_forwarded_to_qwen(router: EngineRouter, qwen: QwenEngine) -> None:
    """Default seed (-1) should be forwarded when no seed specified."""
    with patch.object(qwen, "generate_speech", return_value=b"data") as mock_gen:
        router.generate_speech("text", "qwen-male", "ogg")
        mock_gen.assert_called_once_with("text", "qwen-male", "ogg", None, -1)


# --- noise_dir parameter forwarding ---


def test_noise_dir_forwarded_to_kokoro(
    router: EngineRouter, kokoro: KokoroEngine
) -> None:
    """noise_dir should be forwarded to KokoroEngine."""
    noise = Path("/fake/noise")
    with patch.object(kokoro, "generate_speech", return_value=b"data") as mock_gen:
        router.generate_speech("text", "santa", "ogg", noise_dir=noise)
        mock_gen.assert_called_once_with("text", "santa", "ogg", noise)


def test_noise_dir_forwarded_to_qwen(router: EngineRouter, qwen: QwenEngine) -> None:
    """noise_dir should be forwarded to QwenEngine."""
    noise = Path("/fake/noise")
    with patch.object(qwen, "generate_speech", return_value=b"data") as mock_gen:
        router.generate_speech("text", "qwen-female", "ogg", noise_dir=noise)
        mock_gen.assert_called_once_with("text", "qwen-female", "ogg", noise, -1)


# --- Story 1.10: Preprocessing/post-processing pipeline tests ---


class TestKokoroPreprocessingPipeline:
    """Verify Kokoro engine calls normalize_text() then chunk_text()."""

    @patch("cumadre.service._apply_vibrato_warm", return_value=b"processed")
    @patch("cumadre.service._concatenate_wavs", return_value=b"concat-wav")
    @patch("cumadre.service._samples_to_wav", return_value=b"wav-data")
    def test_kokoro_calls_normalize_then_chunk(
        self,
        mock_wav: MagicMock,
        mock_concat: MagicMock,
        mock_vibrato: MagicMock,
        kokoro: KokoroEngine,
    ) -> None:
        """KokoroEngine.generate_speech() calls normalize_text then chunk_text."""
        kokoro._kokoro.create.return_value = (np.zeros(100), 24000)
        with (
            patch(
                "cumadre.service.normalize_text", return_value="normalized"
            ) as mock_normalize,
            patch("cumadre.service.chunk_text", return_value=["chunk1"]) as mock_chunk,
        ):
            kokoro.generate_speech("raw text", "santa", "ogg")
            mock_normalize.assert_called_once_with("raw text")
            mock_chunk.assert_called_once_with("normalized")


class TestKokoroPostProcessingPipeline:
    """Verify Kokoro engine calls _apply_vibrato_warm()."""

    @patch("cumadre.service._apply_vibrato_warm", return_value=b"processed")
    @patch("cumadre.service._concatenate_wavs", return_value=b"concat-wav")
    @patch("cumadre.service._samples_to_wav", return_value=b"wav-data")
    def test_kokoro_uses_vibrato_warm_pipeline(
        self,
        mock_wav: MagicMock,
        mock_concat: MagicMock,
        mock_vibrato: MagicMock,
        kokoro: KokoroEngine,
    ) -> None:
        """KokoroEngine.generate_speech() calls _apply_vibrato_warm on output."""
        kokoro._kokoro.create.return_value = (np.zeros(100), 24000)
        kokoro.generate_speech("test", "santa", "ogg")
        mock_vibrato.assert_called_once()


class TestQwenPreprocessingPipeline:
    """Verify Qwen3 engine calls expand_siglas()."""

    @patch("cumadre.service._apply_whatsapp_subtle", return_value=b"processed")
    @patch("cumadre.service.subprocess.run")
    def test_qwen_calls_expand_siglas(
        self,
        mock_run: MagicMock,
        mock_whatsapp: MagicMock,
        qwen: QwenEngine,
    ) -> None:
        """QwenEngine.generate_speech() calls expand_siglas on input."""
        mock_run.return_value = MagicMock(returncode=0)
        with (
            patch(
                "cumadre.service.expand_siglas", return_value="expanded"
            ) as mock_expand,
            patch.object(
                qwen, "_build_command", return_value=["fake-cli", "-t", "expanded"]
            ),
            patch("cumadre.service.Path") as mock_path,
            patch("cumadre.service.tempfile") as mock_tempfile,
        ):
            mock_tempfile.NamedTemporaryFile.return_value.__enter__ = MagicMock(
                return_value=MagicMock(name="/tmp/fake.wav")
            )
            mock_tempfile.NamedTemporaryFile.return_value.__exit__ = MagicMock(
                return_value=False
            )
            mock_path.return_value.read_bytes.return_value = b"wav-data"
            mock_path.return_value.unlink = MagicMock()
            qwen.generate_speech("CNPJ test", "qwen-female", "ogg")
            mock_expand.assert_called_once_with("CNPJ test")


class TestQwenPostProcessingPipeline:
    """Verify Qwen3 engine calls _apply_whatsapp_subtle()."""

    @patch("cumadre.service._apply_whatsapp_subtle", return_value=b"processed")
    @patch("cumadre.service.subprocess.run")
    def test_qwen_uses_whatsapp_subtle_pipeline(
        self,
        mock_run: MagicMock,
        mock_whatsapp: MagicMock,
        qwen: QwenEngine,
    ) -> None:
        """QwenEngine.generate_speech() calls _apply_whatsapp_subtle on output."""
        mock_run.return_value = MagicMock(returncode=0)
        with (
            patch("cumadre.service.expand_siglas", return_value="expanded"),
            patch.object(
                qwen, "_build_command", return_value=["fake-cli", "-t", "expanded"]
            ),
            patch("cumadre.service.Path") as mock_path,
            patch("cumadre.service.tempfile") as mock_tempfile,
        ):
            mock_tempfile.NamedTemporaryFile.return_value.__enter__ = MagicMock(
                return_value=MagicMock(name="/tmp/fake.wav")
            )
            mock_tempfile.NamedTemporaryFile.return_value.__exit__ = MagicMock(
                return_value=False
            )
            mock_path.return_value.read_bytes.return_value = b"wav-data"
            mock_path.return_value.unlink = MagicMock()
            qwen.generate_speech("test", "qwen-female", "ogg")
            mock_whatsapp.assert_called_once()
