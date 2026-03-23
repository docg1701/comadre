"""Integration tests for real TTS generation (requires model files).

Run with: uv run pytest -m slow
Skip with: uv run pytest -m "not slow"
"""

from __future__ import annotations

import os
import time
import wave
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from core.cloner import KokoClone

# Resource limits before any model import
os.environ.setdefault("OMP_NUM_THREADS", "4")
os.environ.setdefault("MKL_NUM_THREADS", "4")

REF_AUDIO = Path("tmp/audio-referencia-01.wav")
RTF_THRESHOLD = 10.0  # generous — just catching catastrophic failures


def _get_wav_duration(path: str) -> float:
    with wave.open(path, "rb") as wf:
        return wf.getnframes() / wf.getframerate()


@pytest.fixture(scope="module")
def cloner() -> KokoClone:
    """Load KokoClone once for the entire test module."""
    if not REF_AUDIO.exists():
        pytest.skip("Reference audio not found — run from project root")
    import torch

    torch.set_num_threads(4)
    from core.cloner import KokoClone

    c = KokoClone()
    # Warm up
    c.generate("Teste.", "pt", str(REF_AUDIO), "/tmp/cumadre_warmup.wav")
    Path("/tmp/cumadre_warmup.wav").unlink(missing_ok=True)
    return c


BASIC_PHRASES = [
    ("Ola, tudo bem?", "greeting"),
    ("O pedido custa mil e quinhentos reais.", "currency-preprocessed"),
    ("Entrega em vinte e um de marco de dois mil e vinte e seis.", "date-preprocessed"),
    ("Reuniao as catorze e trinta.", "time-preprocessed"),
]


@pytest.mark.slow
class TestBasicGeneration:
    """Verify TTS generates valid audio for basic pt-BR phrases."""

    @pytest.mark.parametrize("text,desc", BASIC_PHRASES)
    def test_generates_valid_wav(
        self,
        cloner: KokoClone,
        tmp_path: Path,
        text: str,
        desc: str,
    ) -> None:
        output = tmp_path / f"{desc}.wav"
        cloner.generate(text, "pt", str(REF_AUDIO), str(output))
        assert output.exists()
        assert output.stat().st_size > 0
        duration = _get_wav_duration(str(output))
        assert duration > 0

    @pytest.mark.parametrize("text,desc", BASIC_PHRASES)
    def test_rtf_below_threshold(
        self,
        cloner: KokoClone,
        tmp_path: Path,
        text: str,
        desc: str,
    ) -> None:
        output = tmp_path / f"{desc}.wav"
        t0 = time.perf_counter()
        cloner.generate(text, "pt", str(REF_AUDIO), str(output))
        gen_time = time.perf_counter() - t0
        duration = _get_wav_duration(str(output))
        rtf = gen_time / duration if duration > 0 else float("inf")
        assert rtf < RTF_THRESHOLD, f"RTF {rtf:.2f} exceeds threshold {RTF_THRESHOLD}"


@pytest.mark.slow
class TestPreprocessingIntegration:
    """Verify preprocessing + TTS works end to end."""

    def test_currency_normalized(
        self,
        cloner: KokoClone,
        tmp_path: Path,
    ) -> None:
        from cumadre.preprocessing import normalize_text

        text = normalize_text("O valor e R$ 1.500,00")
        assert "mil e quinhentos reais" in text
        output = tmp_path / "currency.wav"
        cloner.generate(text, "pt", str(REF_AUDIO), str(output))
        assert _get_wav_duration(str(output)) > 0

    def test_mixed_content(
        self,
        cloner: KokoClone,
        tmp_path: Path,
    ) -> None:
        from cumadre.preprocessing import normalize_text

        text = normalize_text("Pedido R$ 247,90 em 21/03/2026 as 14:30 com 3 itens")
        output = tmp_path / "mixed.wav"
        cloner.generate(text, "pt", str(REF_AUDIO), str(output))
        assert _get_wav_duration(str(output)) > 0


@pytest.mark.slow
class TestChunking:
    """Verify long text chunking produces valid concatenated audio."""

    def test_long_text_generates(
        self,
        cloner: KokoClone,
        tmp_path: Path,
    ) -> None:
        from cumadre.preprocessing import chunk_text, normalize_text

        text = (
            "O Brasil e o maior pais da America do Sul. "
            "Sua capital e Brasilia, fundada em 21/04/1960. "
            "O pais tem 26 estados e um Distrito Federal. "
            "As principais cidades incluem Sao Paulo e Rio de Janeiro. "
            "A lingua oficial e o portugues."
        )
        normalized = normalize_text(text)
        chunks = chunk_text(normalized)
        assert len(chunks) >= 1

        # Generate each chunk
        for i, chunk in enumerate(chunks):
            output = tmp_path / f"chunk_{i}.wav"
            cloner.generate(chunk, "pt", str(REF_AUDIO), str(output))
            assert _get_wav_duration(str(output)) > 0
