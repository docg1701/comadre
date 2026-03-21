"""Tests for the voice discovery and validation module."""

import logging
import wave
from pathlib import Path

import pytest

from cumadre.voices import (
    MAX_VOICE_DURATION,
    MIN_VOICE_DURATION,
    VoiceInfo,
    _validate_wav,
    discover_voices,
    list_voice_names,
)


def _create_wav(path: Path, duration_seconds: float, framerate: int = 24000) -> None:
    """Write a minimal mono 16-bit WAV file with the given duration."""
    n_frames = int(framerate * duration_seconds)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(framerate)
        wf.writeframes(b"\x00\x00" * n_frames)


@pytest.fixture()
def voice_logger(caplog: pytest.LogCaptureFixture) -> pytest.LogCaptureFixture:
    """Enable log capture for the voice logger (propagate=False by default)."""
    voice_log = logging.getLogger("voice")
    voice_log.propagate = True
    yield caplog
    voice_log.propagate = False


# --- Task 2.3: Valid WAV files in range (3-10s) ---


class TestDiscoverValidVoices:
    def test_valid_wav_discovered(
        self, tmp_path: Path, voice_logger: pytest.LogCaptureFixture
    ) -> None:
        _create_wav(tmp_path / "carlos.wav", 5.2)
        _create_wav(tmp_path / "maria.wav", 7.0)

        with voice_logger.at_level(logging.DEBUG, logger="voice"):
            voices = discover_voices(tmp_path)

        assert len(voices) == 2
        names = [v.name for v in voices]
        assert "carlos" in names
        assert "maria" in names
        assert any("Voice 'carlos' loaded" in r.message for r in voice_logger.records)

    def test_boundary_min_duration(self, tmp_path: Path) -> None:
        _create_wav(tmp_path / "exact_min.wav", MIN_VOICE_DURATION)
        voices = discover_voices(tmp_path)
        assert len(voices) == 1
        assert voices[0].name == "exact_min"

    def test_boundary_max_duration(self, tmp_path: Path) -> None:
        _create_wav(tmp_path / "exact_max.wav", MAX_VOICE_DURATION)
        voices = discover_voices(tmp_path)
        assert len(voices) == 1
        assert voices[0].name == "exact_max"

    def test_voice_info_fields(self, tmp_path: Path) -> None:
        wav_path = tmp_path / "test.wav"
        _create_wav(wav_path, 5.0)
        voices = discover_voices(tmp_path)
        assert len(voices) == 1
        v = voices[0]
        assert v.name == "test"
        assert v.path == wav_path
        assert abs(v.duration_seconds - 5.0) < 0.1


# --- Task 2.4: Non-WAV files skipped ---


class TestCaseInsensitiveWav:
    def test_uppercase_wav_discovered(self, tmp_path: Path) -> None:
        _create_wav(tmp_path / "voice.WAV", 5.0)
        voices = discover_voices(tmp_path)
        assert len(voices) == 1
        assert voices[0].name == "voice"

    def test_mixed_case_wav_discovered(self, tmp_path: Path) -> None:
        _create_wav(tmp_path / "voice.Wav", 5.0)
        voices = discover_voices(tmp_path)
        assert len(voices) == 1
        assert voices[0].name == "voice"


class TestSkipNonWav:
    def test_mp3_skipped(
        self, tmp_path: Path, voice_logger: pytest.LogCaptureFixture
    ) -> None:
        (tmp_path / "test.mp3").write_bytes(b"\x00" * 100)
        with voice_logger.at_level(logging.DEBUG, logger="voice"):
            voices = discover_voices(tmp_path)
        assert voices == []
        assert any("not a WAV file" in r.message for r in voice_logger.records)

    def test_txt_skipped(
        self, tmp_path: Path, voice_logger: pytest.LogCaptureFixture
    ) -> None:
        (tmp_path / "readme.txt").write_text("hello")
        with voice_logger.at_level(logging.DEBUG, logger="voice"):
            voices = discover_voices(tmp_path)
        assert voices == []
        assert any("not a WAV file" in r.message for r in voice_logger.records)


# --- Task 2.5: WAV > 10s skipped ---


class TestSkipTooLong:
    def test_long_wav_skipped(
        self, tmp_path: Path, voice_logger: pytest.LogCaptureFixture
    ) -> None:
        _create_wav(tmp_path / "long.wav", 45.0)
        with voice_logger.at_level(logging.DEBUG, logger="voice"):
            voices = discover_voices(tmp_path)
        assert voices == []
        assert any(
            "exceeds" in r.message and "45.0s" in r.message
            for r in voice_logger.records
        )


# --- Task 2.6: WAV < 3s skipped ---


class TestSkipTooShort:
    def test_short_wav_skipped(
        self, tmp_path: Path, voice_logger: pytest.LogCaptureFixture
    ) -> None:
        _create_wav(tmp_path / "short.wav", 1.5)
        with voice_logger.at_level(logging.DEBUG, logger="voice"):
            voices = discover_voices(tmp_path)
        assert voices == []
        assert any(
            "below" in r.message and "1.5s" in r.message for r in voice_logger.records
        )


# --- Task 2.7: Empty directory ---


class TestEmptyDirectory:
    def test_empty_dir_returns_empty(
        self, tmp_path: Path, voice_logger: pytest.LogCaptureFixture
    ) -> None:
        with voice_logger.at_level(logging.DEBUG, logger="voice"):
            voices = discover_voices(tmp_path)
        assert voices == []
        assert any("No voice files found" in r.message for r in voice_logger.records)

    def test_only_invalid_files_warns_no_valid(
        self, tmp_path: Path, voice_logger: pytest.LogCaptureFixture
    ) -> None:
        (tmp_path / "track.mp3").write_bytes(b"\x00" * 100)
        _create_wav(tmp_path / "short.wav", 1.0)
        with voice_logger.at_level(logging.DEBUG, logger="voice"):
            voices = discover_voices(tmp_path)
        assert voices == []
        assert any(
            "No valid voice files" in r.message and "2 files scanned" in r.message
            for r in voice_logger.records
        )


# --- Task 2.8: Nonexistent directory ---


class TestNonexistentDirectory:
    def test_missing_dir_returns_empty(
        self, tmp_path: Path, voice_logger: pytest.LogCaptureFixture
    ) -> None:
        missing = tmp_path / "nonexistent"
        with voice_logger.at_level(logging.DEBUG, logger="voice"):
            voices = discover_voices(missing)
        assert voices == []
        assert any(
            "Voices directory not found" in r.message for r in voice_logger.records
        )

    def test_path_is_file_returns_empty(
        self, tmp_path: Path, voice_logger: pytest.LogCaptureFixture
    ) -> None:
        file_path = tmp_path / "not_a_dir"
        file_path.write_text("I am a file")
        with voice_logger.at_level(logging.DEBUG, logger="voice"):
            voices = discover_voices(file_path)
        assert voices == []
        assert any(
            "Voices directory not found" in r.message for r in voice_logger.records
        )


# --- Task 2.9: Corrupted WAV files ---


class TestCorruptedWav:
    def test_corrupted_wav_skipped(
        self, tmp_path: Path, voice_logger: pytest.LogCaptureFixture
    ) -> None:
        (tmp_path / "bad.wav").write_bytes(b"RIFF\x00\x00\x00\x00WAVE_JUNK")
        with voice_logger.at_level(logging.DEBUG, logger="voice"):
            voices = discover_voices(tmp_path)
        assert voices == []
        assert any(
            "corrupted or invalid WAV" in r.message for r in voice_logger.records
        )

    def test_unreadable_wav_skipped(
        self, tmp_path: Path, voice_logger: pytest.LogCaptureFixture
    ) -> None:
        unreadable = tmp_path / "noperm.wav"
        _create_wav(unreadable, 5.0)
        unreadable.chmod(0o000)
        with voice_logger.at_level(logging.DEBUG, logger="voice"):
            voices = discover_voices(tmp_path)
        assert voices == []
        assert any(
            "corrupted or invalid WAV" in r.message for r in voice_logger.records
        )
        unreadable.chmod(0o644)


# --- Task 2.10: Voice names are filename stems ---


class TestVoiceNameStems:
    def test_name_is_stem(self, tmp_path: Path) -> None:
        _create_wav(tmp_path / "my_voice.wav", 5.0)
        voices = discover_voices(tmp_path)
        assert voices[0].name == "my_voice"
        assert ".wav" not in voices[0].name


# --- Task 2.11: list_voice_names returns sorted names ---


class TestListVoiceNames:
    def test_sorted_names(self) -> None:
        voices = [
            VoiceInfo(name="zara", path=Path("/v/zara.wav"), duration_seconds=5.0),
            VoiceInfo(name="anna", path=Path("/v/anna.wav"), duration_seconds=4.0),
            VoiceInfo(name="maria", path=Path("/v/maria.wav"), duration_seconds=6.0),
        ]
        assert list_voice_names(voices) == ["anna", "maria", "zara"]

    def test_empty_list(self) -> None:
        assert list_voice_names([]) == []


# --- _validate_wav direct tests ---


class TestValidateWav:
    def test_valid_file(self, tmp_path: Path) -> None:
        wav_path = tmp_path / "ok.wav"
        _create_wav(wav_path, 5.0)
        result = _validate_wav(wav_path)
        assert result is not None
        assert result.name == "ok"

    def test_invalid_file(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.wav"
        bad.write_bytes(b"not a wav file at all")
        result = _validate_wav(bad)
        assert result is None
