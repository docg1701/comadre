"""Tests for the KokoClone TTS service wrapper."""

import io
import logging
import subprocess
import wave
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from cumadre.exceptions import GenerationError, VoiceNotFoundError
from cumadre.service import TTSService, _concatenate_wavs, _encode_ogg
from cumadre.voices import VoiceInfo


def _create_wav_bytes(duration: float = 1.0, framerate: int = 24000) -> bytes:
    """Create minimal WAV bytes for testing."""
    buf = io.BytesIO()
    n_frames = int(framerate * duration)
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(framerate)
        wf.writeframes(b"\x00\x00" * n_frames)
    return buf.getvalue()


def _mock_generate(
    text: str, lang: str, ref_audio: str, output_path: str = "output.wav"
) -> None:
    """Write a valid WAV to the output path (simulates KokoClone)."""
    wav_bytes = _create_wav_bytes()
    Path(output_path).write_bytes(wav_bytes)


@pytest.fixture()
def voices(tmp_path: Path) -> list[VoiceInfo]:
    """Create a test voice list with a real WAV file on disk."""
    wav_path = tmp_path / "alice.wav"
    wav_path.write_bytes(_create_wav_bytes(duration=5.0))
    return [
        VoiceInfo(name="alice", path=wav_path, duration_seconds=5.0),
        VoiceInfo(name="bob", path=tmp_path / "bob.wav", duration_seconds=4.0),
    ]


@pytest.fixture()
def service() -> TTSService:
    """Return a TTSService with a mocked KokoClone instance."""
    svc = TTSService()
    mock_cloner = MagicMock()
    mock_cloner.generate.side_effect = _mock_generate
    svc._cloner = mock_cloner
    return svc


@pytest.fixture()
def request_logger(caplog: pytest.LogCaptureFixture) -> pytest.LogCaptureFixture:
    """Enable log capture for the request logger (propagate=False by default)."""
    req_log = logging.getLogger("request")
    req_log.propagate = True
    yield caplog
    req_log.propagate = False


@pytest.fixture()
def startup_logger(caplog: pytest.LogCaptureFixture) -> pytest.LogCaptureFixture:
    """Enable log capture for the startup logger."""
    log = logging.getLogger("startup")
    log.propagate = True
    yield caplog
    log.propagate = False


# --- Test generate_speech with WAV format (AC #1) ---


class TestGenerateSpeechWav:
    def test_returns_wav_bytes(
        self, service: TTSService, voices: list[VoiceInfo]
    ) -> None:
        result = service.generate_speech("hello", "alice", "wav", voices)
        assert isinstance(result, bytes)
        assert len(result) > 0

    def test_wav_starts_with_riff_header(
        self, service: TTSService, voices: list[VoiceInfo]
    ) -> None:
        result = service.generate_speech("hello", "alice", "wav", voices)
        assert result[:4] == b"RIFF"

    def test_calls_cloner_with_correct_args(
        self, service: TTSService, voices: list[VoiceInfo]
    ) -> None:
        service.generate_speech("hello world", "alice", "wav", voices)
        service._cloner.generate.assert_called_once()
        call_args = service._cloner.generate.call_args
        assert call_args[0][0] == "hello world"
        assert call_args[0][1] == "pt"
        assert call_args[0][2] == str(voices[0].path)


# --- Test generate_speech with OGG format (AC #2) ---


class TestGenerateSpeechOgg:
    @patch("cumadre.service.subprocess.run")
    def test_returns_ogg_bytes(
        self,
        mock_run: MagicMock,
        service: TTSService,
        voices: list[VoiceInfo],
    ) -> None:
        mock_run.return_value = MagicMock(stdout=b"OggS_fake_data")
        result = service.generate_speech("hello", "alice", "ogg", voices)
        assert result == b"OggS_fake_data"

    @patch("cumadre.service.subprocess.run")
    def test_calls_ffmpeg(
        self,
        mock_run: MagicMock,
        service: TTSService,
        voices: list[VoiceInfo],
    ) -> None:
        mock_run.return_value = MagicMock(stdout=b"OggS_data")
        service.generate_speech("hello", "alice", "ogg", voices)
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "ffmpeg"
        assert "-c:a" in cmd
        assert "libopus" in cmd
        assert "-f" in cmd
        assert "ogg" in cmd


# --- Test voice not found (AC #3) ---


class TestVoiceNotFound:
    def test_raises_voice_not_found_error(
        self, service: TTSService, voices: list[VoiceInfo]
    ) -> None:
        with pytest.raises(VoiceNotFoundError) as exc_info:
            service.generate_speech("hello", "ghost", "wav", voices)
        assert exc_info.value.voice == "ghost"

    def test_error_contains_available_voices(
        self, service: TTSService, voices: list[VoiceInfo]
    ) -> None:
        with pytest.raises(VoiceNotFoundError) as exc_info:
            service.generate_speech("hello", "ghost", "wav", voices)
        assert "alice" in exc_info.value.available
        assert "bob" in exc_info.value.available


# --- Test KokoClone failure wrapped in GenerationError (AC #4) ---


class TestGenerationError:
    def test_wraps_cloner_exception(
        self,
        voices: list[VoiceInfo],
        request_logger: pytest.LogCaptureFixture,
    ) -> None:
        svc = TTSService()
        mock_cloner = MagicMock()
        mock_cloner.generate.side_effect = RuntimeError("CUDA out of memory")
        svc._cloner = mock_cloner
        with (
            request_logger.at_level(logging.DEBUG, logger="request"),
            pytest.raises(GenerationError) as exc_info,
        ):
            svc.generate_speech("hello", "alice", "wav", voices)

        assert "CUDA out of memory" in exc_info.value.message

    def test_logs_traceback_at_error_level(
        self,
        voices: list[VoiceInfo],
        request_logger: pytest.LogCaptureFixture,
    ) -> None:
        svc = TTSService()
        mock_cloner = MagicMock()
        mock_cloner.generate.side_effect = RuntimeError("model crash")
        svc._cloner = mock_cloner
        with (
            request_logger.at_level(logging.DEBUG, logger="request"),
            pytest.raises(GenerationError),
        ):
            svc.generate_speech("hello", "alice", "wav", voices)

        error_records = [
            r for r in request_logger.records if r.levelno == logging.ERROR
        ]
        assert len(error_records) >= 1
        assert any("TTS generation failed" in r.message for r in error_records)


# --- Test load_model (AC #1) ---


class TestLoadModel:
    def test_load_model_instantiates_kokoclone(self) -> None:
        svc = TTSService()
        assert not svc.is_loaded

        mock_cloner_class = MagicMock()
        with patch.dict(
            "sys.modules",
            {
                "core": MagicMock(),
                "core.cloner": MagicMock(KokoClone=mock_cloner_class),
            },
        ):
            svc.load_model()

        assert svc.is_loaded
        mock_cloner_class.assert_called_once()


# --- Test warm_up (AC #1) ---


class TestWarmUp:
    def test_warm_up_calls_generate(
        self,
        service: TTSService,
        tmp_path: Path,
    ) -> None:
        ref_wav = tmp_path / "ref.wav"
        ref_wav.write_bytes(_create_wav_bytes())
        service.warm_up(ref_wav)
        service._cloner.generate.assert_called_once()
        call_args = service._cloner.generate.call_args
        assert call_args[0][0] == "test"
        assert call_args[0][1] == "pt"
        assert call_args[0][2] == str(ref_wav)


# --- Test _encode_ogg ---


class TestEncodeOgg:
    @patch("cumadre.service.subprocess.run")
    def test_returns_stdout_bytes(self, mock_run: MagicMock, tmp_path: Path) -> None:
        mock_run.return_value = MagicMock(stdout=b"OggS_encoded")
        wav_path = tmp_path / "test.wav"
        wav_path.write_bytes(_create_wav_bytes())
        result = _encode_ogg(wav_path)
        assert result == b"OggS_encoded"

    @patch("cumadre.service.subprocess.run")
    def test_ffmpeg_failure_raises_generation_error(
        self, mock_run: MagicMock, tmp_path: Path
    ) -> None:
        mock_run.side_effect = subprocess.CalledProcessError(
            1, "ffmpeg", stderr=b"encoding error"
        )
        wav_path = tmp_path / "test.wav"
        wav_path.write_bytes(_create_wav_bytes())
        with pytest.raises(GenerationError, match="OGG"):
            _encode_ogg(wav_path)


# --- Test multi-chunk generation (Story 1.4a AC #5) ---


class TestMultiChunkGeneration:
    @patch("cumadre.service.chunk_text")
    @patch("cumadre.service.normalize_text")
    def test_multi_chunk_calls_generate_per_chunk(
        self,
        mock_normalize: MagicMock,
        mock_chunk: MagicMock,
        service: TTSService,
        voices: list[VoiceInfo],
    ) -> None:
        mock_normalize.return_value = "chunk one. chunk two."
        mock_chunk.return_value = ["chunk one.", "chunk two."]
        result = service.generate_speech(
            "chunk one. chunk two.", "alice", "wav", voices
        )
        assert service._cloner.generate.call_count == 2
        assert result[:4] == b"RIFF"

    @patch("cumadre.service.chunk_text")
    @patch("cumadre.service.normalize_text")
    def test_single_chunk_no_concatenation_overhead(
        self,
        mock_normalize: MagicMock,
        mock_chunk: MagicMock,
        service: TTSService,
        voices: list[VoiceInfo],
    ) -> None:
        mock_normalize.return_value = "short text"
        mock_chunk.return_value = ["short text"]
        result = service.generate_speech("short text", "alice", "wav", voices)
        assert service._cloner.generate.call_count == 1
        assert result[:4] == b"RIFF"

    def test_logs_chunk_count(
        self,
        service: TTSService,
        voices: list[VoiceInfo],
        request_logger: pytest.LogCaptureFixture,
    ) -> None:
        with request_logger.at_level(logging.DEBUG, logger="request"):
            service.generate_speech("hello world", "alice", "wav", voices)
        info_records = [r for r in request_logger.records if r.levelno == logging.INFO]
        assert any("chunk" in r.message.lower() for r in info_records)


# --- Test _concatenate_wavs ---


class TestConcatenateWavs:
    def test_single_wav_returns_unchanged(self) -> None:
        wav = _create_wav_bytes(duration=1.0)
        assert _concatenate_wavs([wav]) is wav

    def test_two_wavs_produce_valid_output(self) -> None:
        wav1 = _create_wav_bytes(duration=1.0)
        wav2 = _create_wav_bytes(duration=0.5)
        result = _concatenate_wavs([wav1, wav2])
        assert result[:4] == b"RIFF"
        assert len(result) > len(wav1)


# --- Test ESPEAK_DATA_PATH override (Story 1.4a AC #6) ---


class TestEspeakDataPath:
    def test_load_model_sets_env_var(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        svc = TTSService()
        monkeypatch.delenv("ESPEAK_DATA_PATH", raising=False)
        mock_cloner_class = MagicMock()
        with patch.dict(
            "sys.modules",
            {
                "core": MagicMock(),
                "core.cloner": MagicMock(KokoClone=mock_cloner_class),
            },
        ):
            svc.load_model(espeak_data_path="/custom/data")
        import os

        assert os.environ.get("ESPEAK_DATA_PATH") == "/custom/data"
        monkeypatch.delenv("ESPEAK_DATA_PATH", raising=False)

    def test_load_model_without_path_skips_override(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        svc = TTSService()
        monkeypatch.delenv("ESPEAK_DATA_PATH", raising=False)
        mock_cloner_class = MagicMock()
        with patch.dict(
            "sys.modules",
            {
                "core": MagicMock(),
                "core.cloner": MagicMock(KokoClone=mock_cloner_class),
            },
        ):
            svc.load_model()
        import os

        assert os.environ.get("ESPEAK_DATA_PATH") is None
