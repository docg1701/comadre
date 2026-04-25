"""Tests for ``EngineRouter`` voice routing and dispatch.

Lean by design (test-suite review 2026-04-25): per-flag forwarding mock
asserts collapsed into one full-dispatch test per engine. Path-traversal
+ unknown-engine + bad-format rejections kept (security-relevant).
"""

from __future__ import annotations

import io
import wave
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from comadre.exceptions import InvalidRequestError, VoiceNotFoundError
from comadre.service import EngineRouter, KokoroEngine, QwenEngine


def _create_ref_wav(path: Path) -> None:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(b"\x00\x00" * 16000)
    path.write_bytes(buf.getvalue())


@pytest.fixture()
def kokoro() -> KokoroEngine:
    engine = KokoroEngine()
    mock = MagicMock()
    mock.get_voices.return_value = ["pm_santa", "pf_dora"]
    mock.get_voice_style.return_value = np.zeros((510, 1, 256), dtype=np.float32)
    engine._kokoro = mock
    return engine


@pytest.fixture()
def qwen() -> QwenEngine:
    engine = QwenEngine()
    engine._loaded = True
    engine._cli_path = "/usr/local/bin/qwen3-tts-cli"
    engine._model_path = "models/qwen3-tts-0.6b-q8_0.gguf"
    return engine


@pytest.fixture()
def voices_dir(tmp_path: Path) -> Path:
    (tmp_path / "kokoro").mkdir()
    (tmp_path / "qwen").mkdir()
    np.save(
        tmp_path / "kokoro" / "custom_voice.npy",
        np.zeros((510, 1, 256), dtype=np.float32),
    )
    _create_ref_wav(tmp_path / "qwen" / "female-reference.wav")
    return tmp_path


@pytest.fixture()
def router(kokoro: KokoroEngine, qwen: QwenEngine, voices_dir: Path) -> EngineRouter:
    return EngineRouter(kokoro, qwen, voices_dir)


def test_parse_voice_rejects_path_traversal_and_special_chars(
    router: EngineRouter,
) -> None:
    """Security: voice format must NOT allow path-traversal / special chars
    that would let a request walk outside ``voices_dir``."""
    for hostile in ("kokoro/../etc/passwd", "kokoro/voice.npy", "kokoro/x/y"):
        with pytest.raises(InvalidRequestError):
            router._parse_voice(hostile)


def test_parse_voice_rejects_unknown_engine_and_bad_shape(
    router: EngineRouter,
) -> None:
    for bad in ("santa", "kokoro/", "chatterbox/voice"):
        with pytest.raises(InvalidRequestError):
            router._parse_voice(bad)


def test_parse_voice_accepts_engine_slash_name_with_hyphens_underscores(
    router: EngineRouter,
) -> None:
    engine, name = router._parse_voice("qwen/my-voice_01")
    assert engine == "qwen"
    assert name == "my-voice_01"


def test_resolve_voice_unknown_raises_voice_not_found(
    router: EngineRouter,
) -> None:
    """A 404 (NOT 500) is what reaches the user; tests at the resolution
    layer make sure resolution dispatches the right exception."""
    with pytest.raises(VoiceNotFoundError):
        router._resolve_kokoro_voice("nonexistent")
    with pytest.raises(VoiceNotFoundError):
        router._resolve_qwen_voice("nonexistent")


def test_generate_speech_dispatches_to_engine_with_correct_args(
    router: EngineRouter, kokoro: KokoroEngine, qwen: QwenEngine
) -> None:
    """Dispatch by engine prefix; per-engine call signature differs (Kokoro
    takes noise_dir + speed; Qwen takes reference path + seed)."""
    with patch.object(kokoro, "generate_speech", return_value=b"k") as mock_k:
        result = router.generate_speech(
            "ola", "kokoro/pm_santa", "ogg", noise_dir=Path("/n"), speed=1.5
        )
        assert result == b"k"
        # noise_dir + speed in positional slots.
        assert mock_k.call_args[0][3] == Path("/n")
        assert mock_k.call_args[0][4] == 1.5

    with patch.object(qwen, "generate_speech", return_value=b"q") as mock_q:
        result = router.generate_speech("ola", "qwen/female-reference", "ogg", seed=42)
        assert result == b"q"
        # reference path is positional[1]; seed at [4].
        assert isinstance(mock_q.call_args[0][1], Path)
        assert mock_q.call_args[0][4] == 42


def test_available_voices_dedupes_builtin_and_custom_npy_overlap(
    kokoro: KokoroEngine, qwen: QwenEngine, voices_dir: Path
) -> None:
    """A custom .npy with the same name as a built-in voice must not
    duplicate the entry — operator-visible bug if it did."""
    np.save(
        voices_dir / "kokoro" / "pm_santa.npy",
        np.zeros((510, 1, 256), dtype=np.float32),
    )
    router = EngineRouter(kokoro, qwen, voices_dir)
    voices = router.available_voices()
    assert voices.count("kokoro/pm_santa") == 1
    assert voices == sorted(voices)
    # Both built-in + custom .npy + .wav surface.
    assert "kokoro/custom_voice" in voices
    assert "qwen/female-reference" in voices
