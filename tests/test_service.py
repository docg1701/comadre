"""Tests for the Kokoro TTS engine service."""

import io
import logging
import wave
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from cumadre.exceptions import GenerationError, InvalidRequestError, VoiceNotFoundError
from cumadre.service import (
    KOKORO_CHAR_LIMIT,
    KOKORO_VOICES,
    KokoroEngine,
    _apply_vibrato_warm,
    _concatenate_wavs,
    _samples_to_wav,
)


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


@pytest.fixture()
def engine() -> KokoroEngine:
    """Return a KokoroEngine with mocked Kokoro instance."""
    svc = KokoroEngine()
    mock_kokoro = MagicMock()
    mock_kokoro.create.return_value = (np.zeros(24000, dtype=np.float32), 24000)
    mock_kokoro.get_voices.return_value = ["pm_santa", "pf_dora", "pm_alex"]
    svc._kokoro = mock_kokoro
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


# --- Test voice mapping (AC #1) ---


class TestVoiceMapping:
    def test_kokoro_voices_contains_santa(self) -> None:
        assert KOKORO_VOICES["santa"] == "pm_santa"

    def test_kokoro_voices_contains_dora(self) -> None:
        assert KOKORO_VOICES["dora"] == "pf_dora"

    def test_kokoro_voices_contains_alex(self) -> None:
        assert KOKORO_VOICES["alex"] == "pm_alex"

    def test_kokoro_voices_only_three(self) -> None:
        assert len(KOKORO_VOICES) == 3


# --- Test generate_speech with WAV format (AC #1) ---


class TestGenerateSpeechWav:
    @patch("cumadre.service._apply_vibrato_warm")
    def test_returns_processed_bytes(
        self, mock_pipeline: MagicMock, engine: KokoroEngine
    ) -> None:
        mock_pipeline.return_value = b"processed_wav"
        result = engine.generate_speech("hello", "santa", "wav")
        assert result == b"processed_wav"

    @patch("cumadre.service._apply_vibrato_warm")
    def test_calls_kokoro_create_with_correct_args(
        self, mock_pipeline: MagicMock, engine: KokoroEngine
    ) -> None:
        mock_pipeline.return_value = b"audio"
        engine.generate_speech("hello world", "santa", "wav")
        engine._kokoro.create.assert_called_once()  # type: ignore[union-attr]
        call_kwargs = engine._kokoro.create.call_args  # type: ignore[union-attr]
        assert call_kwargs.kwargs["voice"] == "pm_santa"
        assert call_kwargs.kwargs["lang"] == "pt-br"

    @patch("cumadre.service._apply_vibrato_warm")
    def test_dora_maps_to_pf_dora(
        self, mock_pipeline: MagicMock, engine: KokoroEngine
    ) -> None:
        mock_pipeline.return_value = b"audio"
        engine.generate_speech("hello", "dora", "wav")
        call_kwargs = engine._kokoro.create.call_args  # type: ignore[union-attr]
        assert call_kwargs.kwargs["voice"] == "pf_dora"

    @patch("cumadre.service._apply_vibrato_warm")
    def test_alex_maps_to_pm_alex(
        self, mock_pipeline: MagicMock, engine: KokoroEngine
    ) -> None:
        mock_pipeline.return_value = b"audio"
        engine.generate_speech("hello", "alex", "wav")
        call_kwargs = engine._kokoro.create.call_args  # type: ignore[union-attr]
        assert call_kwargs.kwargs["voice"] == "pm_alex"


# --- Test response_format validation ---


class TestResponseFormatValidation:
    def test_rejects_unsupported_format(self, engine: KokoroEngine) -> None:
        with pytest.raises(InvalidRequestError) as exc_info:
            engine.generate_speech("hello", "santa", "mp3")
        assert "mp3" in exc_info.value.message
        assert exc_info.value.status_code == 400

    def test_accepts_wav(self, engine: KokoroEngine) -> None:
        with patch("cumadre.service._apply_vibrato_warm", return_value=b"audio"):
            result = engine.generate_speech("hello", "santa", "wav")
        assert result == b"audio"

    def test_accepts_ogg(self, engine: KokoroEngine) -> None:
        with patch("cumadre.service._apply_vibrato_warm", return_value=b"audio"):
            result = engine.generate_speech("hello", "santa", "ogg")
        assert result == b"audio"


# --- Test empty text validation ---


class TestEmptyTextValidation:
    def test_rejects_empty_string(self, engine: KokoroEngine) -> None:
        with pytest.raises(InvalidRequestError) as exc_info:
            engine.generate_speech("", "santa", "wav")
        assert "empty" in exc_info.value.message.lower()
        assert exc_info.value.status_code == 400

    def test_rejects_whitespace_only(self, engine: KokoroEngine) -> None:
        with pytest.raises(InvalidRequestError):
            engine.generate_speech("   \n\t  ", "santa", "wav")


# --- Test char limit validation (AC #4) ---


class TestCharLimitValidation:
    def test_text_at_limit_passes(self, engine: KokoroEngine) -> None:
        text = "a" * KOKORO_CHAR_LIMIT
        with patch("cumadre.service._apply_vibrato_warm", return_value=b"audio"):
            result = engine.generate_speech(text, "santa", "wav")
        assert result == b"audio"

    def test_text_over_limit_raises_invalid_request(self, engine: KokoroEngine) -> None:
        text = "a" * (KOKORO_CHAR_LIMIT + 1)
        with pytest.raises(InvalidRequestError) as exc_info:
            engine.generate_speech(text, "santa", "wav")
        assert str(KOKORO_CHAR_LIMIT) in exc_info.value.message
        assert exc_info.value.status_code == 400

    def test_error_hint_mentions_limit(self, engine: KokoroEngine) -> None:
        text = "a" * (KOKORO_CHAR_LIMIT + 1)
        with pytest.raises(InvalidRequestError) as exc_info:
            engine.generate_speech(text, "santa", "wav")
        assert str(KOKORO_CHAR_LIMIT) in exc_info.value.hint


# --- Test voice not found ---


class TestVoiceNotFound:
    def test_raises_voice_not_found_error(self, engine: KokoroEngine) -> None:
        with pytest.raises(VoiceNotFoundError) as exc_info:
            engine.generate_speech("hello", "ghost", "wav")
        assert exc_info.value.voice == "ghost"

    def test_error_contains_available_voices(self, engine: KokoroEngine) -> None:
        with pytest.raises(VoiceNotFoundError) as exc_info:
            engine.generate_speech("hello", "ghost", "wav")
        assert "santa" in exc_info.value.available
        assert "dora" in exc_info.value.available
        assert "alex" in exc_info.value.available


# --- Test model not loaded guard ---


class TestModelNotLoaded:
    def test_raises_runtime_error_when_not_loaded(self) -> None:
        svc = KokoroEngine()
        assert not svc.is_loaded
        with pytest.raises(RuntimeError, match="Model not loaded"):
            svc.generate_speech("hello", "santa", "wav")

    def test_warm_up_raises_when_not_loaded(self) -> None:
        svc = KokoroEngine()
        with pytest.raises(RuntimeError, match="Model not loaded"):
            svc.warm_up()


# --- Test vibrato_warm pipeline invocation (AC #6) ---


class TestVibratoWarmPipeline:
    @patch("cumadre.service.subprocess.run")
    def test_calls_ffmpeg_with_vibrato_filter(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(stdout=b"processed")
        wav = _create_wav_bytes()
        _apply_vibrato_warm(wav, "wav")
        # Stage 1 call
        assert mock_run.call_count >= 1
        cmd = mock_run.call_args_list[0]
        filter_arg = cmd.kwargs.get("input") or cmd[1].get("input")
        assert filter_arg is not None  # WAV was piped in

    @patch("cumadre.service.subprocess.run")
    def test_stage1_filter_chain_complete_and_ordered(
        self, mock_run: MagicMock
    ) -> None:
        mock_run.return_value = MagicMock(stdout=b"processed")
        wav = _create_wav_bytes()
        _apply_vibrato_warm(wav, "wav")
        stage1_call = mock_run.call_args_list[0]
        cmd_args = stage1_call[0][0]
        af_idx = cmd_args.index("-af")
        filter_chain = cmd_args[af_idx + 1]
        # All 10 filter stages must be present
        for filt in [
            "vibrato=f=4.5:d=0.06",
            "highpass=f=80",
            "bass=g=3:f=200",
            "equalizer=f=2500:width_type=o:width=1.5:g=2",
            "aexciter=freq=4500",
            "asoftclip=type=tanh",
            "acompressor=ratio=4:threshold=-20dB:attack=5:release=50",
            "lowpass=f=8000",
            "aecho=0.8:0.8:40:0.12",
            "loudnorm=I=-18:TP=-2:LRA=7",
        ]:
            assert filt in filter_chain, f"Missing filter: {filt}"
        # Verify order: vibrato first, loudnorm last
        assert filter_chain.index("vibrato") < filter_chain.index("loudnorm")

    @patch("cumadre.service.subprocess.run")
    def test_wav_format_without_noise_calls_ffmpeg_twice(
        self, mock_run: MagicMock
    ) -> None:
        mock_run.return_value = MagicMock(stdout=b"wav_data")
        wav = _create_wav_bytes()
        result = _apply_vibrato_warm(wav, "wav")
        assert result == b"wav_data"
        # Stage 1 (effects) + encode_final (second loudnorm)
        assert mock_run.call_count == 2


# --- Test OGG output path (AC #7) ---


class TestOggOutput:
    @patch("cumadre.service.subprocess.run")
    def test_ogg_format_calls_ffmpeg_twice(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(stdout=b"ogg_data")
        wav = _create_wav_bytes()
        _apply_vibrato_warm(wav, "ogg")
        # Stage 1 (effects) + encode (to ogg)
        assert mock_run.call_count == 2

    @patch("cumadre.service.subprocess.run")
    def test_ogg_encoding_params(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(stdout=b"ogg_data")
        wav = _create_wav_bytes()
        _apply_vibrato_warm(wav, "ogg")
        encode_call = mock_run.call_args_list[1]
        cmd_args = encode_call[0][0]
        assert "libopus" in cmd_args
        assert "ogg" in cmd_args
        assert "24k" in cmd_args  # bitrate
        assert "16000" in cmd_args  # sample rate
        assert "1" in cmd_args  # mono

    @patch("cumadre.service.subprocess.run")
    def test_ogg_encode_final_includes_second_loudnorm(
        self, mock_run: MagicMock
    ) -> None:
        mock_run.return_value = MagicMock(stdout=b"ogg_data")
        wav = _create_wav_bytes()
        _apply_vibrato_warm(wav, "ogg")
        encode_call = mock_run.call_args_list[1]
        cmd_args = encode_call[0][0]
        af_idx = cmd_args.index("-af")
        assert "loudnorm=I=-17:TP=-1.5:LRA=7" in cmd_args[af_idx + 1]


# --- Test noise mixing ---


class TestNoiseMixing:
    @patch("cumadre.service.subprocess.run")
    def test_noise_files_used_when_present(
        self, mock_run: MagicMock, tmp_path: Path
    ) -> None:
        mock_run.return_value = MagicMock(stdout=b"mixed_audio")
        room_file = tmp_path / "room.wav"
        hiss_file = tmp_path / "hiss.wav"
        room_file.write_bytes(_create_wav_bytes())
        hiss_file.write_bytes(_create_wav_bytes())

        wav = _create_wav_bytes()
        result = _apply_vibrato_warm(wav, "ogg", noise_dir=tmp_path)
        assert result == b"mixed_audio"
        # Stage 1 + stage 2 (with noise)
        assert mock_run.call_count == 2

    @patch("cumadre.service.subprocess.run")
    def test_noise_filter_complex_content(
        self, mock_run: MagicMock, tmp_path: Path
    ) -> None:
        mock_run.return_value = MagicMock(stdout=b"mixed")
        (tmp_path / "room.wav").write_bytes(_create_wav_bytes())
        (tmp_path / "hiss.wav").write_bytes(_create_wav_bytes())

        _apply_vibrato_warm(_create_wav_bytes(), "ogg", noise_dir=tmp_path)
        stage2_call = mock_run.call_args_list[1]
        cmd_args = stage2_call[0][0]
        fc_idx = cmd_args.index("-filter_complex")
        fc = cmd_args[fc_idx + 1]
        assert "volume=0.45" in fc
        assert "volume=0.24" in fc
        assert "amix=inputs=3" in fc
        assert "loudnorm=I=-17:TP=-1.5:LRA=7" in fc

    @patch("cumadre.service.subprocess.run")
    def test_missing_noise_falls_back_gracefully(
        self, mock_run: MagicMock, tmp_path: Path
    ) -> None:
        mock_run.return_value = MagicMock(stdout=b"clean_audio")
        wav = _create_wav_bytes()
        # noise_dir exists but has no noise files
        result = _apply_vibrato_warm(wav, "ogg", noise_dir=tmp_path)
        assert result == b"clean_audio"

    @patch("cumadre.service.subprocess.run")
    def test_missing_noise_logs_warning(
        self,
        mock_run: MagicMock,
        tmp_path: Path,
        request_logger: pytest.LogCaptureFixture,
    ) -> None:
        mock_run.return_value = MagicMock(stdout=b"clean")
        with request_logger.at_level(logging.WARNING, logger="request"):
            _apply_vibrato_warm(_create_wav_bytes(), "ogg", noise_dir=tmp_path)
        warnings = [r for r in request_logger.records if r.levelno == logging.WARNING]
        assert any(
            "missing" in r.message.lower() or "noise" in r.message.lower()
            for r in warnings
        )


# --- Test multi-chunk generation (AC #5) ---


class TestMultiChunkGeneration:
    @patch("cumadre.service._apply_vibrato_warm")
    @patch("cumadre.service.chunk_text")
    @patch("cumadre.service.normalize_text")
    def test_multi_chunk_calls_create_per_chunk(
        self,
        mock_normalize: MagicMock,
        mock_chunk: MagicMock,
        mock_pipeline: MagicMock,
        engine: KokoroEngine,
    ) -> None:
        mock_normalize.return_value = "chunk one. chunk two."
        mock_chunk.return_value = ["chunk one.", "chunk two."]
        mock_pipeline.return_value = b"audio"
        engine.generate_speech("chunk one. chunk two.", "santa", "wav")
        assert engine._kokoro.create.call_count == 2  # type: ignore[union-attr]

    @patch("cumadre.service._apply_vibrato_warm")
    @patch("cumadre.service.chunk_text")
    @patch("cumadre.service.normalize_text")
    def test_single_chunk_only_one_create_call(
        self,
        mock_normalize: MagicMock,
        mock_chunk: MagicMock,
        mock_pipeline: MagicMock,
        engine: KokoroEngine,
    ) -> None:
        mock_normalize.return_value = "short text"
        mock_chunk.return_value = ["short text"]
        mock_pipeline.return_value = b"audio"
        engine.generate_speech("short text", "santa", "wav")
        assert engine._kokoro.create.call_count == 1  # type: ignore[union-attr]

    @patch("cumadre.service._apply_vibrato_warm")
    def test_logs_chunk_count(
        self,
        mock_pipeline: MagicMock,
        engine: KokoroEngine,
        request_logger: pytest.LogCaptureFixture,
    ) -> None:
        mock_pipeline.return_value = b"audio"
        with request_logger.at_level(logging.DEBUG, logger="request"):
            engine.generate_speech("hello world", "santa", "wav")
        info_records = [r for r in request_logger.records if r.levelno == logging.INFO]
        assert any("chunk" in r.message.lower() for r in info_records)


# --- Test generation error wrapping ---


class TestGenerationError:
    def test_wraps_kokoro_exception(
        self,
        request_logger: pytest.LogCaptureFixture,
    ) -> None:
        svc = KokoroEngine()
        mock_kokoro = MagicMock()
        mock_kokoro.create.side_effect = RuntimeError("ONNX inference failed")
        svc._kokoro = mock_kokoro
        with (
            request_logger.at_level(logging.DEBUG, logger="request"),
            pytest.raises(GenerationError) as exc_info,
        ):
            svc.generate_speech("hello", "santa", "wav")
        assert "ONNX inference failed" in exc_info.value.message

    def test_logs_traceback_at_error_level(
        self,
        request_logger: pytest.LogCaptureFixture,
    ) -> None:
        svc = KokoroEngine()
        mock_kokoro = MagicMock()
        mock_kokoro.create.side_effect = RuntimeError("model crash")
        svc._kokoro = mock_kokoro
        with (
            request_logger.at_level(logging.DEBUG, logger="request"),
            pytest.raises(GenerationError),
        ):
            svc.generate_speech("hello", "santa", "wav")
        error_records = [
            r for r in request_logger.records if r.levelno == logging.ERROR
        ]
        assert len(error_records) >= 1
        assert any("TTS generation failed" in r.message for r in error_records)


# --- Test load_model ---


class TestLoadModel:
    def test_load_model_instantiates_kokoro(self) -> None:
        svc = KokoroEngine()
        assert not svc.is_loaded

        mock_kokoro_class = MagicMock()
        with (
            patch("cumadre.service.Kokoro", mock_kokoro_class, create=True),
            patch.dict(
                "sys.modules",
                {"kokoro_onnx": MagicMock(Kokoro=mock_kokoro_class)},
            ),
        ):
            svc.load_model("model.onnx", "voices.bin")

        assert svc.is_loaded

    def test_load_model_with_espeak_path(self) -> None:
        svc = KokoroEngine()
        mock_kokoro_class = MagicMock()
        mock_espeak_config_class = MagicMock()
        with patch.dict(
            "sys.modules",
            {
                "kokoro_onnx": MagicMock(
                    Kokoro=mock_kokoro_class,
                    EspeakConfig=mock_espeak_config_class,
                ),
            },
        ):
            svc.load_model("model.onnx", "voices.bin", "/custom/data")

        assert svc.is_loaded
        mock_espeak_config_class.assert_called_once_with(data_path="/custom/data")


# --- Test warm_up ---


class TestWarmUp:
    def test_warm_up_calls_create(self, engine: KokoroEngine) -> None:
        engine.warm_up()
        engine._kokoro.create.assert_called_once()  # type: ignore[union-attr]
        call_kwargs = engine._kokoro.create.call_args.kwargs  # type: ignore[union-attr]
        assert call_kwargs["voice"] == "pm_santa"
        assert call_kwargs["lang"] == "pt-br"


# --- Test _samples_to_wav ---


class TestSamplesToWav:
    def test_returns_valid_wav(self) -> None:
        samples = np.zeros(24000, dtype=np.float32)
        result = _samples_to_wav(samples, 24000)
        assert result[:4] == b"RIFF"

    def test_correct_sample_rate(self) -> None:
        samples = np.zeros(24000, dtype=np.float32)
        result = _samples_to_wav(samples, 24000)
        with wave.open(io.BytesIO(result), "rb") as wf:
            assert wf.getframerate() == 24000
            assert wf.getnchannels() == 1
            assert wf.getsampwidth() == 2

    def test_clips_samples_outside_range(self) -> None:
        """Samples >1.0 or <-1.0 must be clipped, not wrapped around."""
        samples = np.array([1.5, -1.5, 0.5], dtype=np.float32)
        result = _samples_to_wav(samples, 24000)
        with wave.open(io.BytesIO(result), "rb") as wf:
            raw = wf.readframes(3)
        values = np.frombuffer(raw, dtype=np.int16)
        assert values[0] == 32767  # clipped to max
        assert values[1] == -32767  # clipped to min
        assert values[2] == 16383  # 0.5 * 32767 ≈ 16383


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
