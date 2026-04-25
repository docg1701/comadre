"""Tests for the TTS engine services.

Lean by design (test-suite review 2026-04-25): the FFmpeg pipeline,
post-processing, noise mixing, and chunk strategy are tested upstream
by integration smoke tests against real audio. What ONLY a unit test
can guard: char-limit + format-allowlist enforcement (400 before any
model call), and model-not-loaded guard (clear error vs cryptic None).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from comadre.exceptions import GenerationError, InvalidRequestError
from comadre.service import KokoroEngine


@pytest.fixture()
def engine() -> KokoroEngine:
    """KokoroEngine with mocked Kokoro inference."""
    svc = KokoroEngine()
    mock_kokoro = MagicMock()
    mock_kokoro.create.return_value = (np.zeros(24000, dtype=np.float32), 24000)
    mock_kokoro.get_voices.return_value = ["pm_santa", "pf_dora", "pm_alex"]
    mock_kokoro.get_voice_style.return_value = np.zeros((510, 1, 256), dtype=np.float32)
    svc._kokoro = mock_kokoro
    return svc


def test_kokoro_engine_generate_speech_smoke(engine: KokoroEngine) -> None:
    """Happy path: create() → post-process pipeline returns the bytes."""
    with patch("comadre.service._apply_radio_warm", return_value=b"processed"):
        result = engine.generate_speech("hello world", "pm_santa", "wav")
    assert result == b"processed"
    engine._kokoro.create.assert_called_once()  # type: ignore[union-attr]
    call_kwargs = engine._kokoro.create.call_args.kwargs  # type: ignore[union-attr]
    assert call_kwargs["voice"] == "pm_santa"
    assert call_kwargs["lang"] == "pt-br"


def test_kokoro_engine_rejects_oversize_empty_and_unsupported_format_with_400(
    engine: KokoroEngine,
) -> None:
    """Pre-call validation: oversize text, empty/whitespace, and
    unsupported formats all raise ``InvalidRequestError`` BEFORE create();
    the model is never asked to render input that would 4xx anyway."""
    too_long = "a" * (KokoroEngine.CHAR_LIMIT + 1)
    with pytest.raises(InvalidRequestError) as exc_info:
        engine.generate_speech(too_long, "pm_santa", "wav")
    assert str(KokoroEngine.CHAR_LIMIT) in exc_info.value.message
    assert exc_info.value.status_code == 400

    for bad in ("", "   "):
        with pytest.raises(InvalidRequestError):
            engine.generate_speech(bad, "pm_santa", "wav")

    # mp3 → 400 (only wav and ogg are supported).
    with pytest.raises(InvalidRequestError):
        engine.generate_speech("hello", "pm_santa", "mp3")

    # No model call happened across any of the rejected inputs.
    engine._kokoro.create.assert_not_called()  # type: ignore[union-attr]


def test_kokoro_engine_model_not_loaded_raises_generation_error() -> None:
    """A clean GenerationError beats an opaque AttributeError on None._kokoro."""
    svc = KokoroEngine()
    assert not svc.is_loaded
    with pytest.raises(GenerationError, match="Model not loaded"):
        svc.generate_speech("hello", "pm_santa", "wav")
