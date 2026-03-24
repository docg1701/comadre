"""Tests for the pt-BR text preprocessing module."""

from cumadre.preprocessing import (
    WORD_SIGLAS,
    chunk_text,
    expand_siglas,
    normalize_currency,
    normalize_dates,
    normalize_numbers,
    normalize_text,
    normalize_times,
)


class TestExpandSiglas:
    def test_spelled_sigla_cnpj(self) -> None:
        assert expand_siglas("Seu CNPJ está") == "Seu C N P J está"

    def test_spelled_sigla_cpf(self) -> None:
        assert expand_siglas("Informe o CPF") == "Informe o C P F"

    def test_spelled_sigla_fgts(self) -> None:
        assert expand_siglas("Saque FGTS") == "Saque F G T S"

    def test_word_sigla_sus_kept(self) -> None:
        assert expand_siglas("Consulta no SUS") == "Consulta no SUS"

    def test_word_sigla_pix_kept(self) -> None:
        assert expand_siglas("Pague via PIX") == "Pague via PIX"

    def test_word_sigla_loas_kept(self) -> None:
        assert expand_siglas("Benefício LOAS") == "Benefício LOAS"

    def test_word_sigla_detran_kept(self) -> None:
        assert expand_siglas("Vá ao DETRAN") == "Vá ao DETRAN"

    def test_all_word_siglas_preserved(self) -> None:
        for sigla in WORD_SIGLAS:
            result = expand_siglas(f"Teste {sigla} aqui")
            assert sigla in result, f"{sigla} should be preserved"

    def test_mixed_siglas(self) -> None:
        result = expand_siglas("O CPF e o SUS são diferentes do FGTS")
        assert "C P F" in result
        assert "SUS" in result
        assert "F G T S" in result

    def test_no_siglas(self) -> None:
        text = "Texto sem siglas aqui"
        assert expand_siglas(text) == text

    def test_empty_string(self) -> None:
        assert expand_siglas("") == ""

    def test_single_uppercase_letter_not_matched(self) -> None:
        assert expand_siglas("Use a letra A") == "Use a letra A"

    def test_lowercase_not_matched(self) -> None:
        assert expand_siglas("cpf cnpj") == "cpf cnpj"

    def test_multiple_spelled_siglas(self) -> None:
        result = expand_siglas("CNPJ e CPF e INSS")
        assert "C N P J" in result
        assert "C P F" in result
        assert "I N S S" in result

    def test_word_sigla_tv_kept(self) -> None:
        assert expand_siglas("Assista na TV") == "Assista na TV"

    def test_word_sigla_ok_kept(self) -> None:
        assert expand_siglas("Tudo OK aqui") == "Tudo OK aqui"

    def test_word_sigla_covid_kept(self) -> None:
        assert expand_siglas("Vacina COVID") == "Vacina COVID"

    def test_word_sigla_pasep_kept(self) -> None:
        assert expand_siglas("PIS/PASEP") == "PIS/PASEP"

    def test_word_sigla_mei_kept(self) -> None:
        assert expand_siglas("Cadastro MEI") == "Cadastro MEI"

    def test_word_sigla_prouni_kept(self) -> None:
        assert expand_siglas("Inscrição PROUNI") == "Inscrição PROUNI"

    def test_word_sigla_sebrae_kept(self) -> None:
        assert expand_siglas("Curso no SEBRAE") == "Curso no SEBRAE"


class TestNormalizeNumbers:
    def test_standalone_integer(self) -> None:
        assert "mil e quinhentos" in normalize_numbers("O valor é 1500")

    def test_large_number(self) -> None:
        result = normalize_numbers("São 42 itens")
        assert "quarenta e dois" in result

    def test_ordinal_masculine(self) -> None:
        result = normalize_numbers("Ele é o 3º da fila")
        assert "terceiro" in result

    def test_ordinal_feminine(self) -> None:
        result = normalize_numbers("Ela é a 1ª colocada")
        assert "primeira" in result

    def test_ordinal_large(self) -> None:
        result = normalize_numbers("O 10º andar")
        assert "décimo" in result

    def test_no_numbers(self) -> None:
        text = "Sem numeros aqui"
        assert normalize_numbers(text) == text


class TestNormalizeCurrency:
    def test_with_cents(self) -> None:
        result = normalize_currency("Custa R$ 1.500,00")
        assert "mil e quinhentos reais" in result

    def test_with_decimals(self) -> None:
        result = normalize_currency("Total R$ 42,50")
        assert "quarenta e dois reais" in result
        assert "cinquenta centavos" in result

    def test_no_space_after_symbol(self) -> None:
        result = normalize_currency("Valor R$100,00")
        assert "cem reais" in result

    def test_no_cents(self) -> None:
        result = normalize_currency("R$ 500")
        assert "quinhentos" in result

    def test_preserves_surrounding_text(self) -> None:
        result = normalize_currency("O preço é R$ 10,00 por unidade")
        assert result.startswith("O preço é")
        assert result.endswith("por unidade")


class TestNormalizeDates:
    def test_standard_date(self) -> None:
        result = normalize_dates("Data: 21/03/2026")
        assert "vinte e um" in result
        assert "março" in result
        assert "dois mil e vinte e seis" in result

    def test_january(self) -> None:
        assert "janeiro" in normalize_dates("01/01/2025")

    def test_february(self) -> None:
        assert "fevereiro" in normalize_dates("15/02/2025")

    def test_december(self) -> None:
        assert "dezembro" in normalize_dates("25/12/2025")

    def test_all_months(self) -> None:
        months = [
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
        for i, month_name in enumerate(months, 1):
            result = normalize_dates(f"01/{i:02d}/2025")
            assert month_name in result, f"Month {i} should produce '{month_name}'"

    def test_invalid_month_preserved(self) -> None:
        result = normalize_dates("01/13/2025")
        assert "01/13/2025" in result

    def test_invalid_day_preserved(self) -> None:
        assert "99/06/2025" in normalize_dates("99/06/2025")

    def test_day_zero_preserved(self) -> None:
        assert "00/01/2025" in normalize_dates("00/01/2025")

    def test_preserves_surrounding_text(self) -> None:
        result = normalize_dates("Nascido em 15/06/1990 no Brasil")
        assert result.startswith("Nascido em")
        assert result.endswith("no Brasil")


class TestNormalizeTimes:
    def test_afternoon(self) -> None:
        result = normalize_times("Reunião às 14:30")
        assert "catorze e trinta" in result or "quatorze e trinta" in result

    def test_midnight(self) -> None:
        result = normalize_times("Saída 00:00")
        assert "zero" in result

    def test_noon(self) -> None:
        result = normalize_times("Almoço 12:00")
        assert "doze" in result
        assert "e" not in result.split("doze")[-1].split()[0:1]

    def test_morning(self) -> None:
        result = normalize_times("Aula 08:15")
        assert "oito e quinze" in result

    def test_exact_hour_no_minutes(self) -> None:
        result = normalize_times("Evento 10:00")
        assert "dez" in result

    def test_preserves_surrounding_text(self) -> None:
        result = normalize_times("Das 09:00 às 17:00")
        assert result.startswith("Das")

    def test_invalid_hour_preserved(self) -> None:
        assert "25:00" in normalize_times("Evento 25:00")

    def test_invalid_minute_preserved(self) -> None:
        assert "10:99" in normalize_times("Evento 10:99")


class TestNormalizeText:
    def test_mixed_content(self) -> None:
        text = "Pedido R$ 1.500,00 em 21/03/2026 às 14:30 com 3 itens"
        result = normalize_text(text)
        assert "mil e quinhentos reais" in result
        assert "março" in result
        assert "R$" not in result
        assert "21/03/2026" not in result

    def test_currency_before_numbers(self) -> None:
        result = normalize_text("R$ 1500 e mais 200 unidades")
        assert "mil e quinhentos reais" in result
        assert "duzentos" in result

    def test_no_normalizable_content(self) -> None:
        text = "Texto simples sem numeros"
        assert normalize_text(text) == text

    def test_empty_string(self) -> None:
        assert normalize_text("") == ""

    def test_ordinals_in_mixed(self) -> None:
        result = normalize_text("O 3º pedido custou R$ 50,00")
        assert "terceiro" in result
        assert "cinquenta reais" in result


class TestChunkText:
    def test_short_text_single_chunk(self) -> None:
        chunks = chunk_text("Texto curto.")
        assert len(chunks) == 1
        assert chunks[0] == "Texto curto."

    def test_long_text_splits_at_sentences(self) -> None:
        sentences = [f"Esta e a frase numero {i}." for i in range(50)]
        text = " ".join(sentences)
        chunks = chunk_text(text, max_tokens=30)
        assert len(chunks) > 1
        for chunk in chunks:
            assert len(chunk.split()) <= 35  # allow some tolerance

    def test_respects_max_tokens(self) -> None:
        text = "Primeira frase curta. Segunda frase curta. Terceira frase curta."
        chunks = chunk_text(text, max_tokens=10)
        assert len(chunks) >= 1

    def test_empty_string(self) -> None:
        chunks = chunk_text("")
        assert len(chunks) == 1

    def test_single_sentence(self) -> None:
        chunks = chunk_text("Uma unica frase sem ponto final")
        assert len(chunks) == 1
        assert chunks[0] == "Uma unica frase sem ponto final"

    def test_never_returns_empty_list(self) -> None:
        assert len(chunk_text("")) >= 1
        assert len(chunk_text("   ")) >= 1
        assert len(chunk_text("Hello.")) >= 1

    def test_preserves_all_content(self) -> None:
        sentences = [f"Frase {i}." for i in range(20)]
        text = " ".join(sentences)
        chunks = chunk_text(text, max_tokens=10)
        reconstructed = " ".join(chunks)
        for sentence in sentences:
            assert sentence in reconstructed
