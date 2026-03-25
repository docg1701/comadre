"""Voice file discovery and validation."""

import dataclasses
import wave
from pathlib import Path

from comadre.logging import get_logger

MIN_VOICE_DURATION = 3.0
MAX_VOICE_DURATION = 10.0

logger = get_logger("voice")


@dataclasses.dataclass(frozen=True)
class VoiceInfo:
    """Immutable descriptor for a validated voice file."""

    name: str
    path: Path
    duration_seconds: float


def _validate_wav(file_path: Path) -> VoiceInfo | None:
    """Open a WAV file and return VoiceInfo if valid, or None if invalid."""
    try:
        with wave.open(str(file_path), "rb") as wf:
            frames = wf.getnframes()
            framerate = wf.getframerate()
            if framerate <= 0:
                logger.warning("File %s skipped: corrupted or invalid WAV", file_path)
                return None
            duration = frames / framerate
    except (wave.Error, OSError):
        logger.warning("File %s skipped: corrupted or invalid WAV", file_path)
        return None

    if duration > MAX_VOICE_DURATION:
        logger.warning(
            "File %s skipped: duration %.1fs exceeds %gs limit",
            file_path,
            duration,
            MAX_VOICE_DURATION,
        )
        return None

    if duration < MIN_VOICE_DURATION:
        logger.warning(
            "File %s skipped: duration %.1fs below %gs minimum",
            file_path,
            duration,
            MIN_VOICE_DURATION,
        )
        return None

    return VoiceInfo(
        name=file_path.stem,
        path=file_path,
        duration_seconds=duration,
    )


def discover_voices(voices_dir: Path) -> list[VoiceInfo]:
    """Scan a directory for valid WAV voice files."""
    if not voices_dir.is_dir():
        logger.warning("Voices directory not found: %s", voices_dir)
        return []

    scanned = 0
    voices: list[VoiceInfo] = []
    for entry in sorted(voices_dir.iterdir()):
        if not entry.is_file():
            continue
        scanned += 1
        if entry.suffix.lower() != ".wav":
            logger.warning("File %s skipped: not a WAV file", entry)
            continue
        voice = _validate_wav(entry)
        if voice is not None:
            logger.info(
                "Voice '%s' loaded from %s (%.1fs)",
                voice.name,
                voice.path,
                voice.duration_seconds,
            )
            voices.append(voice)

    if not voices and scanned == 0:
        logger.warning("No voice files found in %s", voices_dir)
    elif not voices:
        logger.warning(
            "No valid voice files in %s (%d files scanned)",
            voices_dir,
            scanned,
        )

    return sorted(voices, key=lambda v: v.name)


def list_voice_names(voices: list[VoiceInfo]) -> list[str]:
    """Return a sorted list of voice names."""
    return sorted(v.name for v in voices)
