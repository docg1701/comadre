"""CPF/CNPJ validation (via `validate-docbr`) and Fernet encryption for tax IDs.

Validation delegates to the `validate-docbr` package, which maintains the
canonical Brazilian tax-ID algorithms and — since version 2.0 (2026-04) —
supports the alphanumeric CNPJ format defined by RFB IN 2.229/2024, effective
July 2026. The defaults `CPF(repeated_digits=False)` and `CNPJ()` reject
all-same-digit inputs and incorrect check digits.

Anti-enumeration (FR37, NFR16): `InvalidTaxIdError` NEVER receives the raw
input. The rejected value exists only in the caller's local scope and is
dropped when the exception propagates.
"""

from __future__ import annotations

import re

from cryptography.fernet import Fernet
from pydantic import SecretStr
from validate_docbr import CNPJ, CPF

from comadre.exceptions import InvalidTaxIdError

_MASK_CHARS = re.compile(r"[.\-/\s]")

_CPF = CPF()  # repeated_digits=False by default — rejects 111.111.111-11 etc.
_CNPJ = CNPJ()  # 2.0+ handles numeric and alphanumeric CNPJ.


def strip_tax_id(raw: str) -> str:
    """Return the canonical storage form of a CPF/CNPJ.

    Removes mask punctuation (`.`, `-`, `/`, whitespace) and uppercases the
    remainder. Uppercase is a no-op for numeric CPF/CNPJ but normalizes
    alphanumeric CNPJ so `12.abc.345/xy01-89` and `12.ABC.345/XY01-89` end
    up identical in `tax_id_encrypted`.
    """
    return _MASK_CHARS.sub("", raw).upper()


def validate_cpf(raw: str) -> None:
    """Validate a CPF (masked or unmasked). Raises `InvalidTaxIdError("cpf")`.

    Delegates to `validate_docbr.CPF.validate` against the canonical stripped
    form. The explicit length check is required because validate-docbr
    zero-pads inputs shorter than 11 digits to be tolerant of typed input —
    we want canonical 11-digit storage, so we reject shortforms upfront. The
    rejected input is never stored on the exception (FR37/NFR16
    anti-enumeration invariant).
    """
    canonical = strip_tax_id(raw)
    if len(canonical) != 11 or not _CPF.validate(canonical):
        raise InvalidTaxIdError("cpf")


def validate_cnpj(raw: str) -> None:
    """Validate a CNPJ (numeric or alphanumeric, masked or unmasked).

    Raises `InvalidTaxIdError("cnpj")` on failure. Validation runs against
    the canonical stripped form so the length check and checksum check agree
    on input shape. `validate-docbr` 2.0+ accepts the alphanumeric format
    defined in RFB IN 2.229/2024 (effective July 2026).
    """
    canonical = strip_tax_id(raw)
    if len(canonical) != 14 or not _CNPJ.validate(canonical):
        raise InvalidTaxIdError("cnpj")


def encrypt_tax_id(canonical: str, key: SecretStr) -> bytes:
    """Fernet-encrypt the stripped, uppercased tax ID. Returns ciphertext bytes."""
    fernet = Fernet(key.get_secret_value().encode())
    return fernet.encrypt(canonical.encode())
