"""KokoClone TTS service wrapper."""

from __future__ import annotations

import io
import os
import subprocess
import tempfile
import wave
from pathlib import Path
from typing import TYPE_CHECKING

from cumadre.exceptions import GenerationError, VoiceNotFoundError
from cumadre.logging import get_logger
from cumadre.preprocessing import chunk_text, normalize_text
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

    def load_model(self, espeak_data_path: str | None = None) -> None:
        """Import and instantiate KokoClone (lazy import — heavy dependency)."""
        if espeak_data_path is not None:
            os.environ["ESPEAK_DATA_PATH"] = espeak_data_path
            startup_logger.info("espeak-ng data path overridden: %s", espeak_data_path)
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

        normalized = normalize_text(text)
        chunks = chunk_text(normalized)
        logger.info("Generating %d chunk(s) for %d characters", len(chunks), len(text))

        tmp_paths: list[Path] = []
        try:
            wav_parts: list[bytes] = []
            for chunk in chunks:
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                    tmp_path = Path(tmp.name)
                tmp_paths.append(tmp_path)
                self._cloner.generate(chunk, LANGUAGE, str(voice.path), str(tmp_path))
                wav_parts.append(tmp_path.read_bytes())

            wav_bytes = _concatenate_wavs(wav_parts)

            if response_format == "ogg":
                with tempfile.NamedTemporaryFile(
                    suffix=".wav", delete=False
                ) as ogg_tmp:
                    ogg_path = Path(ogg_tmp.name)
                tmp_paths.append(ogg_path)
                ogg_path.write_bytes(wav_bytes)
                return _encode_ogg(ogg_path)
            return wav_bytes
        except (VoiceNotFoundError, GenerationError):
            raise
        except Exception as exc:
            logger.error("TTS generation failed: %s", exc, exc_info=True)
            raise GenerationError(f"TTS generation failed: {exc}") from exc
        finally:
            for p in tmp_paths:
                p.unlink(missing_ok=True)


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
