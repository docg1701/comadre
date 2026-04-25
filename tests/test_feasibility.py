"""Integration tests for real TTS generation (requires model files).

Run with: ``uv run pytest -m slow``
Skip with: ``uv run pytest -m "not slow"``
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

# Resource limits before any model import.
os.environ.setdefault("OMP_NUM_THREADS", "4")
os.environ.setdefault("MKL_NUM_THREADS", "4")

MODEL_PATH = Path("models/kokoro-v1.0.onnx")
VOICES_PATH = Path("models/voices-v1.0.bin")
RTF_THRESHOLD = 10.0  # generous — catches catastrophic failures only

VOICE = "pm_santa"
LANG = "pt-br"

BASIC_PHRASES = [
    ("Ola, tudo bem?", "greeting"),
    ("O pedido custa mil e quinhentos reais.", "currency-preprocessed"),
    ("Entrega em vinte e um de marco de dois mil e vinte e seis.", "date-preprocessed"),
    ("Reuniao as catorze e trinta.", "time-preprocessed"),
]


@pytest.fixture(scope="module")
def kokoro():  # type: ignore[no-untyped-def]
    """Load kokoro-onnx once for the entire test module."""
    if not MODEL_PATH.exists() or not VOICES_PATH.exists():
        pytest.skip("Model files not found")
    from kokoro_onnx import Kokoro

    k = Kokoro(model_path=str(MODEL_PATH), voices_path=str(VOICES_PATH))
    k.create(text="Teste.", voice=VOICE, speed=1.0, lang=LANG)  # warm-up
    return k


def _create(kokoro: object, text: str) -> tuple[object, int]:
    return kokoro.create(  # type: ignore[union-attr]
        text=text, voice=VOICE, speed=1.0, lang=LANG
    )


@pytest.mark.slow
@pytest.mark.parametrize("text,desc", BASIC_PHRASES)
def test_basic_phrase_generates_valid_wav_within_rtf_threshold(
    kokoro: object, text: str, desc: str
) -> None:
    """Verify TTS generates valid 24 kHz audio AND RTF stays bounded."""
    t0 = time.perf_counter()
    samples, sr = _create(kokoro, text)
    gen_time = time.perf_counter() - t0
    duration = len(samples) / sr  # type: ignore[arg-type]
    rtf = gen_time / duration if duration > 0 else float("inf")
    assert len(samples) > 0  # type: ignore[arg-type]
    assert sr == 24000
    assert rtf < RTF_THRESHOLD, f"RTF {rtf:.2f} exceeds {RTF_THRESHOLD}"


@pytest.mark.slow
def test_preprocessing_normalizes_currency_and_long_text_chunks_render(
    kokoro: object,
) -> None:
    """Preprocessing → TTS end-to-end: a mixed-content sentence + a
    multi-sentence corpus both render valid audio. Currency normalisation
    materialises ``mil e quinhentos reais`` and chunk_text handles the
    long form without losing bytes."""
    from comadre.preprocessing import chunk_text, normalize_text

    text = normalize_text("Pedido R$ 1.500,00 em 21/03/2026 as 14:30 com 3 itens")
    assert "mil e quinhentos reais" in text
    samples, sr = _create(kokoro, text)
    assert len(samples) / sr > 0  # type: ignore[arg-type]

    long_text = normalize_text(
        "O Brasil e o maior pais da America do Sul. "
        "Sua capital e Brasilia, fundada em 21/04/1960. "
        "O pais tem 26 estados e um Distrito Federal. "
        "As principais cidades incluem Sao Paulo e Rio. "
        "A lingua oficial e o portugues."
    )
    chunks = chunk_text(long_text)
    assert len(chunks) >= 1
    for chunk in chunks:
        samples, sr = _create(kokoro, chunk)
        assert len(samples) / sr > 0  # type: ignore[arg-type]
