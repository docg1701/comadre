"""TTS engine service — Kokoro fp32 + Qwen3 C++ Q8_0 integration."""

from __future__ import annotations

import io
import os
import subprocess
import tempfile
import wave
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

from cumadre.exceptions import GenerationError, InvalidRequestError, VoiceNotFoundError
from cumadre.logging import get_logger
from cumadre.preprocessing import chunk_text, expand_siglas, normalize_text

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
    if not processed_wav:
        raise GenerationError("ffmpeg stage 1 produced empty output")

    # Stage 2: Noise mixing + final encoding
    room_noise = _find_noise_file(noise_dir, "room")
    hiss_noise = _find_noise_file(noise_dir, "hiss")

    if room_noise is not None and hiss_noise is not None:
        return _apply_noise_and_encode(
            processed_wav,
            room_noise,
            hiss_noise,
            response_format,
            room_volume=0.45,
            hiss_volume=0.24,
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
    room_volume: float = 0.45,
    hiss_volume: float = 0.24,
) -> bytes:
    """Mix noise and encode to final format (OGG Opus or WAV)."""
    if response_format == "ogg":
        codec_args = ["-c:a", "libopus", "-b:a", "24k", "-ar", "16000", "-ac", "1"]
        fmt = "ogg"
    else:
        codec_args = ["-ar", "24000", "-ac", "1"]
        fmt = "wav"

    filter_complex = (
        f"[1:a]volume={room_volume}[room];"
        f"[2:a]volume={hiss_volume}[hiss];"
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

    if not result.stdout:
        raise GenerationError("ffmpeg stage 2 produced empty output")

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

    if not result.stdout:
        raise GenerationError("ffmpeg encoding produced empty output")

    return result.stdout


# --- Qwen3 TTS Engine ---

# All Qwen3 voices use x-vector cloning via -r flag with different reference WAVs.
# The 0.6B-Base model has no built-in voice presets.
QWEN_VOICES: dict[str, str] = {
    "clone": "clone",
    "qwen-female": "female",
    "qwen-male": "male",
}

QWEN_CHAR_LIMIT = 300


class QwenEngine:
    """Wraps qwen3-tts-cli C++ binary for TTS generation with voice cloning."""

    def __init__(self) -> None:
        self._cli_path: str | None = None
        self._model_path: str | None = None
        self._tokenizer_path: str | None = None
        self._voice_references: dict[str, str] = {}
        self._threads: int = 4
        self._loaded: bool = False

    @property
    def is_loaded(self) -> bool:
        """Return True if the Qwen3 engine is loaded."""
        return self._loaded

    @property
    def is_clone_configured(self) -> bool:
        """Return True if a clone reference WAV is configured."""
        return "clone" in self._voice_references

    def _validate_reference_wav(self, path: str, label: str) -> None:
        """Validate a reference WAV file exists and is readable."""
        if not Path(path).is_file():
            msg = f"{label} WAV not found: {path}"
            raise FileNotFoundError(msg)
        try:
            with wave.open(path, "rb") as wf:
                duration = wf.getnframes() / wf.getframerate()
                if not (3.0 <= duration <= 10.0):
                    startup_logger.warning(
                        "%s WAV duration %.1fs outside 3-10s range",
                        label,
                        duration,
                    )
        except wave.Error as exc:
            msg = f"{label} is not a valid WAV: {path}"
            raise ValueError(msg) from exc

    def load_model(
        self,
        cli_path: str,
        model_path: str,
        tokenizer_path: str,
        female_reference_path: str,
        male_reference_path: str,
        clone_reference_path: str | None = None,
        threads: int = 4,
    ) -> None:
        """Verify Qwen3 binary, model files, and reference WAVs exist."""
        if not Path(cli_path).is_file():
            msg = f"qwen3-tts-cli binary not found: {cli_path}"
            raise FileNotFoundError(msg)
        if not os.access(cli_path, os.X_OK):
            msg = f"qwen3-tts-cli binary is not executable: {cli_path}"
            raise PermissionError(msg)
        if not Path(model_path).is_file():
            msg = f"Qwen3 model file not found: {model_path}"
            raise FileNotFoundError(msg)
        if not Path(tokenizer_path).is_file():
            msg = f"Qwen3 tokenizer file not found: {tokenizer_path}"
            raise FileNotFoundError(msg)

        # Validate all reference WAVs before assigning any state
        self._validate_reference_wav(female_reference_path, "Female reference")
        self._validate_reference_wav(male_reference_path, "Male reference")

        validated_refs: dict[str, str] = {
            "qwen-female": female_reference_path,
            "qwen-male": male_reference_path,
        }

        if clone_reference_path is not None:
            self._validate_reference_wav(clone_reference_path, "Clone reference")
            validated_refs["clone"] = clone_reference_path

        # All validation passed — assign state atomically
        self._cli_path = cli_path
        self._model_path = model_path
        self._tokenizer_path = tokenizer_path
        self._threads = threads
        self._voice_references = validated_refs

        startup_logger.info(
            "Qwen3 voices configured: %s",
            list(validated_refs.keys()),
        )
        if "clone" not in validated_refs:
            startup_logger.info("No clone reference — clone voice disabled")

        self._loaded = True
        startup_logger.info("Qwen3 engine loaded (threads=%d)", threads)

    def warm_up(self) -> None:
        """Run a dummy subprocess invocation to verify binary works."""
        if not self._loaded:
            msg = "Engine not loaded — call load_model() first"
            raise RuntimeError(msg)
        startup_logger.info("Running Qwen3 warm-up...")
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            cmd = self._build_command("Teste.", "qwen-female", tmp_path, seed=42)
            subprocess.run(
                cmd,
                capture_output=True,
                check=True,
                timeout=60,
            )
            startup_logger.info("Qwen3 warm-up complete")
        except (
            subprocess.TimeoutExpired,
            subprocess.CalledProcessError,
            OSError,
        ) as exc:
            startup_logger.warning("Qwen3 warm-up failed: %s", exc)
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def generate_speech(
        self,
        text: str,
        voice_name: str,
        response_format: str,
        noise_dir: Path | None = None,
        seed: int = -1,
    ) -> bytes:
        """Generate speech via Qwen3 C++ engine.

        Args:
            text: Input text to synthesize.
            voice_name: User-facing voice name (clone/qwen-female/qwen-male).
            response_format: Output format — "wav" or "ogg".
            noise_dir: Directory containing room/hiss noise WAV files.
            seed: Random seed (-1 = random, N = deterministic).

        Returns:
            Audio bytes in the requested format.

        Raises:
            VoiceNotFoundError: If voice_name is not a Qwen3 voice.
            InvalidRequestError: If text exceeds the character limit.
            GenerationError: If TTS generation fails.
        """
        if response_format not in ("wav", "ogg"):
            raise InvalidRequestError(
                message=f"Unsupported response format: '{response_format}'",
                hint="Supported formats: 'wav', 'ogg'.",
            )

        if voice_name not in QWEN_VOICES:
            raise VoiceNotFoundError(
                voice=voice_name, available=list(QWEN_VOICES.keys())
            )

        if voice_name == "clone" and not self.is_clone_configured:
            raise VoiceNotFoundError(
                voice=voice_name,
                available=[v for v in QWEN_VOICES if v != "clone"],
            )

        if not text.strip():
            raise InvalidRequestError(
                message="Text must not be empty",
                hint="Provide non-empty text for speech synthesis.",
            )

        if len(text) > QWEN_CHAR_LIMIT:
            raise InvalidRequestError(
                message=(
                    f"Text exceeds {QWEN_CHAR_LIMIT} character limit"
                    f" ({len(text)} chars)"
                ),
                hint=f"Shorten your text to {QWEN_CHAR_LIMIT} characters or fewer.",
            )

        if not self._loaded:
            msg = "Engine not loaded — call load_model() first"
            raise RuntimeError(msg)

        preprocessed = expand_siglas(text)
        max_tokens = min(4096, max(100, len(text) * 8))
        logger.info("Generating Qwen3 speech for %d characters", len(text))

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            cmd = self._build_command(
                preprocessed, voice_name, tmp_path, seed, max_tokens
            )
            subprocess.run(
                cmd,
                capture_output=True,
                check=True,
                timeout=60,
            )
            wav_bytes = Path(tmp_path).read_bytes()
            return _apply_whatsapp_subtle(wav_bytes, response_format, noise_dir)
        except (VoiceNotFoundError, InvalidRequestError, GenerationError):
            raise
        except subprocess.TimeoutExpired as exc:
            logger.error("qwen3-tts-cli timed out after 60s")
            raise GenerationError("Qwen3 TTS generation timed out") from exc
        except subprocess.CalledProcessError as exc:
            logger.error(
                "qwen3-tts-cli failed: %s", exc.stderr.decode(errors="replace")
            )
            raise GenerationError("Qwen3 TTS generation failed") from exc
        except Exception as exc:
            logger.error("Qwen3 TTS generation failed: %s", exc, exc_info=True)
            raise GenerationError(f"Qwen3 TTS generation failed: {exc}") from exc
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def _build_command(
        self,
        text: str,
        voice_name: str,
        output_path: str,
        seed: int,
        max_tokens: int = 100,
    ) -> list[str]:
        """Build the qwen3-tts-cli command arguments."""
        cmd = [
            str(self._cli_path),
            "-m",
            str(self._model_path),
            "-t",
            str(self._tokenizer_path),
            "-l",
            "pt",
            "--temperature",
            "0.7",
            "--top-p",
            "0.95",
            "--repetition-penalty",
            "1.05",
            "--max-tokens",
            str(max_tokens),
            "--seed",
            str(seed),
            "-j",
            str(self._threads),
        ]
        ref_path = self._voice_references.get(voice_name)
        if ref_path is not None:
            cmd.extend(["-r", ref_path])
        cmd.extend(["-o", output_path, "--", text])
        return cmd


def _apply_whatsapp_subtle(
    wav_bytes: bytes,
    response_format: str,
    noise_dir: Path | None = None,
) -> bytes:
    """Apply whatsapp-subtle post-processing pipeline via ffmpeg.

    Stage 1: Audio effects (EQ, compression, echo, atempo, loudnorm)
    Stage 2: Noise mixing + final encoding (OGG Opus or WAV)
    """
    # Stage 1: Audio effects
    stage1_filter = (
        "highpass=f=100,"
        "equalizer=f=200:width_type=o:width=1.5:g=1.5,"
        "equalizer=f=700:width_type=o:width=1.5:g=-2,"
        "equalizer=f=3000:width_type=o:width=1.5:g=3,"
        "equalizer=f=7000:width_type=o:width=1.5:g=-4,"
        "acompressor=threshold=0.15:ratio=6:attack=15:release=200:makeup=5,"
        "lowpass=f=8000,"
        "aecho=0.8:0.85:40:0.12,"
        "atempo=1.15,"
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
        logger.error("ffmpeg whatsapp-subtle stage 1 timed out after 30s")
        raise GenerationError(
            "Audio post-processing timed out (whatsapp-subtle stage 1)"
        ) from exc
    except subprocess.CalledProcessError as exc:
        logger.error(
            "ffmpeg whatsapp-subtle stage 1 failed: %s",
            exc.stderr.decode(errors="replace"),
        )
        raise GenerationError(
            "Audio post-processing failed (whatsapp-subtle stage 1)"
        ) from exc

    processed_wav = stage1.stdout
    if not processed_wav:
        raise GenerationError("ffmpeg whatsapp-subtle stage 1 produced empty output")

    # Stage 2: Noise mixing + final encoding
    room_noise = _find_noise_file(noise_dir, "room")
    hiss_noise = _find_noise_file(noise_dir, "hiss")

    if room_noise is not None and hiss_noise is not None:
        return _apply_noise_and_encode(
            processed_wav,
            room_noise,
            hiss_noise,
            response_format,
            room_volume=0.15,
            hiss_volume=0.08,
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
