"""pt-BR text normalization and sentence chunking."""

from __future__ import annotations

import re

import num2words as _num2words

MONTHS_PT = [
    "janeiro",
    "fevereiro",
    "março",
    "abril",
    "maio",
    "junho",
    "julho",
    "agosto",
    "setembro",
    "outubro",
    "novembro",
    "dezembro",
]

# Currency: R$ 1.500,00 or R$ 42,50 or R$1500
_CURRENCY_RE = re.compile(r"R\$\s?(\d+(?:\.\d{3})*(?:,\d{2})?)")

# Date: dd/mm/yyyy
_DATE_RE = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})")

# Time: HH:MM (but not part of a date like dd/mm/yyyy or a larger number)
_TIME_RE = re.compile(r"(?<!/)\b(\d{1,2}):(\d{2})\b")

# Ordinals: 3º, 1ª, 10º
_ORDINAL_RE = re.compile(r"(\d+)[ºª]")

# Standalone integers (not part of dates, times, or currency already processed)
_NUMBER_RE = re.compile(r"\b(\d+)\b")


def _n2w(n: int | float, **kwargs: str) -> str:
    """Typed wrapper around num2words.num2words for pt_BR."""
    result: str = _num2words.num2words(n, lang="pt_BR", **kwargs)
    return result


def _currency_to_float(raw: str) -> float:
    """Convert Brazilian currency string to float. E.g. '1.500,50' -> 1500.50."""
    return float(raw.replace(".", "").replace(",", "."))


def normalize_currency(text: str) -> str:
    """Replace R$ currency patterns with pt-BR words."""

    def _replace(match: re.Match[str]) -> str:
        value = _currency_to_float(match.group(1))
        return _n2w(value, to="currency")

    return _CURRENCY_RE.sub(_replace, text)


def normalize_dates(text: str) -> str:
    """Replace dd/mm/yyyy date patterns with pt-BR words."""

    def _replace(match: re.Match[str]) -> str:
        day = int(match.group(1))
        month = int(match.group(2))
        year = int(match.group(3))
        if not (1 <= month <= 12) or not (1 <= day <= 31):
            return match.group(0)
        day_words = _n2w(day)
        month_name = MONTHS_PT[month - 1]
        year_words = _n2w(year)
        return f"{day_words} de {month_name} de {year_words}"

    return _DATE_RE.sub(_replace, text)


def normalize_times(text: str) -> str:
    """Replace HH:MM time patterns with pt-BR words."""

    def _replace(match: re.Match[str]) -> str:
        hour = int(match.group(1))
        minute = int(match.group(2))
        if not (0 <= hour <= 23) or not (0 <= minute <= 59):
            return match.group(0)
        hour_words = _n2w(hour)
        if minute == 0:
            return hour_words
        minute_words = _n2w(minute)
        return f"{hour_words} e {minute_words}"

    return _TIME_RE.sub(_replace, text)


def normalize_numbers(text: str) -> str:
    """Replace standalone ordinals and integers with pt-BR words."""

    def _replace_ordinal(match: re.Match[str]) -> str:
        result = _n2w(int(match.group(1)), to="ordinal")
        if match.group(0).endswith("ª") and result.endswith("o"):
            result = result[:-1] + "a"
        return result

    text = _ORDINAL_RE.sub(_replace_ordinal, text)

    def _replace_number(match: re.Match[str]) -> str:
        return _n2w(int(match.group(1)))

    return _NUMBER_RE.sub(_replace_number, text)


# Word siglas that are pronounced as words, not spelled out.
# All-caps words NOT in this set get letter-spaced (e.g., CNPJ -> "C N P J").
WORD_SIGLAS: frozenset[str] = frozenset(
    {
        # Healthcare / Social
        "SUS",
        "SAMU",
        "ANVISA",
        "CRAS",
        "LOAS",
        # Financial / Employment
        "PIX",
        "PIS",
        "PASEP",
        "MEI",
        "FIES",
        # Education
        "ENEM",
        "PROUNI",
        "PRONATEC",
        "SENAI",
        "SENAC",
        "SESI",
        "SEBRAE",
        # Government / Infrastructure
        "CEP",
        "DETRAN",
        "SINE",
        # General word-pronounced
        "TV",
        "OK",
        "COVID",
        "ONG",
        "ONU",
        "UNESCO",
        "FIFA",
    }
)

_SIGLA_RE = re.compile(r"\b([A-Z]{2,})\b")


def expand_siglas(text: str) -> str:
    """Convert spelled siglas to spaced format for Qwen3 pronunciation.

    Spelled siglas (CNPJ, CPF, FGTS) become "C N P J", "C P F", "F G T S".
    Word siglas (SUS, PIX, LOAS) are kept as-is.
    """

    def _replace(match: re.Match[str]) -> str:
        sigla = match.group(1)
        if sigla in WORD_SIGLAS:
            return sigla
        return " ".join(sigla)

    return _SIGLA_RE.sub(_replace, text)


def normalize_text(text: str) -> str:
    """Normalize pt-BR text: currency, dates, times, numbers.

    Order matters: currency first (R$ pattern before bare numbers),
    then dates and times (contain digits), then standalone numbers last.
    """
    text = normalize_currency(text)
    text = normalize_dates(text)
    text = normalize_times(text)
    text = normalize_numbers(text)
    return text


def chunk_text(text: str, max_tokens: int = 200) -> list[str]:
    """Split text at sentence boundaries targeting max_tokens per chunk.

    Token count is approximated by whitespace-splitting.
    Returns at least one chunk (never empty list).
    """
    if not text.strip():
        return [text]

    sentences = re.split(r"(?<=[.!?])\s+", text)
    chunks: list[str] = []
    current_chunk: list[str] = []
    current_tokens = 0

    for sentence in sentences:
        token_count = len(sentence.split())
        if current_tokens + token_count > max_tokens and current_chunk:
            chunks.append(" ".join(current_chunk))
            current_chunk = [sentence]
            current_tokens = token_count
        else:
            current_chunk.append(sentence)
            current_tokens += token_count

    if current_chunk:
        chunks.append(" ".join(current_chunk))

    return chunks if chunks else [text]
