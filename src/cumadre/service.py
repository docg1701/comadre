"""KokoClone TTS service wrapper."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from cumadre.exceptions import GenerationError, VoiceNotFoundError
from cumadre.logging import get_logger
from cumadre.voices import VoiceInfo, list_voice_names

if TYPE_CHECKING:
    from core.cloner import KokoClone

logger = get_logger("request")
startup_logger = get_logger("startup")

LANGUAGE = "pt"  # Brazilian Portuguese — hardcoded per FR4


class TTSService:
    """Wraps KokoClone for TTS generation with voice cloning."""

    def __init__(self) -> None:
        self._cloner: KokoClone | None = None

    @property
    def is_loaded(self) -> bool:
        """Return True if the KokoClone model is loaded."""
        return self._cloner is not None

    def load_model(self) -> None:
        """Import and instantiate KokoClone (lazy import — heavy dependency)."""
        from core.cloner import KokoClone

        startup_logger.info("Loading KokoClone model...")
        self._cloner = KokoClone()
        startup_logger.info("KokoClone model loaded")

    def warm_up(self, reference_wav: Path) -> None:
        """Run dummy inference to preload model internals."""
        if self._cloner is None:
            msg = "Model not loaded — call load_model() first"
            raise RuntimeError(msg)
        startup_logger.info("Running warm-up inference...")
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as tmp:
            self._cloner.generate("test", LANGUAGE, str(reference_wav), tmp.name)
        startup_logger.info("Warm-up complete")

    def generate_speech(
        self,
        text: str,
        voice_name: str,
        response_format: str,
        voices: list[VoiceInfo],
    ) -> bytes:
        """Generate cloned-voice speech from text.

        Args:
            text: Input text to synthesize.
            voice_name: Name of the voice to use.
            response_format: Output format — "wav" or "ogg".
            voices: Available voice descriptors.

        Returns:
            Audio bytes in the requested format.

        Raises:
            VoiceNotFoundError: If voice_name is not in the voices list.
            GenerationError: If TTS generation or encoding fails.
        """
        voice = next((v for v in voices if v.name == voice_name), None)
        if voice is None:
            raise VoiceNotFoundError(
                voice=voice_name, available=list_voice_names(voices)
            )

        if self._cloner is None:
            msg = "Model not loaded — call load_model() first"
            raise RuntimeError(msg)

        tmp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp_path = Path(tmp.name)
            self._cloner.generate(text, LANGUAGE, str(voice.path), str(tmp_path))
            if response_format == "ogg":
                return _encode_ogg(tmp_path)
            return tmp_path.read_bytes()
        except (VoiceNotFoundError, GenerationError):
            raise
        except Exception as exc:
            logger.error("TTS generation failed: %s", exc, exc_info=True)
            raise GenerationError(f"TTS generation failed: {exc}") from exc
        finally:
            if tmp_path is not None:
                tmp_path.unlink(missing_ok=True)


def _encode_ogg(wav_path: Path) -> bytes:
    """Encode a WAV file to OGG Opus format using ffmpeg."""
    try:
        result = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(wav_path),
                "-c:a",
                "libopus",
                "-f",
                "ogg",
                "pipe:1",
            ],
            capture_output=True,
            check=True,
            timeout=30,
        )
    except subprocess.CalledProcessError as exc:
        logger.error("ffmpeg encoding failed: %s", exc.stderr.decode(errors="replace"))
        raise GenerationError("Audio encoding to OGG failed") from exc
    return result.stdout
