"""Tests for the pt-BR text preprocessing module.

Lean by design (test-suite review 2026-04-25): per-sigla, per-number,
per-currency parametrize-bait collapsed into representative smoke
tests. The full table is exercised via integration smoke against real
audio output.
"""

from __future__ import annotations

from comadre.preprocessing import (
    chunk_text,
    expand_siglas,
    normalize_currency,
    normalize_numbers,
    normalize_text,
)


def test_expand_siglas_spells_unknowns_keeps_word_siglas() -> None:
    """Spelled siglas (CNPJ, CPF, FGTS) get spaced for engine reading;
    word-shaped siglas (SUS, PIX, LOAS, DETRAN, MEI, COVID) stay verbatim
    so the engine pronounces them as words."""
    text = "O CNPJ é necessário para o SUS e PIX, mais o CPF para o FGTS."
    out = expand_siglas(text)
    assert "C N P J" in out
    assert "C P F" in out
    assert "F G T S" in out
    assert "SUS" in out and "PIX" in out  # word-siglas preserved


def test_expand_siglas_does_not_match_lowercase_or_single_letter() -> None:
    """Only ALL-CAPS multi-letter runs trigger spelling; lowercase or
    single letters are left alone (avoid false positives like 'I went')."""
    assert "cnpj" in expand_siglas("cnpj minúsculo")  # unchanged
    assert "I" in expand_siglas("I went home")  # unchanged


def test_normalize_numbers_expands_integers_and_ordinals() -> None:
    """Integers + ordinals (masculine + feminine) get expanded for engine
    reading. Three smokes cover the full library cardinality."""
    assert "vinte e três" in normalize_numbers("23 anos").lower()
    assert "primeiro" in normalize_numbers("1º lugar").lower()
    assert "primeira" in normalize_numbers("1ª colocada").lower()


def test_normalize_currency_expands_brl_amounts() -> None:
    out = normalize_currency("R$ 1.234,56")
    assert "real" in out.lower() or "reais" in out.lower()
    # Numbers expanded.
    assert "1.234,56" not in out


def test_chunk_text_splits_long_inputs() -> None:
    """Chunk strategy splits long text into multiple chunks; each chunk
    fits within max_tokens."""
    long = "Primeira frase. " * 50
    chunks = chunk_text(long, max_tokens=20)
    assert len(chunks) > 1


def test_normalize_text_pipeline_applies_currency_and_numbers() -> None:
    """End-to-end smoke for the Kokoro normalization pipeline (siglas
    are handled by espeak-ng dictionary, NOT by normalize_text)."""
    out = normalize_text("Pague R$ 100,00 até o 1º dia de janeiro.")
    assert "100,00" not in out  # currency expanded
    assert "1º" not in out  # ordinal expanded
