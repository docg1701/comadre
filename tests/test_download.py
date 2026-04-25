"""Tests for ``comadre.download`` (model auto-download).

Lean by design (test-suite review 2026-04-25): per-model variant tests
collapsed; kept the cross-filesystem-safe move + skip-when-present
short-circuit + empty-URL fallback (air-gap support).
"""

from __future__ import annotations

from email.message import Message
from pathlib import Path
from unittest.mock import patch

import pytest

from comadre.download import _download_file, ensure_kokoro_models, ensure_qwen3_models


class _FakeResponse:
    def __init__(self, data: bytes) -> None:
        self._data = data
        self.headers = Message()
        self.headers["Content-Length"] = str(len(data))

    def read(self, size: int = -1) -> bytes:
        if size == -1 or size >= len(self._data):
            chunk, self._data = self._data, b""
            return chunk
        chunk, self._data = self._data[:size], self._data[size:]
        return chunk

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        pass


def test_download_file_writes_to_destination_and_cleans_tmp_on_failure(
    tmp_path: Path,
) -> None:
    """Happy path lands a file at the destination; failure cleans up
    the .tmp sibling so a retry doesn't see partial bytes."""
    dest = tmp_path / "nested" / "model.onnx"
    with patch("comadre.download.urllib.request.urlopen") as mock_open:
        mock_open.return_value = _FakeResponse(b"x" * 1024)
        _download_file("https://example.com/model.onnx", dest)
    assert dest.exists()
    assert dest.read_bytes() == b"x" * 1024
    assert list(tmp_path.glob("**/*.tmp")) == []

    # Failure mid-download must NOT leave a .tmp leftover.
    fail_dest = tmp_path / "fail.onnx"
    with (
        patch("comadre.download.urllib.request.urlopen", side_effect=OSError("boom")),
        pytest.raises(OSError),
    ):
        _download_file("https://example.com/x", fail_dest)
    assert not fail_dest.exists()
    assert list(tmp_path.glob("*.tmp")) == []


def test_ensure_models_skips_existing_downloads_missing(tmp_path: Path) -> None:
    """Skip-when-present: present files trigger no urlopen. Missing files
    with non-empty URLs trigger one urlopen each."""
    model = tmp_path / "kokoro.onnx"
    voices = tmp_path / "voices.bin"

    # Both present → zero downloads.
    model.write_bytes(b"existing")
    voices.write_bytes(b"existing")
    with patch("comadre.download.urllib.request.urlopen") as mock_open:
        ensure_kokoro_models(
            model_path=model,
            voices_path=voices,
            model_url="https://x/m",
            voices_url="https://x/v",
        )
        mock_open.assert_not_called()

    # Both absent → two downloads.
    model.unlink()
    voices.unlink()
    with patch("comadre.download.urllib.request.urlopen") as mock_open:
        mock_open.return_value = _FakeResponse(b"data")
        ensure_kokoro_models(
            model_path=model,
            voices_path=voices,
            model_url="https://x/m",
            voices_url="https://x/v",
        )
        assert mock_open.call_count == 2


def test_ensure_models_with_empty_urls_skips_download_for_air_gap(
    tmp_path: Path,
) -> None:
    """Empty URL = air-gap deployment opt-out: file missing + URL empty
    must NOT raise; the operator deploys models out-of-band via SCP."""
    model = tmp_path / "qwen3.gguf"
    tokenizer = tmp_path / "tokenizer.gguf"
    with patch("comadre.download.urllib.request.urlopen") as mock_open:
        ensure_qwen3_models(
            model_path=model,
            tokenizer_path=tokenizer,
            model_url="",
            tokenizer_url="",
        )
        mock_open.assert_not_called()
    # Files still missing (air-gap path; operator deploys later).
    assert not model.exists()
    assert not tokenizer.exists()
