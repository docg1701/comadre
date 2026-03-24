"""Kokoro TTS engine — kokoro-onnx fp32 integration."""

from __future__ import annotations

import io
import subprocess
import wave
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

from cumadre.exceptions import GenerationError, InvalidRequestError, VoiceNotFoundError
from cumadre.logging import get_logger
from cumadre.preprocessing import chunk_text, normalize_text

if TYPE_CHECKING:
    from numpy.typing import NDArray

logger = get_logger("request")
startup_logger = get_logger("startup")

KOKORO_VOICES: dict[str, str] = {
    "santa": "pm_santa",
    "dora": "pf_dora",
    "alex": "pm_alex",
}

KOKORO_CHAR_LIMIT = 500


class KokoroEngine:
    """Wraps kokoro-onnx for TTS generation with built-in voices."""

    def __init__(self) -> None:
        self._kokoro: Any = None

    @property
    def is_loaded(self) -> bool:
        """Return True if the Kokoro model is loaded."""
        return self._kokoro is not None

    def load_model(
        self,
        model_path: str,
        voices_path: str,
        espeak_data_path: str | None = None,
    ) -> None:
        """Load the Kokoro ONNX model."""
        import kokoro_onnx

        espeak_config = None
        if espeak_data_path is not None:
            espeak_config = kokoro_onnx.EspeakConfig(  # type: ignore[attr-defined]
                data_path=espeak_data_path
            )
            startup_logger.info("espeak-ng data path overridden: %s", espeak_data_path)

        startup_logger.info("Loading Kokoro model...")
        self._kokoro = kokoro_onnx.Kokoro(
            model_path=model_path,
            voices_path=voices_path,
            espeak_config=espeak_config,
        )
        startup_logger.info("Kokoro model loaded")

    def warm_up(self) -> None:
        """Run dummy inference to preload model internals."""
        if self._kokoro is None:
            msg = "Model not loaded — call load_model() first"
            raise RuntimeError(msg)
        startup_logger.info("Running warm-up inference...")
        self._kokoro.create(
            text="Teste de aquecimento.",
            voice="pm_santa",
            speed=1.0,
            lang="pt-br",
        )
        startup_logger.info("Warm-up complete")

    def generate_speech(
        self,
        text: str,
        voice_name: str,
        response_format: str,
        noise_dir: Path | None = None,
    ) -> bytes:
        """Generate speech via Kokoro fp32 engine.

        Args:
            text: Input text to synthesize.
            voice_name: User-facing voice name (santa/dora/alex).
            response_format: Output format — "wav" or "ogg".
            noise_dir: Directory containing room/hiss noise WAV files.

        Returns:
            Audio bytes in the requested format.

        Raises:
            VoiceNotFoundError: If voice_name is not a Kokoro voice.
            InvalidRequestError: If text exceeds the character limit.
            GenerationError: If TTS generation or encoding fails.
        """
        if response_format not in ("wav", "ogg"):
            raise InvalidRequestError(
                message=f"Unsupported response format: '{response_format}'",
                hint="Supported formats: 'wav', 'ogg'.",
            )

        kokoro_voice = KOKORO_VOICES.get(voice_name)
        if kokoro_voice is None:
            raise VoiceNotFoundError(
                voice=voice_name, available=list(KOKORO_VOICES.keys())
            )

        if not text.strip():
            raise InvalidRequestError(
                message="Text must not be empty",
                hint="Provide non-empty text for speech synthesis.",
            )

        if len(text) > KOKORO_CHAR_LIMIT:
            raise InvalidRequestError(
                message=(
                    f"Text exceeds {KOKORO_CHAR_LIMIT} character limit"
                    f" ({len(text)} chars)"
                ),
                hint=f"Shorten your text to {KOKORO_CHAR_LIMIT} characters or fewer.",
            )

        if self._kokoro is None:
            msg = "Model not loaded — call load_model() first"
            raise RuntimeError(msg)

        normalized = normalize_text(text)
        chunks = chunk_text(normalized)
        logger.info("Generating %d chunk(s) for %d characters", len(chunks), len(text))

        try:
            wav_parts: list[bytes] = []
            for chunk in chunks:
                samples, sample_rate = self._kokoro.create(
                    text=chunk,
                    voice=kokoro_voice,
                    speed=1.0,
                    lang="pt-br",
                )
                wav_parts.append(_samples_to_wav(samples, sample_rate))

            wav_bytes = _concatenate_wavs(wav_parts)
            return _apply_vibrato_warm(wav_bytes, response_format, noise_dir)
        except (VoiceNotFoundError, InvalidRequestError, GenerationError):
            raise
        except Exception as exc:
            logger.error("TTS generation failed: %s", exc, exc_info=True)
            raise GenerationError(f"TTS generation failed: {exc}") from exc


def _samples_to_wav(samples: NDArray[np.float32], sample_rate: int) -> bytes:
    """Convert float32 audio samples to WAV bytes."""
    int16_samples = (np.clip(samples, -1.0, 1.0) * 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(sample_rate)
        wf.writeframes(int16_samples.tobytes())
    return buf.getvalue()


def _concatenate_wavs(wav_bytes_list: list[bytes]) -> bytes:
    """Concatenate multiple WAV byte sequences into one."""
    if len(wav_bytes_list) == 1:
        return wav_bytes_list[0]

    output = io.BytesIO()
    params: wave._wave_params | None = None
    with wave.open(output, "wb") as out_wf:
        for i, wav_bytes in enumerate(wav_bytes_list):
            with wave.open(io.BytesIO(wav_bytes), "rb") as in_wf:
                if i == 0:
                    params = in_wf.getparams()
                    out_wf.setparams(params)
                else:
                    chunk_params = in_wf.getparams()
                    if chunk_params[:3] != params[:3]:  # type: ignore[index]
                        msg = (
                            f"WAV params mismatch: chunk 0={params},"
                            f" chunk {i}={chunk_params}"
                        )
                        raise GenerationError(msg)
                out_wf.writeframes(in_wf.readframes(in_wf.getnframes()))
    return output.getvalue()


def _apply_vibrato_warm(
    wav_bytes: bytes,
    response_format: str,
    noise_dir: Path | None = None,
) -> bytes:
    """Apply vibrato_warm post-processing pipeline via ffmpeg.

    Stage 1: Audio effects (vibrato, EQ, compression, echo, loudnorm)
    Stage 2: Noise mixing + final encoding (OGG Opus or WAV)
    """
    # Stage 1: Audio effects
    stage1_filter = (
        "vibrato=f=4.5:d=0.06,"
        "highpass=f=80,"
        "bass=g=3:f=200,"
        "equalizer=f=2500:width_type=o:width=1.5:g=2,"
        "aexciter=freq=4500,"
        "asoftclip=type=tanh,"
        "acompressor=ratio=4:threshold=-20dB:attack=5:release=50,"
        "lowpass=f=8000,"
        "aecho=0.8:0.8:40:0.12,"
        "loudnorm=I=-18:TP=-2:LRA=7"
    )

    stage1_cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "wav",
        "-i",
        "pipe:0",
        "-af",
        stage1_filter,
        "-ar",
        "24000",
        "-f",
        "wav",
        "pipe:1",
    ]

    try:
        stage1 = subprocess.run(
            stage1_cmd,
            input=wav_bytes,
            capture_output=True,
            check=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired as exc:
        logger.error("ffmpeg stage 1 timed out after 30s")
        raise GenerationError("Audio post-processing timed out (stage 1)") from exc
    except subprocess.CalledProcessError as exc:
        logger.error("ffmpeg stage 1 failed: %s", exc.stderr.decode(errors="replace"))
        raise GenerationError("Audio post-processing failed (stage 1)") from exc

    processed_wav = stage1.stdout

    # Stage 2: Noise mixing + final encoding
    room_noise = _find_noise_file(noise_dir, "room")
    hiss_noise = _find_noise_file(noise_dir, "hiss")

    if room_noise is not None and hiss_noise is not None:
        return _apply_noise_and_encode(
            processed_wav, room_noise, hiss_noise, response_format
        )

    if noise_dir is not None:
        missing = []
        if room_noise is None:
            missing.append("room")
        if hiss_noise is None:
            missing.append("hiss")
        logger.warning(
            "Missing noise file(s) in %s: %s — skipping noise mixing",
            noise_dir,
            missing,
        )

    # No noise mixing — just encode to final format
    return _encode_final(processed_wav, response_format)


def _find_noise_file(noise_dir: Path | None, kind: str) -> Path | None:
    """Find a noise WAV file by kind (room/hiss) in the noise directory."""
    if noise_dir is None:
        return None
    candidates = [
        noise_dir / f"{kind}.wav",
        noise_dir / f"{kind}_noise.wav",
    ]
    for path in candidates:
        if path.is_file():
            return path
    return None


def _apply_noise_and_encode(
    processed_wav: bytes,
    room_noise: Path,
    hiss_noise: Path,
    response_format: str,
) -> bytes:
    """Mix noise and encode to final format (OGG Opus or WAV)."""
    if response_format == "ogg":
        codec_args = ["-c:a", "libopus", "-b:a", "24k", "-ar", "16000", "-ac", "1"]
        fmt = "ogg"
    else:
        codec_args = ["-ar", "24000", "-ac", "1"]
        fmt = "wav"

    filter_complex = (
        "[1:a]volume=0.45[room];"
        "[2:a]volume=0.24[hiss];"
        "[0:a][room][hiss]amix=inputs=3:duration=shortest,"
        "loudnorm=I=-17:TP=-1.5:LRA=7"
    )

    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "wav",
        "-i",
        "pipe:0",
        "-i",
        str(room_noise),
        "-i",
        str(hiss_noise),
        "-filter_complex",
        filter_complex,
        *codec_args,
        "-f",
        fmt,
        "pipe:1",
    ]

    try:
        result = subprocess.run(
            cmd,
            input=processed_wav,
            capture_output=True,
            check=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired as exc:
        logger.error("ffmpeg stage 2 timed out after 30s")
        raise GenerationError("Audio post-processing timed out (stage 2)") from exc
    except subprocess.CalledProcessError as exc:
        logger.error("ffmpeg stage 2 failed: %s", exc.stderr.decode(errors="replace"))
        raise GenerationError("Audio post-processing failed (stage 2)") from exc

    return result.stdout


def _encode_final(processed_wav: bytes, response_format: str) -> bytes:
    """Encode processed WAV to final format without noise mixing.

    Applies the final loudnorm pass (-17 LUFS) that would normally come
    after noise mixing, then encodes to the requested format.
    """
    if response_format == "wav":
        codec_args = ["-ar", "24000", "-ac", "1", "-f", "wav"]
    else:
        codec_args = [
            "-c:a",
            "libopus",
            "-b:a",
            "24k",
            "-ar",
            "16000",
            "-ac",
            "1",
            "-f",
            "ogg",
        ]

    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "wav",
        "-i",
        "pipe:0",
        "-af",
        "loudnorm=I=-17:TP=-1.5:LRA=7",
        *codec_args,
        "pipe:1",
    ]

    try:
        result = subprocess.run(
            cmd,
            input=processed_wav,
            capture_output=True,
            check=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired as exc:
        logger.error("ffmpeg encoding timed out after 30s")
        raise GenerationError("Audio encoding timed out") from exc
    except subprocess.CalledProcessError as exc:
        logger.error("ffmpeg encoding failed: %s", exc.stderr.decode(errors="replace"))
        raise GenerationError("Audio encoding failed") from exc

    return result.stdout
