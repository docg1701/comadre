"""Tests for comadre.keys.crypto — validate-docbr wrappers + Fernet encryption."""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet, InvalidToken
from pydantic import SecretStr

from comadre.exceptions import InvalidTaxIdError
from comadre.keys.crypto import (
    decrypt_tax_id,
    encrypt_tax_id,
    strip_tax_id,
    validate_cnpj,
    validate_cpf,
)

# Valid CPFs — check digits verified against the canonical algorithm.
# Mix of masked and unmasked forms: validate-docbr accepts both.
VALID_CPFS = [
    "12345678909",
    "01234567890",
    "11144477735",
    "52998224725",
    "39053344705",
    "86288366757",
    "68656713337",
    "97532890147",
    "53198094097",
    "41373406097",
    "123.456.789-09",  # masked form
]

# Valid numeric CNPJs.
VALID_CNPJS = [
    "12345678000195",
    "11222333000181",
    "05468057000133",
    "27865757000102",
    "00000000000191",
    "12.345.678/0001-95",  # masked form
]


class TestStripTaxId:
    def test_removes_dots_dashes_slashes(self) -> None:
        assert strip_tax_id("123.456.789-09") == "12345678909"
        assert strip_tax_id("12.345.678/0001-95") == "12345678000195"

    def test_preserves_digits_only(self) -> None:
        assert strip_tax_id("12345678909") == "12345678909"

    def test_strips_whitespace(self) -> None:
        assert strip_tax_id("  123 456 789 09  ") == "12345678909"

    def test_empty_input(self) -> None:
        assert strip_tax_id("") == ""

    def test_preserves_letters_for_alphanumeric_cnpj(self) -> None:
        """CNPJ alfanumérico (RFB IN 2.229/2024, jul/2026) pode conter letras
        nas posições 1-12. strip_tax_id deve preservar e uppercase-ar."""
        assert strip_tax_id("12.ABC.345/XY01-89") == "12ABC345XY0189"

    def test_uppercases_alphanumeric(self) -> None:
        assert strip_tax_id("12.abc.345/xy01-89") == "12ABC345XY0189"


class TestValidateCpf:
    @pytest.mark.parametrize("cpf", VALID_CPFS)
    def test_accepts_valid_cpfs(self, cpf: str) -> None:
        validate_cpf(cpf)  # must not raise

    @pytest.mark.parametrize(
        "bad",
        [
            "12345678900",  # wrong check digit
            "11144477734",
            "00000000001",
            "52998224720",
            "86288366750",
        ],
    )
    def test_rejects_invalid_checksum(self, bad: str) -> None:
        with pytest.raises(InvalidTaxIdError):
            validate_cpf(bad)

    @pytest.mark.parametrize("bad", ["1234567890", "123456789012", ""])
    def test_rejects_wrong_length(self, bad: str) -> None:
        with pytest.raises(InvalidTaxIdError):
            validate_cpf(bad)

    def test_rejects_all_zeros(self) -> None:
        with pytest.raises(InvalidTaxIdError):
            validate_cpf("00000000000")

    @pytest.mark.parametrize(
        "repeated",
        ["11111111111", "22222222222", "99999999999"],
    )
    def test_rejects_all_same_digit(self, repeated: str) -> None:
        """validate-docbr default `repeated_digits=False` rejects these
        inputs even though they pass the arithmetic check."""
        with pytest.raises(InvalidTaxIdError):
            validate_cpf(repeated)


class TestValidateCnpj:
    @pytest.mark.parametrize("cnpj", VALID_CNPJS)
    def test_accepts_valid_cnpjs(self, cnpj: str) -> None:
        validate_cnpj(cnpj)  # must not raise

    @pytest.mark.parametrize(
        "bad",
        [
            "12345678000190",  # wrong check digit
            "11222333000180",
            "27865757000100",
        ],
    )
    def test_rejects_invalid_checksum(self, bad: str) -> None:
        with pytest.raises(InvalidTaxIdError):
            validate_cnpj(bad)

    @pytest.mark.parametrize("bad", ["1234567800019", "123456780001955", ""])
    def test_rejects_wrong_length(self, bad: str) -> None:
        with pytest.raises(InvalidTaxIdError):
            validate_cnpj(bad)

    def test_rejects_all_same_digit(self) -> None:
        with pytest.raises(InvalidTaxIdError):
            validate_cnpj("11111111111111")


class TestEncryptTaxId:
    def test_round_trip(self) -> None:
        key_bytes = Fernet.generate_key()
        secret = SecretStr(key_bytes.decode())
        ciphertext = encrypt_tax_id("12345678909", secret)
        assert isinstance(ciphertext, bytes)
        plaintext = Fernet(key_bytes).decrypt(ciphertext).decode()
        assert plaintext == "12345678909"

    def test_ciphertext_is_nondeterministic(self) -> None:
        key_bytes = Fernet.generate_key()
        secret = SecretStr(key_bytes.decode())
        c1 = encrypt_tax_id("12345678909", secret)
        c2 = encrypt_tax_id("12345678909", secret)
        assert c1 != c2

    def test_ciphertext_prefix(self) -> None:
        key_bytes = Fernet.generate_key()
        secret = SecretStr(key_bytes.decode())
        ciphertext = encrypt_tax_id("12345678909", secret)
        assert ciphertext.startswith(b"gAAAAA")

    def test_length_exceeds_40_bytes(self) -> None:
        key_bytes = Fernet.generate_key()
        secret = SecretStr(key_bytes.decode())
        ciphertext = encrypt_tax_id("12345678909", secret)
        assert len(ciphertext) > 40

    def test_round_trip_alphanumeric_cnpj(self) -> None:
        """Ensure Fernet handles the upcoming alphanumeric CNPJ form."""
        key_bytes = Fernet.generate_key()
        secret = SecretStr(key_bytes.decode())
        canonical = "12ABC345XY0189"
        ciphertext = encrypt_tax_id(canonical, secret)
        plaintext = Fernet(key_bytes).decrypt(ciphertext).decode()
        assert plaintext == canonical


class TestDecryptTaxId:
    """Story 4.1 — dual primitive: decrypt round-trips encrypt_tax_id."""

    def test_round_trip_cpf(self) -> None:
        key_bytes = Fernet.generate_key()
        secret = SecretStr(key_bytes.decode())
        canonical = "12345678909"
        ciphertext = encrypt_tax_id(canonical, secret)
        assert decrypt_tax_id(ciphertext, secret) == canonical

    def test_round_trip_numeric_cnpj(self) -> None:
        key_bytes = Fernet.generate_key()
        secret = SecretStr(key_bytes.decode())
        canonical = "12345678000195"
        ciphertext = encrypt_tax_id(canonical, secret)
        assert decrypt_tax_id(ciphertext, secret) == canonical

    def test_round_trip_alphanumeric_cnpj(self) -> None:
        key_bytes = Fernet.generate_key()
        secret = SecretStr(key_bytes.decode())
        canonical = "12ABC345XY0189"
        ciphertext = encrypt_tax_id(canonical, secret)
        assert decrypt_tax_id(ciphertext, secret) == canonical

    def test_invalid_token_on_tampered_ciphertext(self) -> None:
        key_bytes = Fernet.generate_key()
        secret = SecretStr(key_bytes.decode())
        ciphertext = encrypt_tax_id("12345678909", secret)
        # Flip the last byte. Fernet's HMAC catches any ciphertext
        # modification, even a single bit.
        tampered = ciphertext[:-1] + bytes([ciphertext[-1] ^ 0x01])
        with pytest.raises(InvalidToken):
            decrypt_tax_id(tampered, secret)

    def test_invalid_token_on_key_mismatch(self) -> None:
        key_a = SecretStr(Fernet.generate_key().decode())
        key_b = SecretStr(Fernet.generate_key().decode())
        ciphertext = encrypt_tax_id("12345678909", key_a)
        with pytest.raises(InvalidToken):
            decrypt_tax_id(ciphertext, key_b)

    def test_invalid_token_on_empty_bytes(self) -> None:
        secret = SecretStr(Fernet.generate_key().decode())
        with pytest.raises(InvalidToken):
            decrypt_tax_id(b"", secret)


class TestAntiEnumeration:
    """FR37 / NFR16: rejected input value must not leak via exception state."""

    def test_no_attribute_captures_raw_input(self) -> None:
        err = InvalidTaxIdError("cpf")
        for forbidden in ("value", "raw", "input", "digits", "tax_id"):
            assert not hasattr(err, forbidden)

    def test_message_contains_no_digits(self) -> None:
        for kind in ("cpf", "cnpj"):
            err = InvalidTaxIdError(kind)  # type: ignore[arg-type]
            assert not any(ch.isdigit() for ch in err.message)
            assert not any(ch.isdigit() for ch in err.hint)

    def test_rejected_value_does_not_survive_on_exception(self) -> None:
        rejected = "11111111111"
        try:
            validate_cpf(rejected)
        except InvalidTaxIdError as exc:
            for attr_name, attr_val in vars(exc).items():
                assert rejected not in str(attr_val), (
                    f"{attr_name!r} leaks rejected value"
                )
            assert rejected not in str(exc)
            assert rejected not in exc.message
            assert rejected not in exc.hint
