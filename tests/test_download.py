"""Tests for model auto-download module."""

from __future__ import annotations

import ssl
from email.message import Message
from pathlib import Path
from unittest.mock import patch

import pytest

from cumadre.download import (
    _download_file,
    ensure_kokoro_models,
    ensure_qwen3_models,
)


class _FakeResponse:
    """Minimal file-like object for mocking urlopen responses."""

    def __init__(self, data: bytes, content_length: str | None = None) -> None:
        self._data = data
        self._pos = 0
        self.headers = Message()
        if content_length is not None:
            self.headers["Content-Length"] = content_length

    def read(self, size: int = -1) -> bytes:
        if size == -1:
            chunk = self._data[self._pos :]
            self._pos = len(self._data)
            return chunk
        chunk = self._data[self._pos : self._pos + size]
        self._pos += size
        return chunk

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        pass


class TestDownloadFile:
    """Tests for the _download_file helper."""

    def test_downloads_to_destination(self, tmp_path: Path) -> None:
        dest = tmp_path / "model.onnx"
        with patch("cumadre.download.urllib.request.urlopen") as mock_open:
            mock_open.return_value = _FakeResponse(b"model-data")
            _download_file("https://example.com/model.onnx", dest)

        assert dest.is_file()
        assert dest.read_bytes() == b"model-data"

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        dest = tmp_path / "subdir" / "deep" / "model.bin"
        with patch("cumadre.download.urllib.request.urlopen") as mock_open:
            mock_open.return_value = _FakeResponse(b"data")
            _download_file("https://example.com/model.bin", dest)

        assert dest.is_file()

    def test_uses_shutil_move_for_cross_filesystem_safety(self, tmp_path: Path) -> None:
        dest = tmp_path / "model.onnx"

        def fake_move(src: str, dst: str) -> None:
            Path(src).rename(dst)

        with (
            patch("cumadre.download.urllib.request.urlopen") as mock_open,
            patch("cumadre.download.shutil.move", side_effect=fake_move) as mock_move,
        ):
            mock_open.return_value = _FakeResponse(b"model-data")
            _download_file("https://example.com/model.onnx", dest)

        tmp_file = dest.with_suffix(".onnx.tmp")
        mock_move.assert_called_once_with(str(tmp_file), str(dest))

    def test_cleans_up_tmp_on_failure(self, tmp_path: Path) -> None:
        dest = tmp_path / "model.onnx"
        with (
            patch("cumadre.download.urllib.request.urlopen") as mock_open,
            pytest.raises(ConnectionError),
        ):
            mock_open.side_effect = ConnectionError("network error")
            _download_file("https://example.com/model.onnx", dest)

        assert not dest.is_file()
        assert not dest.with_suffix(".onnx.tmp").is_file()

    def test_logs_critical_on_download_failure(self, tmp_path: Path) -> None:
        dest = tmp_path / "model.onnx"
        with (
            patch("cumadre.download.urllib.request.urlopen") as mock_open,
            patch("cumadre.download.logger") as mock_logger,
            pytest.raises(ConnectionError),
        ):
            mock_open.side_effect = ConnectionError("network error")
            _download_file("https://example.com/model.onnx", dest)

        mock_logger.critical.assert_called_once()
        assert "Failed to download" in mock_logger.critical.call_args[0][0]

    def test_logs_critical_on_ssl_error(self, tmp_path: Path) -> None:
        dest = tmp_path / "model.onnx"
        ssl_err = ssl.SSLCertVerificationError("certificate verify failed")
        with (
            patch("cumadre.download.urllib.request.urlopen") as mock_open,
            patch("cumadre.download.logger") as mock_logger,
            pytest.raises(ssl.SSLCertVerificationError),
        ):
            mock_open.side_effect = ssl_err
            _download_file("https://example.com/model.onnx", dest)

        mock_logger.critical.assert_called_once()
        assert "SSL certificate" in mock_logger.critical.call_args[0][0]


class TestEnsureKokoroModels:
    """Tests for ensure_kokoro_models."""

    def test_skips_download_when_files_exist(self, tmp_path: Path) -> None:
        model = tmp_path / "kokoro.onnx"
        voices = tmp_path / "voices.bin"
        model.write_bytes(b"model")
        voices.write_bytes(b"voices")

        with patch("cumadre.download._download_file") as mock_dl:
            ensure_kokoro_models(
                model_path=str(model),
                voices_path=str(voices),
                model_url="https://example.com/model",
                voices_url="https://example.com/voices",
            )

        mock_dl.assert_not_called()

    def test_downloads_missing_model(self, tmp_path: Path) -> None:
        model = tmp_path / "kokoro.onnx"
        voices = tmp_path / "voices.bin"
        voices.write_bytes(b"voices")

        with patch("cumadre.download._download_file") as mock_dl:
            ensure_kokoro_models(
                model_path=str(model),
                voices_path=str(voices),
                model_url="https://example.com/model",
                voices_url="https://example.com/voices",
            )

        mock_dl.assert_called_once_with("https://example.com/model", model)

    def test_downloads_missing_voices(self, tmp_path: Path) -> None:
        model = tmp_path / "kokoro.onnx"
        voices = tmp_path / "voices.bin"
        model.write_bytes(b"model")

        with patch("cumadre.download._download_file") as mock_dl:
            ensure_kokoro_models(
                model_path=str(model),
                voices_path=str(voices),
                model_url="https://example.com/model",
                voices_url="https://example.com/voices",
            )

        mock_dl.assert_called_once_with("https://example.com/voices", voices)

    def test_downloads_both_when_missing(self, tmp_path: Path) -> None:
        model = tmp_path / "kokoro.onnx"
        voices = tmp_path / "voices.bin"

        with patch("cumadre.download._download_file") as mock_dl:
            ensure_kokoro_models(
                model_path=str(model),
                voices_path=str(voices),
                model_url="https://example.com/model",
                voices_url="https://example.com/voices",
            )

        assert mock_dl.call_count == 2

    def test_skips_when_urls_empty_and_files_missing(self, tmp_path: Path) -> None:
        model = tmp_path / "kokoro.onnx"
        voices = tmp_path / "voices.bin"

        with patch("cumadre.download._download_file") as mock_dl:
            ensure_kokoro_models(
                model_path=str(model),
                voices_path=str(voices),
                model_url="",
                voices_url="",
            )

        mock_dl.assert_not_called()


class TestEnsureQwen3Models:
    """Tests for ensure_qwen3_models."""

    def test_skips_download_when_files_exist(self, tmp_path: Path) -> None:
        model = tmp_path / "qwen3.gguf"
        tokenizer = tmp_path / "tokenizer.gguf"
        model.write_bytes(b"model")
        tokenizer.write_bytes(b"tokenizer")

        with patch("cumadre.download._download_file") as mock_dl:
            ensure_qwen3_models(
                model_path=str(model),
                tokenizer_path=str(tokenizer),
                model_url="https://example.com/model",
                tokenizer_url="https://example.com/tokenizer",
            )

        mock_dl.assert_not_called()

    def test_downloads_missing_model(self, tmp_path: Path) -> None:
        model = tmp_path / "qwen3.gguf"
        tokenizer = tmp_path / "tokenizer.gguf"
        tokenizer.write_bytes(b"tokenizer")

        with patch("cumadre.download._download_file") as mock_dl:
            ensure_qwen3_models(
                model_path=str(model),
                tokenizer_path=str(tokenizer),
                model_url="https://example.com/model",
                tokenizer_url="https://example.com/tokenizer",
            )

        mock_dl.assert_called_once_with("https://example.com/model", model)

    def test_skips_when_urls_empty_and_files_missing(self, tmp_path: Path) -> None:
        model = tmp_path / "qwen3.gguf"
        tokenizer = tmp_path / "tokenizer.gguf"

        with patch("cumadre.download._download_file") as mock_dl:
            ensure_qwen3_models(
                model_path=str(model),
                tokenizer_path=str(tokenizer),
                model_url="",
                tokenizer_url="",
            )

        mock_dl.assert_not_called()

    def test_downloads_both_when_urls_provided(self, tmp_path: Path) -> None:
        model = tmp_path / "qwen3.gguf"
        tokenizer = tmp_path / "tokenizer.gguf"

        with patch("cumadre.download._download_file") as mock_dl:
            ensure_qwen3_models(
                model_path=str(model),
                tokenizer_path=str(tokenizer),
                model_url="https://example.com/model",
                tokenizer_url="https://example.com/tokenizer",
            )

        assert mock_dl.call_count == 2
