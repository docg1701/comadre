"""TTS engine service — Kokoro fp32 + Qwen3 C++ Q8_0 integration."""

from __future__ import annotations

import io
import os
import re
import subprocess
import tempfile
import wave
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

from comadre.exceptions import GenerationError, InvalidRequestError, VoiceNotFoundError
from comadre.logging import get_logger
from comadre.preprocessing import chunk_text, expand_siglas, normalize_text

if TYPE_CHECKING:
    from numpy.typing import NDArray

logger = get_logger("request")
startup_logger = get_logger("startup")

# Voice name must be safe for filesystem paths: alphanumeric, hyphens, underscores.
_VOICE_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


class KokoroEngine:
    """Wraps kokoro-onnx for TTS generation with built-in voices."""

    CHAR_LIMIT = 500

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
            raise GenerationError("Model not loaded — call load_model() first")
        startup_logger.info("Running warm-up inference...")
        self._kokoro.create(
            text="Teste de aquecimento.",
            voice="pm_santa",
            speed=1.0,
            lang="pt-br",
        )
        startup_logger.info("Warm-up complete")

    def get_builtin_voices(self) -> list[str]:
        """Return sorted list of built-in voice names from the .npz archive."""
        if self._kokoro is None:
            return []
        result: list[str] = self._kokoro.get_voices()
        return result

    def get_voice_style(self, name: str) -> NDArray[np.float32]:
        """Return the voice style vector for a built-in voice name."""
        style: NDArray[np.float32] = self._kokoro.get_voice_style(name)
        return style

    def generate_speech(
        self,
        text: str,
        voice: str | NDArray[np.float32],
        response_format: str,
        noise_dir: Path | None = None,
    ) -> bytes:
        """Generate speech via Kokoro fp32 engine.

        Args:
            text: Input text to synthesize.
            voice: Built-in voice name (str) or custom voice style vector (NDArray).
            response_format: Output format — "wav" or "ogg".
            noise_dir: Directory containing room/hiss noise WAV files.

        Returns:
            Audio bytes in the requested format.

        Raises:
            InvalidRequestError: If text exceeds the character limit.
            GenerationError: If TTS generation or encoding fails.
        """
        if response_format not in ("wav", "ogg"):
            raise InvalidRequestError(
                message=f"Unsupported response format: '{response_format}'",
                hint="Supported formats: 'wav', 'ogg'.",
            )

        if not text.strip():
            raise InvalidRequestError(
                message="Text must not be empty",
                hint="Provide non-empty text for speech synthesis.",
            )

        if len(text) > self.CHAR_LIMIT:
            raise InvalidRequestError(
                message=(
                    f"Text exceeds {self.CHAR_LIMIT} character limit"
                    f" ({len(text)} chars)"
                ),
                hint=f"Shorten your text to {self.CHAR_LIMIT} characters or fewer.",
            )

        if self._kokoro is None:
            raise GenerationError("Model not loaded — call load_model() first")

        normalized = normalize_text(text)
        chunks = chunk_text(normalized)
        logger.info("Generating %d chunk(s) for %d characters", len(chunks), len(text))

        try:
            wav_parts: list[bytes] = []
            for chunk in chunks:
                samples, sample_rate = self._kokoro.create(
                    text=chunk,
                    voice=voice,
                    speed=1.0,
                    lang="pt-br",
                )
                wav_parts.append(_samples_to_wav(samples, sample_rate))

            wav_bytes = _concatenate_wavs(wav_parts)
            return _apply_vibrato_warm(wav_bytes, response_format, noise_dir)
        except (InvalidRequestError, GenerationError):
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


class QwenEngine:
    """Wraps qwen3-tts-cli C++ binary for TTS generation with voice cloning."""

    CHAR_LIMIT = 300

    def __init__(self) -> None:
        self._cli_path: str | None = None
        self._model_path: str | None = None
        self._tokenizer_path: str | None = None
        self._threads: int = 4
        self._loaded: bool = False

    @property
    def is_loaded(self) -> bool:
        """Return True if the Qwen3 engine is loaded."""
        return self._loaded

    def load_model(
        self,
        cli_path: str,
        model_path: str,
        tokenizer_path: str,
        threads: int = 4,
    ) -> None:
        """Verify Qwen3 binary, model files exist."""
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

        self._cli_path = cli_path
        self._model_path = model_path
        self._tokenizer_path = tokenizer_path
        self._threads = threads
        self._loaded = True
        startup_logger.info("Qwen3 engine loaded (threads=%d)", threads)

    def warm_up(self, reference_path: Path | None = None) -> None:
        """Run a dummy subprocess invocation to verify binary works."""
        if not self._loaded:
            raise GenerationError("Engine not loaded — call load_model() first")
        if reference_path is None:
            startup_logger.info("No Qwen3 reference WAV available, skipping warm-up")
            return
        startup_logger.info("Running Qwen3 warm-up...")
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            cmd = self._build_command("Teste.", reference_path, tmp_path, seed=42)
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
        reference_path: Path,
        response_format: str,
        noise_dir: Path | None = None,
        seed: int = -1,
    ) -> bytes:
        """Generate speech via Qwen3 C++ engine.

        Args:
            text: Input text to synthesize.
            reference_path: Path to the reference WAV file for voice cloning.
            response_format: Output format — "wav" or "ogg".
            noise_dir: Directory containing room/hiss noise WAV files.
            seed: Random seed (-1 = random, N = deterministic).

        Returns:
            Audio bytes in the requested format.

        Raises:
            InvalidRequestError: If text exceeds the character limit.
            GenerationError: If TTS generation fails.
        """
        if response_format not in ("wav", "ogg"):
            raise InvalidRequestError(
                message=f"Unsupported response format: '{response_format}'",
                hint="Supported formats: 'wav', 'ogg'.",
            )

        if not text.strip():
            raise InvalidRequestError(
                message="Text must not be empty",
                hint="Provide non-empty text for speech synthesis.",
            )

        if len(text) > self.CHAR_LIMIT:
            raise InvalidRequestError(
                message=(
                    f"Text exceeds {self.CHAR_LIMIT} character limit"
                    f" ({len(text)} chars)"
                ),
                hint=f"Shorten your text to {self.CHAR_LIMIT} characters or fewer.",
            )

        if not self._loaded:
            raise GenerationError("Engine not loaded — call load_model() first")

        preprocessed = expand_siglas(text)
        max_tokens = min(4096, max(100, len(text) * 8))
        logger.info("Generating Qwen3 speech for %d characters", len(text))

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            cmd = self._build_command(
                preprocessed, reference_path, tmp_path, seed, max_tokens
            )
            subprocess.run(
                cmd,
                capture_output=True,
                check=True,
                timeout=60,
            )
            wav_bytes = Path(tmp_path).read_bytes()
            return _apply_whatsapp_subtle(wav_bytes, response_format, noise_dir)
        except (InvalidRequestError, GenerationError):
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
        reference_path: Path,
        output_path: str,
        seed: int,
        max_tokens: int = 100,
    ) -> list[str]:
        """Build the qwen3-tts-cli command arguments."""
        if self._model_path is None:
            raise GenerationError("Model path not set — call load_model() first")
        model_dir = str(Path(self._model_path).parent)
        cmd = [
            str(self._cli_path),
            "-m",
            model_dir,
            "-t",
            text,
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
            "-r",
            str(reference_path),
            "-o",
            output_path,
        ]
        return cmd


class EngineRouter:
    """Routes voice requests to the correct TTS engine via filesystem discovery."""

    def __init__(
        self, kokoro: KokoroEngine, qwen: QwenEngine, voices_dir: Path
    ) -> None:
        self._kokoro = kokoro
        self._qwen = qwen
        self._voices_dir = voices_dir

    def _parse_voice(self, voice_name: str) -> tuple[str, str]:
        """Parse 'engine/name' voice string into (engine_prefix, voice_name).

        Raises InvalidRequestError for malformed voice strings or path traversal.
        """
        parts = voice_name.split("/", 1)
        if len(parts) != 2 or not parts[1]:
            raise InvalidRequestError(
                message=f"Invalid voice format: '{voice_name}'",
                hint=(
                    "Voice must be 'kokoro/<name>' or 'qwen/<name>'."
                    " Example: 'kokoro/pm_santa', 'qwen/galvani'."
                ),
            )
        engine, name = parts
        if engine not in ("kokoro", "qwen"):
            raise InvalidRequestError(
                message=f"Unknown engine prefix: '{engine}'",
                hint="Voice must start with 'kokoro/' or 'qwen/'.",
            )
        if not _VOICE_NAME_RE.match(name):
            raise InvalidRequestError(
                message=f"Invalid voice name: '{name}'",
                hint=(
                    "Voice name may only contain letters, digits,"
                    " hyphens, and underscores."
                ),
            )
        return engine, name

    def _resolve_kokoro_voice(self, name: str) -> str | NDArray[np.float32]:
        """Resolve a Kokoro voice by name.

        Checks for a custom .npy file first, then falls back to built-in voices.
        """
        npy_path = self._voices_dir / "kokoro" / f"{name}.npy"
        if npy_path.is_file():
            voice_data: NDArray[np.float32] = np.load(npy_path, allow_pickle=False)
            return voice_data
        # Fall back to built-in voice from .npz archive
        if self._kokoro.is_loaded and name in self._kokoro.get_builtin_voices():
            return self._kokoro.get_voice_style(name)
        raise VoiceNotFoundError(
            voice=f"kokoro/{name}", available=self.available_voices()
        )

    def _resolve_qwen_voice(self, name: str) -> Path:
        """Resolve a Qwen3 voice by name. The .wav file must exist."""
        wav_path = self._voices_dir / "qwen" / f"{name}.wav"
        if wav_path.is_file():
            return wav_path
        raise VoiceNotFoundError(
            voice=f"qwen/{name}", available=self.available_voices()
        )

    def generate_speech(
        self,
        text: str,
        voice_name: str,
        response_format: str = "ogg",
        noise_dir: Path | None = None,
        seed: int = -1,
    ) -> bytes:
        """Generate speech by dispatching to the correct engine.

        Args:
            text: Input text to synthesize.
            voice_name: Voice identifier as 'engine/name' (e.g. 'kokoro/pm_santa').
            response_format: Output format — "wav" or "ogg".
            noise_dir: Directory containing room/hiss noise WAV files.
            seed: Random seed (forwarded to Qwen3 only).

        Returns:
            Audio bytes in the requested format.
        """
        engine, name = self._parse_voice(voice_name)

        if engine == "kokoro":
            voice = self._resolve_kokoro_voice(name)
            return self._kokoro.generate_speech(text, voice, response_format, noise_dir)
        # engine == "qwen"
        ref_path = self._resolve_qwen_voice(name)
        return self._qwen.generate_speech(
            text, ref_path, response_format, noise_dir, seed
        )

    def available_voices(self) -> list[str]:
        """Return sorted list of all available voices from filesystem + builtins."""
        voices: set[str] = set()

        # Kokoro built-in voices from .npz archive
        if self._kokoro.is_loaded:
            for name in self._kokoro.get_builtin_voices():
                voices.add(f"kokoro/{name}")

        # Kokoro custom voices from .npy files
        kokoro_dir = self._voices_dir / "kokoro"
        if kokoro_dir.is_dir():
            for f in kokoro_dir.iterdir():
                if f.suffix == ".npy" and f.is_file():
                    voices.add(f"kokoro/{f.stem}")

        # Qwen3 voices from .wav files
        qwen_dir = self._voices_dir / "qwen"
        if qwen_dir.is_dir():
            for f in qwen_dir.iterdir():
                if f.suffix == ".wav" and f.is_file():
                    voices.add(f"qwen/{f.stem}")

        return sorted(voices)

    def engine_status(self) -> dict[str, dict[str, object]]:
        """Return per-engine status for health endpoint."""
        all_voices = self.available_voices()
        return {
            "kokoro": {
                "loaded": self._kokoro.is_loaded,
                "voices": [v for v in all_voices if v.startswith("kokoro/")],
            },
            "qwen3": {
                "loaded": self._qwen.is_loaded,
                "voices": [v for v in all_voices if v.startswith("qwen/")],
            },
        }


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
