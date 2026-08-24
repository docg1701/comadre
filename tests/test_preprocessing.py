"""Tests for the pt-BR text preprocessing module.

Lean by design (test-suite review 2026-04-25): per-sigla, per-number,
per-currency parametrize-bait collapsed into representative smoke
tests. The full table is exercised via integration smoke against real
audio output (scripts/spike_pocket_tts.py).
"""

from __future__ import annotations

from comadre.preprocessing import (
    normalize_currency,
    normalize_numbers,
    normalize_text,
)


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


def test_normalize_text_pipeline_applies_currency_and_numbers() -> None:
    """End-to-end smoke for the normalization pipeline."""
    out = normalize_text("Pague R$ 100,00 até o 1º dia de janeiro.")
    assert "100,00" not in out  # currency expanded
    assert "1º" not in out  # ordinal expanded


def test_normalize_numbers_expands_decimal_comma() -> None:
    """Regression: '10,50' used to become glued 'dez,cinquenta' — the comma
    must be consumed and the decimal read as one number (2026-08-23)."""
    out = normalize_numbers("Pese 10,50 gramas")
    assert "," not in out
    assert "dez" in out.lower()
    assert "cinquenta" in out.lower()


def test_normalize_numbers_expands_thousands_dot_groups() -> None:
    """Regression: '1.234' used to become glued 'um.duzentos...' (2026-08-23)."""
    out = normalize_numbers("Vendemos 1.234 unidades")
    assert "." not in out
    assert "mil" in out.lower()


def test_normalize_times_handles_h_suffix() -> None:
    """'9h30' -> 'nove e trinta'; bare '9h' -> 'nove horas'."""
    assert "nove e trinta" in normalize_text("Reunião às 9h30")
    assert "nove horas" in normalize_text("Reunião às 9h")


def test_normalize_percent_expands() -> None:
    out = normalize_text("Desconto de 50% no total")
    assert "%" not in out
    assert "cinquenta por cento" in out


def test_normalize_round_the_clock_idiom() -> None:
    out = normalize_text("Atendemos 24/7")
    assert "/" not in out
    assert "vinte e quatro por sete" in out


def test_normalize_short_dates() -> None:
    out = normalize_text("Promoção até 12/05")
    assert "doze de maio" in out
    # Implausible month falls through to the slash sanitizer.
    out2 = normalize_text("Placar 5/13 no jogo")
    assert "/" not in out2


def test_normalize_phones_digit_by_digit() -> None:
    out = normalize_text("Ligue (11) 99999-8888")
    assert "(" not in out and "-" not in out
    assert "um um" in out
    assert "nove nove nove nove nove." in out


def test_sanitize_strips_emoji_urls_and_slashes() -> None:
    out = normalize_text("Confira: https://x.com/a-b 😊 e/ou ok")
    assert "http" not in out and "😊" not in out and "/" not in out
    assert "e ou" in out
