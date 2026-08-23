"""pt-BR text normalization (currency, dates, times, numbers, siglas)."""

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

# Time with h suffix: 9h30 / 9h
_HOUR_H_RE = re.compile(r"\b(\d{1,2})h(\d{2})?\b", re.IGNORECASE)

# Ordinals: 3º, 1ª, 10º
_ORDINAL_RE = re.compile(r"(\d+)[ºª]")

# Thousands-grouped integers: 1.234 / 12.345.678 (currency consumed earlier)
_THOUSANDS_RE = re.compile(r"\b(\d{1,3}(?:\.\d{3})+)\b")

# Decimals with Brazilian comma: 10,5 / 10,50 (currency consumed earlier)
_DECIMAL_RE = re.compile(r"\b(\d+),(\d+)\b")

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
    """Replace HH:MM and 9h30 time patterns with pt-BR words."""

    def _words(hour: int, minute: int | None) -> str:
        hour_words = _n2w(hour)
        if minute is None or minute == 0:
            return hour_words
        return f"{hour_words} e {_n2w(minute)}"

    def _replace_colon(match: re.Match[str]) -> str:
        hour = int(match.group(1))
        minute = int(match.group(2))
        if not (0 <= hour <= 23) or not (0 <= minute <= 59):
            return match.group(0)
        return _words(hour, minute)

    def _replace_h(match: re.Match[str]) -> str:
        hour = int(match.group(1))
        if not (0 <= hour <= 23):
            return match.group(0)
        minute = int(match.group(2)) if match.group(2) else None
        if minute is not None and not (0 <= minute <= 59):
            return match.group(0)
        return _words(hour, minute) + (" horas" if minute is None else "")

    text = _TIME_RE.sub(_replace_colon, text)
    return _HOUR_H_RE.sub(_replace_h, text)


def normalize_phones(text: str) -> str:
    """Read masked phone numbers digit-by-digit with group pauses."""

    def _replace(match: re.Match[str]) -> str:
        digits = re.sub(r"\D", "", match.group(0))
        # Split DDD (2 digits) from the subscriber number when present.
        groups = [digits[:2], digits[2:]] if len(digits) >= 10 else [digits]
        spoken = ", ".join(" ".join(_DIGIT_WORDS_PT[d] for d in g) for g in groups)
        return f"{spoken}"

    return _PHONE_RE.sub(_replace, text)


def normalize_numbers(text: str) -> str:
    """Replace ordinals, decimals, thousands groups and integers with words.

    Decimal commas and dot-grouped thousands MUST become words here;
    leaving them glued ("dez,cinquenta", "um.duzentos...") feeds the TTS
    out-of-distribution punctuation and stalls generation.
    """

    def _replace_ordinal(match: re.Match[str]) -> str:
        result = _n2w(int(match.group(1)), to="ordinal")
        if match.group(0).endswith("ª") and result.endswith("o"):
            result = result[:-1] + "a"
        return result

    def _replace_thousands(match: re.Match[str]) -> str:
        return _n2w(int(match.group(1).replace(".", "")))

    def _replace_decimal(match: re.Match[str]) -> str:
        # Fractional digits read as an integer ("10,50" -> "dez vírgula
        # cinquenta"), the colloquial pt-BR reading; num2words(float)
        # would drop the trailing zero.
        integer_words = _n2w(int(match.group(1)))
        fraction_words = _n2w(int(match.group(2)))
        return f"{integer_words} vírgula {fraction_words}"

    text = _ORDINAL_RE.sub(_replace_ordinal, text)
    text = _THOUSANDS_RE.sub(_replace_thousands, text)
    text = _DECIMAL_RE.sub(_replace_decimal, text)

    def _replace_number(match: re.Match[str]) -> str:
        return _n2w(int(match.group(1)))

    return _NUMBER_RE.sub(_replace_number, text)


# Phone numbers: masked pt-BR forms — (11) 99999-8888, 11 99999-8888,
# 99999-8888, 11999998888
_PHONE_RE = re.compile(r"(?:\(\d{2}\)\s?|\b\d{2}\s|\b)?\d{4,5}-?\d{4}\b")

_DIGIT_WORDS_PT = {
    "0": "zero",
    "1": "um",
    "2": "dois",
    "3": "três",
    "4": "quatro",
    "5": "cinco",
    "6": "seis",
    "7": "sete",
    "8": "oito",
    "9": "nove",
}

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
    """Convert spelled siglas to spaced format for engine pronunciation.

    Spelled siglas (CNPJ, CPF, FGTS) become "C N P J", "C P F", "F G T S".
    Word siglas (SUS, PIX, LOAS) are kept as-is.
    """

    def _replace(match: re.Match[str]) -> str:
        sigla = match.group(1)
        if sigla in WORD_SIGLAS:
            return sigla
        return " ".join(sigla)

    return _SIGLA_RE.sub(_replace, text)


# Percent: 50% / 50 %
_PERCENT_RE = re.compile(r"\b(\d+)\s?%")

# The 24/7 idiom (before short-date handling would read it as a day/month).
_ROUND_THE_CLOCK_RE = re.compile(r"\b24/7\b")

# Short dates: dd/mm (full dd/mm/yyyy consumed earlier)
_SHORT_DATE_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})\b")

# Emoji and symbol blocks that tokenize as garbage.
_EMOJI_RE = re.compile(
    "[\U0001f000-\U0001faff\u2600-\u27bf\ufe0f\u2b00-\u2bff\u2190-\u21ff]+"
)


def normalize_percent(text: str) -> str:
    """Replace '50%' patterns with '<words> por cento'."""

    def _replace(match: re.Match[str]) -> str:
        return f"{_n2w(int(match.group(1)))} por cento"

    return _PERCENT_RE.sub(_replace, text)


def normalize_short_dates(text: str) -> str:
    """Replace remaining dd/mm patterns with 'day de month'.

    Implausible day/month ranges are left for the slash sanitizer.
    """

    def _replace(match: re.Match[str]) -> str:
        day = int(match.group(1))
        month = int(match.group(2))
        if not (1 <= day <= 31) or not (1 <= month <= 12):
            return match.group(0)
        return f"{_n2w(day)} de {MONTHS_PT[month - 1]}"

    return _SHORT_DATE_RE.sub(_replace, text)


def sanitize_text(text: str) -> str:
    """Final pass: drop URLs/emoji/slashes, collapse whitespace.

    Runs after every digit-aware pattern has consumed its share; any '/'
    still standing (e/ou, paths) becomes a plain space — a raw slash is
    never fed to the engine. URLs are dropped entirely: spelling one out
    is never what a listener wants.
    """
    text = re.sub(r"https?://\S+", " ", text)
    text = _EMOJI_RE.sub(" ", text)
    text = text.replace("/", " ")
    return re.sub(r"\s{2,}", " ", text).strip()


def normalize_text(text: str) -> str:
    """Normalize pt-BR text: currency, dates, times, numbers, symbols.

    Order matters: every pattern that needs raw digits runs BEFORE the
    integer expansion pass consumes them. Currency first (R$ prefix),
    then dates/times, then percent / 24-7 / short dates / phones, then
    standalone numbers, then the symbol sanitizer last.
    """
    text = normalize_currency(text)
    text = normalize_dates(text)
    text = normalize_times(text)
    text = normalize_percent(text)
    text = _ROUND_THE_CLOCK_RE.sub(f"{_n2w(24)} por {_n2w(7)}", text)
    text = normalize_short_dates(text)
    text = normalize_phones(text)
    text = normalize_numbers(text)
    return sanitize_text(text)
