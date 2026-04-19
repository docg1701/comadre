"""Tests for comadre.keys.tokens — plaintext, hash, and prefix helpers."""

from __future__ import annotations

import re

import pytest

from comadre.keys.tokens import (
    API_KEY_PREFIX,
    API_KEY_PREFIX_STORED_LEN,
    generate_api_key_plaintext,
    hash_api_key,
    key_prefix_from_plaintext,
)

_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class TestGenerateApiKeyPlaintext:
    def test_starts_with_fixed_prefix(self) -> None:
        assert generate_api_key_plaintext().startswith(API_KEY_PREFIX)

    def test_total_length_53_chars(self) -> None:
        # len("cmdr_live_") == 10, token_urlsafe(32) == 43 chars without padding
        assert len(generate_api_key_plaintext()) == 53

    def test_thousand_samples_unique(self) -> None:
        samples = {generate_api_key_plaintext() for _ in range(1000)}
        assert len(samples) == 1000

    def test_body_is_urlsafe_base64_chars(self) -> None:
        """Token body after the fixed prefix must be URL-safe b64 chars only."""
        body = generate_api_key_plaintext().removeprefix(API_KEY_PREFIX)
        assert re.fullmatch(r"[A-Za-z0-9_-]{43}", body)

    def test_stored_prefix_first_char_is_always_alphanumeric(self) -> None:
        """Regression: CLI tests invoke ``show <prefix>`` etc. positionally;
        a prefix starting with ``-`` or ``_`` is parsed by Click as an option
        group and exits 2. The generator rerolls until the first char after
        ``cmdr_live_`` is ``[A-Za-z0-9]``. 2 000 samples is ~22% expected to
        see a reject under the base64-URL alphabet, so this passes only if
        the retry loop is in place.
        """
        for _ in range(2000):
            plaintext = generate_api_key_plaintext()
            first_stored_char = plaintext[len(API_KEY_PREFIX)]
            assert first_stored_char.isalnum(), (
                f"First stored-prefix char {first_stored_char!r} is not "
                "alphanumeric — Click CLI tests will flake."
            )


class TestHashApiKey:
    def test_returns_64_lowercase_hex(self) -> None:
        digest = hash_api_key("cmdr_live_example")
        assert _HEX64.fullmatch(digest)

    def test_deterministic(self) -> None:
        assert hash_api_key("x") == hash_api_key("x")

    def test_distinct_inputs_distinct_digests(self) -> None:
        assert hash_api_key("x") != hash_api_key("y")

    def test_return_type_is_str(self) -> None:
        """Regression: hash_api_key must use .hexdigest(), not .digest()."""
        digest = hash_api_key("anything")
        assert isinstance(digest, str)
        assert not isinstance(digest, bytes)

    def test_matches_known_sha256(self) -> None:
        """Guard against a future refactor switching algorithm."""
        # SHA-256 of literal ASCII "x"
        expected = "2d711642b726b04401627ca9fbac32f5c8530fb1903cc4db02258717921a4881"
        assert hash_api_key("x") == expected


class TestKeyPrefixFromPlaintext:
    def test_returns_eight_chars(self) -> None:
        plaintext = generate_api_key_plaintext()
        assert len(key_prefix_from_plaintext(plaintext)) == API_KEY_PREFIX_STORED_LEN

    def test_slice_is_after_fixed_prefix(self) -> None:
        plaintext = "cmdr_live_ABCDEFGHijKLMNOPqrstuvwxyz0123456789ab_-"
        assert key_prefix_from_plaintext(plaintext) == "ABCDEFGH"

    @pytest.mark.parametrize("_i", list(range(20)))
    def test_parametric_length_invariant(self, _i: int) -> None:
        plaintext = generate_api_key_plaintext()
        prefix = key_prefix_from_plaintext(plaintext)
        assert len(prefix) == 8
