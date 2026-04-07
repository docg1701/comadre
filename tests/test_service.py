"""Tests for the TTS engine services."""

import io
import logging
import subprocess
import wave
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from comadre.exceptions import GenerationError, InvalidRequestError
from comadre.service import (
    KokoroEngine,
    QwenEngine,
    _apply_radio_warm,
    _apply_whatsapp_subtle,
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
    mock_kokoro.get_voice_style.return_value = np.zeros((510, 1, 256), dtype=np.float32)
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


# --- Test generate_speech with WAV format ---


class TestGenerateSpeechWav:
    @patch("comadre.service._apply_radio_warm")
    def test_returns_processed_bytes(
        self, mock_pipeline: MagicMock, engine: KokoroEngine
    ) -> None:
        mock_pipeline.return_value = b"processed_wav"
        result = engine.generate_speech("hello", "pm_santa", "wav")
        assert result == b"processed_wav"

    @patch("comadre.service._apply_radio_warm")
    def test_calls_kokoro_create_with_correct_args(
        self, mock_pipeline: MagicMock, engine: KokoroEngine
    ) -> None:
        mock_pipeline.return_value = b"audio"
        engine.generate_speech("hello world", "pm_santa", "wav")
        engine._kokoro.create.assert_called_once()  # type: ignore[union-attr]
        call_kwargs = engine._kokoro.create.call_args  # type: ignore[union-attr]
        assert call_kwargs.kwargs["voice"] == "pm_santa"
        assert call_kwargs.kwargs["lang"] == "pt-br"

    @patch("comadre.service._apply_radio_warm")
    def test_accepts_numpy_voice(
        self, mock_pipeline: MagicMock, engine: KokoroEngine
    ) -> None:
        """Voice can be a numpy array (custom voice profile)."""
        mock_pipeline.return_value = b"audio"
        voice_array = np.zeros((510, 1, 256), dtype=np.float32)
        result = engine.generate_speech("hello", voice_array, "wav")
        assert result == b"audio"
        call_kwargs = engine._kokoro.create.call_args  # type: ignore[union-attr]
        assert isinstance(call_kwargs.kwargs["voice"], np.ndarray)


# --- Test response_format validation ---


class TestResponseFormatValidation:
    def test_rejects_unsupported_format(self, engine: KokoroEngine) -> None:
        with pytest.raises(InvalidRequestError) as exc_info:
            engine.generate_speech("hello", "pm_santa", "mp3")
        assert "mp3" in exc_info.value.message
        assert exc_info.value.status_code == 400

    def test_accepts_wav(self, engine: KokoroEngine) -> None:
        with patch("comadre.service._apply_radio_warm", return_value=b"audio"):
            result = engine.generate_speech("hello", "pm_santa", "wav")
        assert result == b"audio"

    def test_accepts_ogg(self, engine: KokoroEngine) -> None:
        with patch("comadre.service._apply_radio_warm", return_value=b"audio"):
            result = engine.generate_speech("hello", "pm_santa", "ogg")
        assert result == b"audio"


# --- Test empty text validation ---


class TestEmptyTextValidation:
    def test_rejects_empty_string(self, engine: KokoroEngine) -> None:
        with pytest.raises(InvalidRequestError) as exc_info:
            engine.generate_speech("", "pm_santa", "wav")
        assert "empty" in exc_info.value.message.lower()
        assert exc_info.value.status_code == 400

    def test_rejects_whitespace_only(self, engine: KokoroEngine) -> None:
        with pytest.raises(InvalidRequestError):
            engine.generate_speech("   \n\t  ", "pm_santa", "wav")


# --- Test char limit validation ---


class TestCharLimitValidation:
    def test_text_at_limit_passes(self, engine: KokoroEngine) -> None:
        text = "a" * KokoroEngine.CHAR_LIMIT
        with patch("comadre.service._apply_radio_warm", return_value=b"audio"):
            result = engine.generate_speech(text, "pm_santa", "wav")
        assert result == b"audio"

    def test_text_over_limit_raises_invalid_request(self, engine: KokoroEngine) -> None:
        text = "a" * (KokoroEngine.CHAR_LIMIT + 1)
        with pytest.raises(InvalidRequestError) as exc_info:
            engine.generate_speech(text, "pm_santa", "wav")
        assert str(KokoroEngine.CHAR_LIMIT) in exc_info.value.message
        assert exc_info.value.status_code == 400

    def test_error_hint_mentions_limit(self, engine: KokoroEngine) -> None:
        text = "a" * (KokoroEngine.CHAR_LIMIT + 1)
        with pytest.raises(InvalidRequestError) as exc_info:
            engine.generate_speech(text, "pm_santa", "wav")
        assert str(KokoroEngine.CHAR_LIMIT) in exc_info.value.hint


# --- Test model not loaded guard ---


class TestModelNotLoaded:
    def test_raises_generation_error_when_not_loaded(self) -> None:
        svc = KokoroEngine()
        assert not svc.is_loaded
        with pytest.raises(GenerationError, match="Model not loaded"):
            svc.generate_speech("hello", "pm_santa", "wav")

    def test_warm_up_raises_when_not_loaded(self) -> None:
        svc = KokoroEngine()
        with pytest.raises(GenerationError, match="Model not loaded"):
            svc.warm_up()


# --- Test radio_warm pipeline invocation ---


class TestRadioWarmPipeline:
    @patch("comadre.service.subprocess.run")
    def test_calls_ffmpeg_with_vibrato_filter(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(stdout=b"processed")
        wav = _create_wav_bytes()
        _apply_radio_warm(wav, "wav")
        # Stage 1 call
        assert mock_run.call_count >= 1
        cmd = mock_run.call_args_list[0]
        filter_arg = cmd.kwargs.get("input") or cmd[1].get("input")
        assert filter_arg is not None  # WAV was piped in

    @patch("comadre.service.subprocess.run")
    def test_stage1_filter_chain_complete_and_ordered(
        self, mock_run: MagicMock
    ) -> None:
        mock_run.return_value = MagicMock(stdout=b"processed")
        wav = _create_wav_bytes()
        _apply_radio_warm(wav, "wav")
        stage1_call = mock_run.call_args_list[0]
        cmd_args = stage1_call[0][0]
        af_idx = cmd_args.index("-af")
        filter_chain = cmd_args[af_idx + 1]
        # All 9 filter stages must be present
        for filt in [
            "highpass=f=100",
            "bass=g=5:f=150",
            "equalizer=f=250:width_type=o:width=1:g=3",
            "equalizer=f=600:width_type=o:width=2:g=-4",
            "equalizer=f=3500:width_type=o:width=1.5:g=5",
            "acompressor=ratio=6:threshold=-24dB:attack=2:release=100:makeup=2",
            "asoftclip=type=tanh:param=0.3",
            "lowpass=f=7000",
            "loudnorm=I=-16:TP=-1:LRA=4",
        ]:
            assert filt in filter_chain, f"Missing filter: {filt}"
        # Verify order: highpass first, loudnorm last
        assert filter_chain.index("highpass") < filter_chain.index("loudnorm")

    @patch("comadre.service.subprocess.run")
    def test_wav_format_without_noise_calls_ffmpeg_twice(
        self, mock_run: MagicMock
    ) -> None:
        mock_run.return_value = MagicMock(stdout=b"wav_data")
        wav = _create_wav_bytes()
        result = _apply_radio_warm(wav, "wav")
        assert result == b"wav_data"
        # Stage 1 (effects) + encode_final (second loudnorm)
        assert mock_run.call_count == 2


# --- Test OGG output path ---


class TestOggOutput:
    @patch("comadre.service.subprocess.run")
    def test_ogg_format_calls_ffmpeg_twice(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(stdout=b"ogg_data")
        wav = _create_wav_bytes()
        _apply_radio_warm(wav, "ogg")
        # Stage 1 (effects) + encode (to ogg)
        assert mock_run.call_count == 2

    @patch("comadre.service.subprocess.run")
    def test_ogg_encoding_params(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(stdout=b"ogg_data")
        wav = _create_wav_bytes()
        _apply_radio_warm(wav, "ogg")
        encode_call = mock_run.call_args_list[1]
        cmd_args = encode_call[0][0]
        assert "libopus" in cmd_args
        assert "ogg" in cmd_args
        assert "24k" in cmd_args  # bitrate
        assert "16000" in cmd_args  # sample rate
        assert "1" in cmd_args  # mono

    @patch("comadre.service.subprocess.run")
    def test_ogg_encode_final_includes_second_loudnorm(
        self, mock_run: MagicMock
    ) -> None:
        mock_run.return_value = MagicMock(stdout=b"ogg_data")
        wav = _create_wav_bytes()
        _apply_radio_warm(wav, "ogg")
        encode_call = mock_run.call_args_list[1]
        cmd_args = encode_call[0][0]
        af_idx = cmd_args.index("-af")
        assert "loudnorm=I=-17:TP=-1.5:LRA=7" in cmd_args[af_idx + 1]


# --- Test noise mixing ---


class TestNoiseMixing:
    @patch("comadre.service.subprocess.run")
    def test_noise_files_used_when_present(
        self, mock_run: MagicMock, tmp_path: Path
    ) -> None:
        mock_run.return_value = MagicMock(stdout=b"mixed_audio")
        room_file = tmp_path / "room.wav"
        hiss_file = tmp_path / "hiss.wav"
        room_file.write_bytes(_create_wav_bytes())
        hiss_file.write_bytes(_create_wav_bytes())

        wav = _create_wav_bytes()
        result = _apply_radio_warm(wav, "ogg", noise_dir=tmp_path)
        assert result == b"mixed_audio"
        # Stage 1 + stage 2 (with noise)
        assert mock_run.call_count == 2

    @patch("comadre.service.subprocess.run")
    def test_noise_filter_complex_content(
        self, mock_run: MagicMock, tmp_path: Path
    ) -> None:
        mock_run.return_value = MagicMock(stdout=b"mixed")
        (tmp_path / "room.wav").write_bytes(_create_wav_bytes())
        (tmp_path / "hiss.wav").write_bytes(_create_wav_bytes())

        _apply_radio_warm(_create_wav_bytes(), "ogg", noise_dir=tmp_path)
        stage2_call = mock_run.call_args_list[1]
        cmd_args = stage2_call[0][0]
        fc_idx = cmd_args.index("-filter_complex")
        fc = cmd_args[fc_idx + 1]
        assert "volume=0.45" in fc
        assert "volume=0.24" in fc
        assert "amix=inputs=3" in fc
        assert "loudnorm=I=-17:TP=-1.5:LRA=7" in fc

    @patch("comadre.service.subprocess.run")
    def test_missing_noise_falls_back_gracefully(
        self, mock_run: MagicMock, tmp_path: Path
    ) -> None:
        mock_run.return_value = MagicMock(stdout=b"clean_audio")
        wav = _create_wav_bytes()
        # noise_dir exists but has no noise files
        result = _apply_radio_warm(wav, "ogg", noise_dir=tmp_path)
        assert result == b"clean_audio"

    @patch("comadre.service.subprocess.run")
    def test_missing_noise_logs_warning(
        self,
        mock_run: MagicMock,
        tmp_path: Path,
        request_logger: pytest.LogCaptureFixture,
    ) -> None:
        mock_run.return_value = MagicMock(stdout=b"clean")
        with request_logger.at_level(logging.WARNING, logger="request"):
            _apply_radio_warm(_create_wav_bytes(), "ogg", noise_dir=tmp_path)
        warnings = [r for r in request_logger.records if r.levelno == logging.WARNING]
        assert any(
            "missing" in r.message.lower() or "noise" in r.message.lower()
            for r in warnings
        )


# --- Test multi-chunk generation ---


class TestMultiChunkGeneration:
    @patch("comadre.service._apply_radio_warm")
    @patch("comadre.service.chunk_text")
    @patch("comadre.service.normalize_text")
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
        engine.generate_speech("chunk one. chunk two.", "pm_santa", "wav")
        assert engine._kokoro.create.call_count == 2  # type: ignore[union-attr]

    @patch("comadre.service._apply_radio_warm")
    @patch("comadre.service.chunk_text")
    @patch("comadre.service.normalize_text")
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
        engine.generate_speech("short text", "pm_santa", "wav")
        assert engine._kokoro.create.call_count == 1  # type: ignore[union-attr]

    @patch("comadre.service._apply_radio_warm")
    def test_logs_chunk_count(
        self,
        mock_pipeline: MagicMock,
        engine: KokoroEngine,
        request_logger: pytest.LogCaptureFixture,
    ) -> None:
        mock_pipeline.return_value = b"audio"
        with request_logger.at_level(logging.DEBUG, logger="request"):
            engine.generate_speech("hello world", "pm_santa", "wav")
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
            svc.generate_speech("hello", "pm_santa", "wav")
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
            svc.generate_speech("hello", "pm_santa", "wav")
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
            patch("comadre.service.Kokoro", mock_kokoro_class, create=True),
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


# --- Test Kokoro builtin voice methods ---


class TestKokoroBuiltinVoices:
    def test_get_builtin_voices(self, engine: KokoroEngine) -> None:
        voices = engine.get_builtin_voices()
        assert "pm_santa" in voices
        assert "pf_dora" in voices
        assert "pm_alex" in voices

    def test_get_builtin_voices_when_not_loaded(self) -> None:
        engine = KokoroEngine()
        assert engine.get_builtin_voices() == []

    def test_get_voice_style(self, engine: KokoroEngine) -> None:
        result = engine.get_voice_style("pm_santa")
        assert isinstance(result, np.ndarray)


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
        assert values[2] == 16383  # 0.5 * 32767 ~ 16383


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


# ===== Qwen3 TTS Engine Tests =====

FAKE_REF_PATH = Path("/voices/qwen/female-reference.wav")


@pytest.fixture()
def qwen_engine() -> QwenEngine:
    """Return a QwenEngine with mock-verified paths."""
    engine = QwenEngine()
    engine._cli_path = "/usr/local/bin/qwen3-tts-cli"
    engine._model_path = "models/qwen3-tts-0.6b-q8_0.gguf"
    engine._tokenizer_path = "models/qwen3-tts-tokenizer-f16.gguf"
    engine._loaded = True
    return engine


# --- Qwen3 char limit validation ---


class TestQwenCharLimit:
    def test_char_limit_is_300(self) -> None:
        assert QwenEngine.CHAR_LIMIT == 300

    @patch("comadre.service._apply_whatsapp_subtle")
    @patch("comadre.service.subprocess.run")
    @patch("comadre.service.Path.read_bytes")
    @patch("comadre.service.Path.unlink")
    def test_text_at_limit_passes(
        self,
        _mock_unlink: MagicMock,
        mock_read: MagicMock,
        mock_run: MagicMock,
        mock_pipeline: MagicMock,
        qwen_engine: QwenEngine,
    ) -> None:
        mock_run.return_value = MagicMock(returncode=0)
        mock_read.return_value = _create_wav_bytes()
        mock_pipeline.return_value = b"audio"
        text = "a" * QwenEngine.CHAR_LIMIT
        result = qwen_engine.generate_speech(text, FAKE_REF_PATH, "wav")
        assert result == b"audio"

    def test_text_over_limit_raises(self, qwen_engine: QwenEngine) -> None:
        text = "a" * (QwenEngine.CHAR_LIMIT + 1)
        with pytest.raises(InvalidRequestError) as exc_info:
            qwen_engine.generate_speech(text, FAKE_REF_PATH, "wav")
        assert str(QwenEngine.CHAR_LIMIT) in exc_info.value.message
        assert exc_info.value.status_code == 400

    def test_error_hint_mentions_limit(self, qwen_engine: QwenEngine) -> None:
        text = "a" * (QwenEngine.CHAR_LIMIT + 1)
        with pytest.raises(InvalidRequestError) as exc_info:
            qwen_engine.generate_speech(text, FAKE_REF_PATH, "wav")
        assert str(QwenEngine.CHAR_LIMIT) in exc_info.value.hint


# --- Qwen3 empty text validation ---


class TestQwenEmptyText:
    def test_rejects_empty_string(self, qwen_engine: QwenEngine) -> None:
        with pytest.raises(InvalidRequestError) as exc_info:
            qwen_engine.generate_speech("", FAKE_REF_PATH, "wav")
        assert "empty" in exc_info.value.message.lower()

    def test_rejects_whitespace_only(self, qwen_engine: QwenEngine) -> None:
        with pytest.raises(InvalidRequestError):
            qwen_engine.generate_speech("   \n\t  ", FAKE_REF_PATH, "wav")


# --- Qwen3 response format validation ---


class TestQwenResponseFormat:
    def test_rejects_unsupported_format(self, qwen_engine: QwenEngine) -> None:
        with pytest.raises(InvalidRequestError) as exc_info:
            qwen_engine.generate_speech("hello", FAKE_REF_PATH, "mp3")
        assert "mp3" in exc_info.value.message


# --- Qwen3 subprocess CLI invocation ---


class TestQwenSubprocessInvocation:
    @patch("comadre.service._apply_whatsapp_subtle")
    @patch("comadre.service.subprocess.run")
    @patch("comadre.service.Path.read_bytes")
    @patch("comadre.service.Path.unlink")
    def test_passes_correct_cli_flags(
        self,
        _mock_unlink: MagicMock,
        mock_read: MagicMock,
        mock_run: MagicMock,
        mock_pipeline: MagicMock,
        qwen_engine: QwenEngine,
    ) -> None:
        mock_run.return_value = MagicMock(returncode=0)
        mock_read.return_value = _create_wav_bytes()
        mock_pipeline.return_value = b"audio"

        qwen_engine.generate_speech("Ola mundo", FAKE_REF_PATH, "ogg")

        cmd = mock_run.call_args[0][0]
        # Verify mandatory flags
        assert "-l" in cmd
        assert cmd[cmd.index("-l") + 1] == "pt"
        assert "--temperature" in cmd
        assert cmd[cmd.index("--temperature") + 1] == "0.7"
        assert "--top-p" in cmd
        assert cmd[cmd.index("--top-p") + 1] == "0.95"
        assert "--repetition-penalty" in cmd
        assert cmd[cmd.index("--repetition-penalty") + 1] == "1.05"
        assert "--seed" in cmd
        assert "-j" in cmd
        assert cmd[cmd.index("-j") + 1] == "4"

    @patch("comadre.service._apply_whatsapp_subtle")
    @patch("comadre.service.subprocess.run")
    @patch("comadre.service.Path.read_bytes")
    @patch("comadre.service.Path.unlink")
    def test_reference_path_passed_via_r_flag(
        self,
        _mock_unlink: MagicMock,
        mock_read: MagicMock,
        mock_run: MagicMock,
        mock_pipeline: MagicMock,
        qwen_engine: QwenEngine,
    ) -> None:
        mock_run.return_value = MagicMock(returncode=0)
        mock_read.return_value = _create_wav_bytes()
        mock_pipeline.return_value = b"audio"

        ref = Path("/voices/qwen/galvani.wav")
        qwen_engine.generate_speech("Ola", ref, "ogg")

        cmd = mock_run.call_args[0][0]
        assert "-r" in cmd
        r_idx = cmd.index("-r")
        assert cmd[r_idx + 1] == "/voices/qwen/galvani.wav"

    @patch("comadre.service._apply_whatsapp_subtle")
    @patch("comadre.service.subprocess.run")
    @patch("comadre.service.Path.read_bytes")
    @patch("comadre.service.Path.unlink")
    def test_seed_parameter_passed(
        self,
        _mock_unlink: MagicMock,
        mock_read: MagicMock,
        mock_run: MagicMock,
        mock_pipeline: MagicMock,
        qwen_engine: QwenEngine,
    ) -> None:
        mock_run.return_value = MagicMock(returncode=0)
        mock_read.return_value = _create_wav_bytes()
        mock_pipeline.return_value = b"audio"

        qwen_engine.generate_speech("Ola", FAKE_REF_PATH, "ogg", seed=42)

        cmd = mock_run.call_args[0][0]
        seed_idx = cmd.index("--seed")
        assert cmd[seed_idx + 1] == "42"

    @patch("comadre.service._apply_whatsapp_subtle")
    @patch("comadre.service.subprocess.run")
    @patch("comadre.service.Path.read_bytes")
    @patch("comadre.service.Path.unlink")
    def test_default_seed_is_negative_one(
        self,
        _mock_unlink: MagicMock,
        mock_read: MagicMock,
        mock_run: MagicMock,
        mock_pipeline: MagicMock,
        qwen_engine: QwenEngine,
    ) -> None:
        mock_run.return_value = MagicMock(returncode=0)
        mock_read.return_value = _create_wav_bytes()
        mock_pipeline.return_value = b"audio"

        qwen_engine.generate_speech("Ola", FAKE_REF_PATH, "ogg")

        cmd = mock_run.call_args[0][0]
        seed_idx = cmd.index("--seed")
        assert cmd[seed_idx + 1] == "-1"

    @patch("comadre.service._apply_whatsapp_subtle")
    @patch("comadre.service.subprocess.run")
    @patch("comadre.service.Path.read_bytes")
    @patch("comadre.service.Path.unlink")
    def test_max_tokens_calculated_dynamically(
        self,
        _mock_unlink: MagicMock,
        mock_read: MagicMock,
        mock_run: MagicMock,
        mock_pipeline: MagicMock,
        qwen_engine: QwenEngine,
    ) -> None:
        mock_run.return_value = MagicMock(returncode=0)
        mock_read.return_value = _create_wav_bytes()
        mock_pipeline.return_value = b"audio"

        text = "a" * 100  # 100 chars -> min(4096, max(100, 800)) = 800
        qwen_engine.generate_speech(text, FAKE_REF_PATH, "ogg")

        cmd = mock_run.call_args[0][0]
        mt_idx = cmd.index("--max-tokens")
        assert cmd[mt_idx + 1] == "800"

    @patch("comadre.service._apply_whatsapp_subtle")
    @patch("comadre.service.subprocess.run")
    @patch("comadre.service.Path.read_bytes")
    @patch("comadre.service.Path.unlink")
    def test_text_passed_through_expand_siglas(
        self,
        _mock_unlink: MagicMock,
        mock_read: MagicMock,
        mock_run: MagicMock,
        mock_pipeline: MagicMock,
        qwen_engine: QwenEngine,
    ) -> None:
        mock_run.return_value = MagicMock(returncode=0)
        mock_read.return_value = _create_wav_bytes()
        mock_pipeline.return_value = b"audio"

        qwen_engine.generate_speech("Seu CNPJ e valido", FAKE_REF_PATH, "ogg")

        cmd = mock_run.call_args[0][0]
        t_idx = cmd.index("-t")
        assert cmd[t_idx + 1] == "Seu C N P J e valido"

    @patch("comadre.service._apply_whatsapp_subtle")
    @patch("comadre.service.subprocess.run")
    @patch("comadre.service.Path.read_bytes")
    @patch("comadre.service.Path.unlink")
    def test_output_path_and_model_paths_in_cmd(
        self,
        _mock_unlink: MagicMock,
        mock_read: MagicMock,
        mock_run: MagicMock,
        mock_pipeline: MagicMock,
        qwen_engine: QwenEngine,
    ) -> None:
        mock_run.return_value = MagicMock(returncode=0)
        mock_read.return_value = _create_wav_bytes()
        mock_pipeline.return_value = b"audio"

        qwen_engine.generate_speech("Ola", FAKE_REF_PATH, "ogg")

        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "/usr/local/bin/qwen3-tts-cli"
        m_idx = cmd.index("-m")
        assert cmd[m_idx + 1] == "models"
        assert "-o" in cmd

    @patch("comadre.service._apply_whatsapp_subtle")
    @patch("comadre.service.subprocess.run")
    @patch("comadre.service.Path.read_bytes")
    @patch("comadre.service.Path.unlink")
    def test_max_tokens_uses_raw_text_length(
        self,
        _mock_unlink: MagicMock,
        mock_read: MagicMock,
        mock_run: MagicMock,
        mock_pipeline: MagicMock,
        qwen_engine: QwenEngine,
    ) -> None:
        """max_tokens is computed from raw text, not expanded siglas."""
        mock_run.return_value = MagicMock(returncode=0)
        mock_read.return_value = _create_wav_bytes()
        mock_pipeline.return_value = b"audio"

        # "CNPJ" is 4 raw chars -> max_tokens = max(100, 4*8) = 100
        qwen_engine.generate_speech("CNPJ", FAKE_REF_PATH, "ogg")

        cmd = mock_run.call_args[0][0]
        mt_idx = cmd.index("--max-tokens")
        assert cmd[mt_idx + 1] == "100"


# --- Qwen3 subprocess error handling ---


class TestQwenSubprocessErrors:
    @patch("comadre.service.subprocess.run")
    @patch("comadre.service.Path.unlink")
    def test_timeout_raises_generation_error(
        self,
        _mock_unlink: MagicMock,
        mock_run: MagicMock,
        qwen_engine: QwenEngine,
        request_logger: pytest.LogCaptureFixture,
    ) -> None:
        mock_run.side_effect = subprocess.TimeoutExpired(
            cmd="qwen3-tts-cli", timeout=60
        )
        with (
            request_logger.at_level(logging.ERROR, logger="request"),
            pytest.raises(GenerationError, match="timed out"),
        ):
            qwen_engine.generate_speech("Ola", FAKE_REF_PATH, "ogg")

    @patch("comadre.service.subprocess.run")
    @patch("comadre.service.Path.unlink")
    def test_called_process_error_raises_generation_error(
        self,
        _mock_unlink: MagicMock,
        mock_run: MagicMock,
        qwen_engine: QwenEngine,
        request_logger: pytest.LogCaptureFixture,
    ) -> None:
        mock_run.side_effect = subprocess.CalledProcessError(
            returncode=1, cmd="qwen3-tts-cli", stderr=b"segfault"
        )
        with (
            request_logger.at_level(logging.ERROR, logger="request"),
            pytest.raises(GenerationError, match="failed"),
        ):
            qwen_engine.generate_speech("Ola", FAKE_REF_PATH, "ogg")

    def test_subprocess_timeout_is_60s(self, qwen_engine: QwenEngine) -> None:
        with (
            patch("comadre.service.subprocess.run") as mock_run,
            patch("comadre.service.Path.read_bytes", return_value=_create_wav_bytes()),
            patch("comadre.service._apply_whatsapp_subtle", return_value=b"audio"),
            patch("comadre.service.Path.unlink"),
        ):
            mock_run.return_value = MagicMock(returncode=0)
            qwen_engine.generate_speech("Ola", FAKE_REF_PATH, "ogg")
            assert mock_run.call_args.kwargs["timeout"] == 60


# --- Qwen3 model not loaded ---


class TestQwenModelNotLoaded:
    def test_raises_generation_error_when_not_loaded(self) -> None:
        engine = QwenEngine()
        assert not engine.is_loaded
        with pytest.raises(GenerationError, match="Engine not loaded"):
            engine.generate_speech("hello", FAKE_REF_PATH, "wav")

    def test_warm_up_raises_when_not_loaded(self) -> None:
        engine = QwenEngine()
        with pytest.raises(GenerationError, match="Engine not loaded"):
            engine.warm_up()


# --- Qwen3 load_model ---


def _setup_qwen_files(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Create CLI binary, model, and tokenizer in tmp_path."""
    cli = tmp_path / "qwen3-tts-cli"
    cli.write_bytes(b"#!/bin/sh\n")
    cli.chmod(0o755)
    model = tmp_path / "model.gguf"
    model.write_bytes(b"GGUF")
    tokenizer = tmp_path / "tokenizer.gguf"
    tokenizer.write_bytes(b"GGUF")
    return cli, model, tokenizer


class TestQwenLoadModel:
    def test_load_model_sets_loaded(self, tmp_path: Path) -> None:
        cli, model, tok = _setup_qwen_files(tmp_path)
        engine = QwenEngine()
        engine.load_model(str(cli), str(model), str(tok))
        assert engine.is_loaded

    def test_load_model_missing_cli_raises(self, tmp_path: Path) -> None:
        _, model, tok = _setup_qwen_files(tmp_path)
        engine = QwenEngine()
        with pytest.raises(FileNotFoundError, match="binary not found"):
            engine.load_model(str(tmp_path / "nonexistent"), str(model), str(tok))

    def test_load_model_non_executable_cli_raises(self, tmp_path: Path) -> None:
        cli, model, tok = _setup_qwen_files(tmp_path)
        cli.chmod(0o644)
        engine = QwenEngine()
        with pytest.raises(PermissionError, match="not executable"):
            engine.load_model(str(cli), str(model), str(tok))

    def test_load_model_missing_model_raises(self, tmp_path: Path) -> None:
        cli, _, tok = _setup_qwen_files(tmp_path)
        engine = QwenEngine()
        with pytest.raises(FileNotFoundError, match="model file not found"):
            engine.load_model(str(cli), str(tmp_path / "x.gguf"), str(tok))

    def test_load_model_missing_tokenizer_raises(self, tmp_path: Path) -> None:
        cli, model, _ = _setup_qwen_files(tmp_path)
        engine = QwenEngine()
        with pytest.raises(FileNotFoundError, match="tokenizer file not found"):
            engine.load_model(str(cli), str(model), str(tmp_path / "x.gguf"))

    def test_load_model_with_custom_threads(self, tmp_path: Path) -> None:
        cli, model, tok = _setup_qwen_files(tmp_path)
        engine = QwenEngine()
        engine.load_model(str(cli), str(model), str(tok), threads=8)
        assert engine._threads == 8


# --- Qwen3 warm_up ---


class TestQwenWarmUp:
    def test_warm_up_skips_when_no_reference(
        self,
        qwen_engine: QwenEngine,
        startup_logger: pytest.LogCaptureFixture,
    ) -> None:
        with startup_logger.at_level(logging.INFO, logger="startup"):
            qwen_engine.warm_up(reference_path=None)
        assert any(
            "skipping warm-up" in r.message.lower() for r in startup_logger.records
        )


# --- whatsapp-subtle pipeline ---


class TestWhatsappSubtlePipeline:
    @patch("comadre.service.subprocess.run")
    def test_calls_ffmpeg_with_whatsapp_subtle_filter(
        self, mock_run: MagicMock
    ) -> None:
        mock_run.return_value = MagicMock(stdout=b"processed")
        wav = _create_wav_bytes()
        _apply_whatsapp_subtle(wav, "wav")
        assert mock_run.call_count >= 1

    @patch("comadre.service.subprocess.run")
    def test_stage1_filter_chain_complete(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(stdout=b"processed")
        wav = _create_wav_bytes()
        _apply_whatsapp_subtle(wav, "wav")
        stage1_call = mock_run.call_args_list[0]
        cmd_args = stage1_call[0][0]
        af_idx = cmd_args.index("-af")
        filter_chain = cmd_args[af_idx + 1]
        for filt in [
            "highpass=f=100",
            "equalizer=f=200:width_type=o:width=1.5:g=1.5",
            "equalizer=f=700:width_type=o:width=1.5:g=-2",
            "equalizer=f=3000:width_type=o:width=1.5:g=3",
            "equalizer=f=7000:width_type=o:width=1.5:g=-4",
            "acompressor=threshold=0.15:ratio=6:attack=15:release=200:makeup=5",
            "lowpass=f=8000",
            "aecho=0.8:0.85:40:0.12",
            "atempo=1.15",
            "loudnorm=I=-18:TP=-2:LRA=7",
        ]:
            assert filt in filter_chain, f"Missing filter: {filt}"
        # No vibrato in whatsapp-subtle
        assert "vibrato" not in filter_chain

    @patch("comadre.service.subprocess.run")
    def test_wav_format_without_noise_calls_ffmpeg_twice(
        self, mock_run: MagicMock
    ) -> None:
        mock_run.return_value = MagicMock(stdout=b"wav_data")
        wav = _create_wav_bytes()
        result = _apply_whatsapp_subtle(wav, "wav")
        assert result == b"wav_data"
        assert mock_run.call_count == 2

    @patch("comadre.service.subprocess.run")
    def test_ogg_format_calls_ffmpeg_twice(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(stdout=b"ogg_data")
        wav = _create_wav_bytes()
        _apply_whatsapp_subtle(wav, "ogg")
        assert mock_run.call_count == 2

    @patch("comadre.service.subprocess.run")
    def test_ogg_encoding_params(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(stdout=b"ogg_data")
        wav = _create_wav_bytes()
        _apply_whatsapp_subtle(wav, "ogg")
        encode_call = mock_run.call_args_list[1]
        cmd_args = encode_call[0][0]
        assert "libopus" in cmd_args
        assert "ogg" in cmd_args


# --- whatsapp-subtle noise mixing with Qwen3 volumes ---


class TestWhatsappSubtleNoiseMixing:
    @patch("comadre.service.subprocess.run")
    def test_qwen3_noise_volumes(self, mock_run: MagicMock, tmp_path: Path) -> None:
        mock_run.return_value = MagicMock(stdout=b"mixed")
        (tmp_path / "room.wav").write_bytes(_create_wav_bytes())
        (tmp_path / "hiss.wav").write_bytes(_create_wav_bytes())

        _apply_whatsapp_subtle(_create_wav_bytes(), "ogg", noise_dir=tmp_path)
        stage2_call = mock_run.call_args_list[1]
        cmd_args = stage2_call[0][0]
        fc_idx = cmd_args.index("-filter_complex")
        fc = cmd_args[fc_idx + 1]
        assert "volume=0.15" in fc  # Qwen3 room volume
        assert "volume=0.08" in fc  # Qwen3 hiss volume

    @patch("comadre.service.subprocess.run")
    def test_missing_noise_falls_back_gracefully(
        self, mock_run: MagicMock, tmp_path: Path
    ) -> None:
        mock_run.return_value = MagicMock(stdout=b"clean")
        result = _apply_whatsapp_subtle(_create_wav_bytes(), "ogg", noise_dir=tmp_path)
        assert result == b"clean"


# --- Noise volume refactoring backward compat ---


class TestNoiseVolumeRefactoring:
    @patch("comadre.service.subprocess.run")
    def test_radio_warm_still_uses_kokoro_volumes(
        self, mock_run: MagicMock, tmp_path: Path
    ) -> None:
        """Regression: radio_warm must still pass 0.45/0.24 after refactoring."""
        mock_run.return_value = MagicMock(stdout=b"mixed")
        (tmp_path / "room.wav").write_bytes(_create_wav_bytes())
        (tmp_path / "hiss.wav").write_bytes(_create_wav_bytes())

        _apply_radio_warm(_create_wav_bytes(), "ogg", noise_dir=tmp_path)
        stage2_call = mock_run.call_args_list[1]
        cmd_args = stage2_call[0][0]
        fc_idx = cmd_args.index("-filter_complex")
        fc = cmd_args[fc_idx + 1]
        assert "volume=0.45" in fc  # Kokoro room volume unchanged
        assert "volume=0.24" in fc  # Kokoro hiss volume unchanged

    @patch("comadre.service.subprocess.run")
    def test_whatsapp_subtle_uses_qwen3_volumes(
        self, mock_run: MagicMock, tmp_path: Path
    ) -> None:
        """Qwen3 uses lower noise volumes than Kokoro."""
        mock_run.return_value = MagicMock(stdout=b"mixed")
        (tmp_path / "room.wav").write_bytes(_create_wav_bytes())
        (tmp_path / "hiss.wav").write_bytes(_create_wav_bytes())

        _apply_whatsapp_subtle(_create_wav_bytes(), "ogg", noise_dir=tmp_path)
        stage2_call = mock_run.call_args_list[1]
        cmd_args = stage2_call[0][0]
        fc_idx = cmd_args.index("-filter_complex")
        fc = cmd_args[fc_idx + 1]
        assert "volume=0.15" in fc
        assert "volume=0.08" in fc
