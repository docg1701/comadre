"""Tests for the Kokoro TTS engine service."""

import io
import logging
import subprocess
import wave
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from cumadre.exceptions import GenerationError, InvalidRequestError, VoiceNotFoundError
from cumadre.service import (
    KOKORO_CHAR_LIMIT,
    KOKORO_VOICES,
    QWEN_CHAR_LIMIT,
    QWEN_VOICES,
    KokoroEngine,
    QwenEngine,
    _apply_vibrato_warm,
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


# ===== Qwen3 TTS Engine Tests =====


@pytest.fixture()
def qwen_engine() -> QwenEngine:
    """Return a QwenEngine with mock-verified paths."""
    engine = QwenEngine()
    engine._cli_path = "/usr/local/bin/qwen3-tts-cli"
    engine._model_path = "models/qwen3-tts-0.6b-q8_0.gguf"
    engine._tokenizer_path = "models/qwen3-tts-tokenizer-f16.gguf"
    engine._voice_references = {
        "qwen-female": "/voices/female-reference.wav",
        "qwen-male": "/voices/male-reference.wav",
    }
    engine._loaded = True
    return engine


# --- Qwen3 voice mapping ---


class TestQwenVoiceMapping:
    def test_qwen_voices_contains_clone(self) -> None:
        assert QWEN_VOICES["clone"] == "clone"

    def test_qwen_voices_contains_female(self) -> None:
        assert QWEN_VOICES["qwen-female"] == "female"

    def test_qwen_voices_contains_male(self) -> None:
        assert QWEN_VOICES["qwen-male"] == "male"

    def test_qwen_voices_only_three(self) -> None:
        assert len(QWEN_VOICES) == 3


# --- Qwen3 voice not found ---


class TestQwenVoiceNotFound:
    def test_unknown_voice_raises(self, qwen_engine: QwenEngine) -> None:
        with pytest.raises(VoiceNotFoundError) as exc_info:
            qwen_engine.generate_speech("hello", "ghost", "wav")
        assert exc_info.value.voice == "ghost"

    def test_error_lists_available_qwen_voices(self, qwen_engine: QwenEngine) -> None:
        with pytest.raises(VoiceNotFoundError) as exc_info:
            qwen_engine.generate_speech("hello", "ghost", "wav")
        assert "clone" in exc_info.value.available
        assert "qwen-female" in exc_info.value.available
        assert "qwen-male" in exc_info.value.available


# --- Qwen3 clone reference handling ---


class TestQwenCloneReference:
    def test_clone_without_reference_raises(self, qwen_engine: QwenEngine) -> None:
        assert "clone" not in qwen_engine._voice_references
        with pytest.raises(VoiceNotFoundError) as exc_info:
            qwen_engine.generate_speech("Olá", "clone", "ogg")
        assert exc_info.value.voice == "clone"

    def test_clone_without_reference_excludes_clone_from_available(
        self, qwen_engine: QwenEngine
    ) -> None:
        assert "clone" not in qwen_engine._voice_references
        with pytest.raises(VoiceNotFoundError) as exc_info:
            qwen_engine.generate_speech("Olá", "clone", "ogg")
        assert "clone" not in exc_info.value.available

    @patch("cumadre.service._apply_whatsapp_subtle")
    @patch("cumadre.service.subprocess.run")
    @patch("cumadre.service.Path.read_bytes")
    @patch("cumadre.service.Path.unlink")
    def test_clone_with_reference_includes_r_flag(
        self,
        _mock_unlink: MagicMock,
        mock_read: MagicMock,
        mock_run: MagicMock,
        mock_pipeline: MagicMock,
        qwen_engine: QwenEngine,
    ) -> None:
        qwen_engine._voice_references["clone"] = "/voices/clone-ref.wav"
        mock_run.return_value = MagicMock(returncode=0)
        mock_read.return_value = _create_wav_bytes()
        mock_pipeline.return_value = b"audio"

        qwen_engine.generate_speech("Olá", "clone", "ogg")

        cmd = mock_run.call_args[0][0]
        assert "-r" in cmd
        r_idx = cmd.index("-r")
        assert cmd[r_idx + 1] == "/voices/clone-ref.wav"

    @patch("cumadre.service._apply_whatsapp_subtle")
    @patch("cumadre.service.subprocess.run")
    @patch("cumadre.service.Path.read_bytes")
    @patch("cumadre.service.Path.unlink")
    def test_female_voice_passes_female_reference(
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

        qwen_engine.generate_speech("Olá", "qwen-female", "ogg")

        cmd = mock_run.call_args[0][0]
        assert "-r" in cmd
        r_idx = cmd.index("-r")
        assert cmd[r_idx + 1] == "/voices/female-reference.wav"

    @patch("cumadre.service._apply_whatsapp_subtle")
    @patch("cumadre.service.subprocess.run")
    @patch("cumadre.service.Path.read_bytes")
    @patch("cumadre.service.Path.unlink")
    def test_male_voice_passes_male_reference(
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

        qwen_engine.generate_speech("Olá", "qwen-male", "ogg")

        cmd = mock_run.call_args[0][0]
        assert "-r" in cmd
        r_idx = cmd.index("-r")
        assert cmd[r_idx + 1] == "/voices/male-reference.wav"

    def test_is_clone_configured_true(self, qwen_engine: QwenEngine) -> None:
        qwen_engine._voice_references["clone"] = "/voices/ref.wav"
        assert qwen_engine.is_clone_configured is True

    def test_is_clone_configured_false(self, qwen_engine: QwenEngine) -> None:
        assert qwen_engine.is_clone_configured is False


# --- Qwen3 char limit validation ---


class TestQwenCharLimit:
    def test_char_limit_is_300(self) -> None:
        assert QWEN_CHAR_LIMIT == 300

    @patch("cumadre.service._apply_whatsapp_subtle")
    @patch("cumadre.service.subprocess.run")
    @patch("cumadre.service.Path.read_bytes")
    @patch("cumadre.service.Path.unlink")
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
        text = "a" * QWEN_CHAR_LIMIT
        result = qwen_engine.generate_speech(text, "qwen-female", "wav")
        assert result == b"audio"

    def test_text_over_limit_raises(self, qwen_engine: QwenEngine) -> None:
        text = "a" * (QWEN_CHAR_LIMIT + 1)
        with pytest.raises(InvalidRequestError) as exc_info:
            qwen_engine.generate_speech(text, "qwen-female", "wav")
        assert str(QWEN_CHAR_LIMIT) in exc_info.value.message
        assert exc_info.value.status_code == 400

    def test_error_hint_mentions_limit(self, qwen_engine: QwenEngine) -> None:
        text = "a" * (QWEN_CHAR_LIMIT + 1)
        with pytest.raises(InvalidRequestError) as exc_info:
            qwen_engine.generate_speech(text, "qwen-female", "wav")
        assert str(QWEN_CHAR_LIMIT) in exc_info.value.hint


# --- Qwen3 empty text validation ---


class TestQwenEmptyText:
    def test_rejects_empty_string(self, qwen_engine: QwenEngine) -> None:
        with pytest.raises(InvalidRequestError) as exc_info:
            qwen_engine.generate_speech("", "qwen-female", "wav")
        assert "empty" in exc_info.value.message.lower()

    def test_rejects_whitespace_only(self, qwen_engine: QwenEngine) -> None:
        with pytest.raises(InvalidRequestError):
            qwen_engine.generate_speech("   \n\t  ", "qwen-female", "wav")


# --- Qwen3 response format validation ---


class TestQwenResponseFormat:
    def test_rejects_unsupported_format(self, qwen_engine: QwenEngine) -> None:
        with pytest.raises(InvalidRequestError) as exc_info:
            qwen_engine.generate_speech("hello", "qwen-female", "mp3")
        assert "mp3" in exc_info.value.message


# --- Qwen3 subprocess CLI invocation ---


class TestQwenSubprocessInvocation:
    @patch("cumadre.service._apply_whatsapp_subtle")
    @patch("cumadre.service.subprocess.run")
    @patch("cumadre.service.Path.read_bytes")
    @patch("cumadre.service.Path.unlink")
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

        qwen_engine.generate_speech("Olá mundo", "qwen-female", "ogg")

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

    @patch("cumadre.service._apply_whatsapp_subtle")
    @patch("cumadre.service.subprocess.run")
    @patch("cumadre.service.Path.read_bytes")
    @patch("cumadre.service.Path.unlink")
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

        qwen_engine.generate_speech("Olá", "qwen-female", "ogg", seed=42)

        cmd = mock_run.call_args[0][0]
        seed_idx = cmd.index("--seed")
        assert cmd[seed_idx + 1] == "42"

    @patch("cumadre.service._apply_whatsapp_subtle")
    @patch("cumadre.service.subprocess.run")
    @patch("cumadre.service.Path.read_bytes")
    @patch("cumadre.service.Path.unlink")
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

        qwen_engine.generate_speech("Olá", "qwen-female", "ogg")

        cmd = mock_run.call_args[0][0]
        seed_idx = cmd.index("--seed")
        assert cmd[seed_idx + 1] == "-1"

    @patch("cumadre.service._apply_whatsapp_subtle")
    @patch("cumadre.service.subprocess.run")
    @patch("cumadre.service.Path.read_bytes")
    @patch("cumadre.service.Path.unlink")
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
        qwen_engine.generate_speech(text, "qwen-female", "ogg")

        cmd = mock_run.call_args[0][0]
        mt_idx = cmd.index("--max-tokens")
        assert cmd[mt_idx + 1] == "800"

    @patch("cumadre.service._apply_whatsapp_subtle")
    @patch("cumadre.service.subprocess.run")
    @patch("cumadre.service.Path.read_bytes")
    @patch("cumadre.service.Path.unlink")
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

        qwen_engine.generate_speech("Seu CNPJ é válido", "qwen-female", "ogg")

        cmd = mock_run.call_args[0][0]
        # Last argument is the text, should have expanded CNPJ
        assert cmd[-1] == "Seu C N P J é válido"

    @patch("cumadre.service._apply_whatsapp_subtle")
    @patch("cumadre.service.subprocess.run")
    @patch("cumadre.service.Path.read_bytes")
    @patch("cumadre.service.Path.unlink")
    def test_all_voices_pass_r_flag(
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

        qwen_engine.generate_speech("Olá", "qwen-female", "ogg")

        cmd = mock_run.call_args[0][0]
        assert "-r" in cmd

    @patch("cumadre.service._apply_whatsapp_subtle")
    @patch("cumadre.service.subprocess.run")
    @patch("cumadre.service.Path.read_bytes")
    @patch("cumadre.service.Path.unlink")
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

        qwen_engine.generate_speech("Olá", "qwen-female", "ogg")

        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "/usr/local/bin/qwen3-tts-cli"
        m_idx = cmd.index("-m")
        assert cmd[m_idx + 1] == "models/qwen3-tts-0.6b-q8_0.gguf"
        t_idx = cmd.index("-t")
        assert cmd[t_idx + 1] == "models/qwen3-tts-tokenizer-f16.gguf"
        assert "-o" in cmd

    @patch("cumadre.service._apply_whatsapp_subtle")
    @patch("cumadre.service.subprocess.run")
    @patch("cumadre.service.Path.read_bytes")
    @patch("cumadre.service.Path.unlink")
    def test_double_dash_separator_before_text(
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

        qwen_engine.generate_speech("Olá", "qwen-female", "ogg")

        cmd = mock_run.call_args[0][0]
        assert "--" in cmd
        dd_idx = cmd.index("--")
        assert cmd[dd_idx + 1] == "Olá"
        assert cmd[-1] == "Olá"

    @patch("cumadre.service._apply_whatsapp_subtle")
    @patch("cumadre.service.subprocess.run")
    @patch("cumadre.service.Path.read_bytes")
    @patch("cumadre.service.Path.unlink")
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

        # "CNPJ" is 4 raw chars → max_tokens = max(100, 4*8) = 100
        # After expand_siglas: "C N P J" is 7 chars → would be 56 if used
        qwen_engine.generate_speech("CNPJ", "qwen-female", "ogg")

        cmd = mock_run.call_args[0][0]
        mt_idx = cmd.index("--max-tokens")
        # 4 raw chars * 8 = 32, max(100, 32) = 100, min(4096, 100) = 100
        assert cmd[mt_idx + 1] == "100"


# --- Qwen3 subprocess error handling ---


class TestQwenSubprocessErrors:
    @patch("cumadre.service.subprocess.run")
    @patch("cumadre.service.Path.unlink")
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
            qwen_engine.generate_speech("Olá", "qwen-female", "ogg")

    @patch("cumadre.service.subprocess.run")
    @patch("cumadre.service.Path.unlink")
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
            qwen_engine.generate_speech("Olá", "qwen-female", "ogg")

    def test_subprocess_timeout_is_60s(self, qwen_engine: QwenEngine) -> None:
        with (
            patch("cumadre.service.subprocess.run") as mock_run,
            patch("cumadre.service.Path.read_bytes", return_value=_create_wav_bytes()),
            patch("cumadre.service._apply_whatsapp_subtle", return_value=b"audio"),
            patch("cumadre.service.Path.unlink"),
        ):
            mock_run.return_value = MagicMock(returncode=0)
            qwen_engine.generate_speech("Olá", "qwen-female", "ogg")
            assert mock_run.call_args.kwargs["timeout"] == 60


# --- Qwen3 model not loaded ---


class TestQwenModelNotLoaded:
    def test_raises_runtime_error_when_not_loaded(self) -> None:
        engine = QwenEngine()
        assert not engine.is_loaded
        with pytest.raises(RuntimeError, match="Engine not loaded"):
            engine.generate_speech("hello", "qwen-female", "wav")

    def test_warm_up_raises_when_not_loaded(self) -> None:
        engine = QwenEngine()
        with pytest.raises(RuntimeError, match="Engine not loaded"):
            engine.warm_up()


# --- Qwen3 load_model ---


def _create_ref_wav(path: Path, duration_s: int = 5) -> None:
    """Create a valid reference WAV file at the given path."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(b"\x00\x00" * 16000 * duration_s)
    path.write_bytes(buf.getvalue())


def _setup_qwen_files(tmp_path: Path) -> tuple[Path, Path, Path, Path, Path]:
    """Create CLI binary, model, tokenizer, and reference WAVs in tmp_path."""
    cli = tmp_path / "qwen3-tts-cli"
    cli.write_bytes(b"#!/bin/sh\n")
    cli.chmod(0o755)
    model = tmp_path / "model.gguf"
    model.write_bytes(b"GGUF")
    tokenizer = tmp_path / "tokenizer.gguf"
    tokenizer.write_bytes(b"GGUF")
    female_ref = tmp_path / "female-reference.wav"
    _create_ref_wav(female_ref)
    male_ref = tmp_path / "male-reference.wav"
    _create_ref_wav(male_ref)
    return cli, model, tokenizer, female_ref, male_ref


class TestQwenLoadModel:
    def test_load_model_sets_loaded(self, tmp_path: Path) -> None:
        cli, model, tok, fref, mref = _setup_qwen_files(tmp_path)
        engine = QwenEngine()
        engine.load_model(str(cli), str(model), str(tok), str(fref), str(mref))
        assert engine.is_loaded

    def test_load_model_configures_female_and_male(self, tmp_path: Path) -> None:
        cli, model, tok, fref, mref = _setup_qwen_files(tmp_path)
        engine = QwenEngine()
        engine.load_model(str(cli), str(model), str(tok), str(fref), str(mref))
        assert "qwen-female" in engine._voice_references
        assert "qwen-male" in engine._voice_references
        assert not engine.is_clone_configured

    def test_load_model_missing_cli_raises(self, tmp_path: Path) -> None:
        _, model, tok, fref, mref = _setup_qwen_files(tmp_path)
        engine = QwenEngine()
        with pytest.raises(FileNotFoundError, match="binary not found"):
            engine.load_model(
                str(tmp_path / "nonexistent"),
                str(model),
                str(tok),
                str(fref),
                str(mref),
            )

    def test_load_model_non_executable_cli_raises(self, tmp_path: Path) -> None:
        cli, model, tok, fref, mref = _setup_qwen_files(tmp_path)
        cli.chmod(0o644)
        engine = QwenEngine()
        with pytest.raises(PermissionError, match="not executable"):
            engine.load_model(
                str(cli),
                str(model),
                str(tok),
                str(fref),
                str(mref),
            )

    def test_load_model_missing_model_raises(self, tmp_path: Path) -> None:
        cli, _, tok, fref, mref = _setup_qwen_files(tmp_path)
        engine = QwenEngine()
        with pytest.raises(FileNotFoundError, match="model file not found"):
            engine.load_model(
                str(cli),
                str(tmp_path / "x.gguf"),
                str(tok),
                str(fref),
                str(mref),
            )

    def test_load_model_missing_tokenizer_raises(self, tmp_path: Path) -> None:
        cli, model, _, fref, mref = _setup_qwen_files(tmp_path)
        engine = QwenEngine()
        with pytest.raises(FileNotFoundError, match="tokenizer file not found"):
            engine.load_model(
                str(cli),
                str(model),
                str(tmp_path / "x.gguf"),
                str(fref),
                str(mref),
            )

    def test_load_model_missing_female_ref_raises(self, tmp_path: Path) -> None:
        cli, model, tok, _, mref = _setup_qwen_files(tmp_path)
        engine = QwenEngine()
        with pytest.raises(FileNotFoundError, match="Female reference"):
            engine.load_model(
                str(cli),
                str(model),
                str(tok),
                str(tmp_path / "missing.wav"),
                str(mref),
            )

    def test_load_model_missing_male_ref_raises(self, tmp_path: Path) -> None:
        cli, model, tok, fref, _ = _setup_qwen_files(tmp_path)
        engine = QwenEngine()
        with pytest.raises(FileNotFoundError, match="Male reference"):
            engine.load_model(
                str(cli),
                str(model),
                str(tok),
                str(fref),
                str(tmp_path / "missing.wav"),
            )

    def test_load_model_with_clone_reference(self, tmp_path: Path) -> None:
        cli, model, tok, fref, mref = _setup_qwen_files(tmp_path)
        clone_ref = tmp_path / "clone-ref.wav"
        _create_ref_wav(clone_ref)

        engine = QwenEngine()
        engine.load_model(
            str(cli),
            str(model),
            str(tok),
            str(fref),
            str(mref),
            clone_reference_path=str(clone_ref),
        )
        assert engine.is_clone_configured
        assert "clone" in engine._voice_references

    def test_load_model_missing_clone_ref_raises(self, tmp_path: Path) -> None:
        cli, model, tok, fref, mref = _setup_qwen_files(tmp_path)
        engine = QwenEngine()
        with pytest.raises(FileNotFoundError, match="Clone reference"):
            engine.load_model(
                str(cli),
                str(model),
                str(tok),
                str(fref),
                str(mref),
                clone_reference_path=str(tmp_path / "missing.wav"),
            )

    def test_load_model_corrupt_ref_raises(self, tmp_path: Path) -> None:
        cli, model, tok, _, mref = _setup_qwen_files(tmp_path)
        corrupt = tmp_path / "corrupt.wav"
        corrupt.write_bytes(b"not a wav file at all")
        engine = QwenEngine()
        with pytest.raises(ValueError, match="not a valid WAV"):
            engine.load_model(
                str(cli),
                str(model),
                str(tok),
                str(corrupt),
                str(mref),
            )

    def test_load_model_short_duration_warns(
        self,
        tmp_path: Path,
        startup_logger: pytest.LogCaptureFixture,
    ) -> None:
        cli, model, tok, _, mref = _setup_qwen_files(tmp_path)
        short = tmp_path / "short.wav"
        _create_ref_wav(short, duration_s=1)
        engine = QwenEngine()
        with startup_logger.at_level(logging.WARNING, logger="startup"):
            engine.load_model(
                str(cli),
                str(model),
                str(tok),
                str(short),
                str(mref),
            )
        assert any("outside 3-10s range" in r.message for r in startup_logger.records)

    def test_load_model_failure_leaves_no_partial_state(self, tmp_path: Path) -> None:
        cli, model, tok, _, mref = _setup_qwen_files(tmp_path)
        corrupt = tmp_path / "corrupt.wav"
        corrupt.write_bytes(b"not a wav")
        engine = QwenEngine()
        with pytest.raises(ValueError):
            engine.load_model(
                str(cli),
                str(model),
                str(tok),
                str(corrupt),
                str(mref),
            )
        assert not engine.is_loaded
        assert engine._cli_path is None

    def test_load_model_no_clone_disables_clone(self, tmp_path: Path) -> None:
        cli, model, tok, fref, mref = _setup_qwen_files(tmp_path)
        engine = QwenEngine()
        engine.load_model(
            str(cli),
            str(model),
            str(tok),
            str(fref),
            str(mref),
        )
        assert not engine.is_clone_configured


# --- whatsapp-subtle pipeline ---


class TestWhatsappSubtlePipeline:
    @patch("cumadre.service.subprocess.run")
    def test_calls_ffmpeg_with_whatsapp_subtle_filter(
        self, mock_run: MagicMock
    ) -> None:
        mock_run.return_value = MagicMock(stdout=b"processed")
        wav = _create_wav_bytes()
        _apply_whatsapp_subtle(wav, "wav")
        assert mock_run.call_count >= 1

    @patch("cumadre.service.subprocess.run")
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

    @patch("cumadre.service.subprocess.run")
    def test_wav_format_without_noise_calls_ffmpeg_twice(
        self, mock_run: MagicMock
    ) -> None:
        mock_run.return_value = MagicMock(stdout=b"wav_data")
        wav = _create_wav_bytes()
        result = _apply_whatsapp_subtle(wav, "wav")
        assert result == b"wav_data"
        assert mock_run.call_count == 2

    @patch("cumadre.service.subprocess.run")
    def test_ogg_format_calls_ffmpeg_twice(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(stdout=b"ogg_data")
        wav = _create_wav_bytes()
        _apply_whatsapp_subtle(wav, "ogg")
        assert mock_run.call_count == 2

    @patch("cumadre.service.subprocess.run")
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
    @patch("cumadre.service.subprocess.run")
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

    @patch("cumadre.service.subprocess.run")
    def test_missing_noise_falls_back_gracefully(
        self, mock_run: MagicMock, tmp_path: Path
    ) -> None:
        mock_run.return_value = MagicMock(stdout=b"clean")
        result = _apply_whatsapp_subtle(_create_wav_bytes(), "ogg", noise_dir=tmp_path)
        assert result == b"clean"


# --- Noise volume refactoring backward compat ---


class TestNoiseVolumeRefactoring:
    @patch("cumadre.service.subprocess.run")
    def test_vibrato_warm_still_uses_kokoro_volumes(
        self, mock_run: MagicMock, tmp_path: Path
    ) -> None:
        """Regression: vibrato_warm must still pass 0.45/0.24 after refactoring."""
        mock_run.return_value = MagicMock(stdout=b"mixed")
        (tmp_path / "room.wav").write_bytes(_create_wav_bytes())
        (tmp_path / "hiss.wav").write_bytes(_create_wav_bytes())

        _apply_vibrato_warm(_create_wav_bytes(), "ogg", noise_dir=tmp_path)
        stage2_call = mock_run.call_args_list[1]
        cmd_args = stage2_call[0][0]
        fc_idx = cmd_args.index("-filter_complex")
        fc = cmd_args[fc_idx + 1]
        assert "volume=0.45" in fc  # Kokoro room volume unchanged
        assert "volume=0.24" in fc  # Kokoro hiss volume unchanged

    @patch("cumadre.service.subprocess.run")
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
