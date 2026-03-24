"""Integration tests for real TTS generation (requires model files).

Run with: uv run pytest -m slow
Skip with: uv run pytest -m "not slow"
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

# Resource limits before any model import
os.environ.setdefault("OMP_NUM_THREADS", "4")
os.environ.setdefault("MKL_NUM_THREADS", "4")

MODEL_PATH = Path("models/kokoro-v1.0.onnx")
VOICES_PATH = Path("models/voices-v1.0.bin")
RTF_THRESHOLD = 10.0  # generous — just catching catastrophic failures

VOICE = "pm_santa"
LANG = "pt-br"


@pytest.fixture(scope="module")
def kokoro():  # type: ignore[no-untyped-def]
    """Load kokoro-onnx once for the entire test module."""
    if not MODEL_PATH.exists() or not VOICES_PATH.exists():
        pytest.skip(
            "Model files not found — download kokoro-v1.0.onnx and voices-v1.0.bin"
        )
    from kokoro_onnx import Kokoro

    k = Kokoro(
        model_path=str(MODEL_PATH),
        voices_path=str(VOICES_PATH),
    )
    # Warm up
    k.create(text="Teste.", voice=VOICE, speed=1.0, lang=LANG)
    return k


def _create(kokoro: object, text: str) -> tuple[object, int]:
    """Call kokoro.create with default voice/lang."""
    return kokoro.create(  # type: ignore[union-attr]
        text=text, voice=VOICE, speed=1.0, lang=LANG
    )


BASIC_PHRASES = [
    ("Ola, tudo bem?", "greeting"),
    (
        "O pedido custa mil e quinhentos reais.",
        "currency-preprocessed",
    ),
    (
        "Entrega em vinte e um de marco de dois mil e vinte e seis.",
        "date-preprocessed",
    ),
    ("Reuniao as catorze e trinta.", "time-preprocessed"),
]


@pytest.mark.slow
class TestBasicGeneration:
    """Verify TTS generates valid audio for basic pt-BR phrases."""

    @pytest.mark.parametrize("text,desc", BASIC_PHRASES)
    def test_generates_valid_wav(
        self,
        kokoro: object,
        text: str,
        desc: str,
    ) -> None:
        samples, sr = _create(kokoro, text)
        assert len(samples) > 0  # type: ignore[arg-type]
        assert sr == 24000

    @pytest.mark.parametrize("text,desc", BASIC_PHRASES)
    def test_rtf_below_threshold(
        self,
        kokoro: object,
        text: str,
        desc: str,
    ) -> None:
        t0 = time.perf_counter()
        samples, sr = _create(kokoro, text)
        gen_time = time.perf_counter() - t0
        duration = len(samples) / sr  # type: ignore[arg-type]
        rtf = gen_time / duration if duration > 0 else float("inf")
        assert rtf < RTF_THRESHOLD, f"RTF {rtf:.2f} exceeds threshold {RTF_THRESHOLD}"


@pytest.mark.slow
class TestPreprocessingIntegration:
    """Verify preprocessing + TTS works end to end."""

    def test_currency_normalized(self, kokoro: object) -> None:
        from cumadre.preprocessing import normalize_text

        text = normalize_text("O valor e R$ 1.500,00")
        assert "mil e quinhentos reais" in text
        samples, sr = _create(kokoro, text)
        assert len(samples) / sr > 0  # type: ignore[arg-type]

    def test_mixed_content(self, kokoro: object) -> None:
        from cumadre.preprocessing import normalize_text

        text = normalize_text("Pedido R$ 247,90 em 21/03/2026 as 14:30 com 3 itens")
        samples, sr = _create(kokoro, text)
        assert len(samples) / sr > 0  # type: ignore[arg-type]


@pytest.mark.slow
class TestChunking:
    """Verify long text chunking produces valid concatenated audio."""

    def test_long_text_generates(self, kokoro: object) -> None:
        from cumadre.preprocessing import chunk_text, normalize_text

        text = (
            "O Brasil e o maior pais da America do Sul. "
            "Sua capital e Brasilia, fundada em 21/04/1960. "
            "O pais tem 26 estados e um Distrito Federal. "
            "As principais cidades incluem Sao Paulo e Rio. "
            "A lingua oficial e o portugues."
        )
        normalized = normalize_text(text)
        chunks = chunk_text(normalized)
        assert len(chunks) >= 1

        for chunk in chunks:
            samples, sr = _create(kokoro, chunk)
            assert len(samples) / sr > 0  # type: ignore[arg-type]
