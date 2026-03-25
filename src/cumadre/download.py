"""Model auto-download for first-time container startup."""

from __future__ import annotations

import shutil
import ssl
import urllib.request
from pathlib import Path

from cumadre.logging import get_logger

logger = get_logger("download")

_DOWNLOAD_TIMEOUT = 300  # seconds per file


def _download_file(url: str, dest: Path) -> None:
    """Download a file from URL to destination path.

    Uses a temporary file to avoid partial downloads on failure.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    logger.info("Downloading %s → %s", url, dest)

    tmp = dest.with_suffix(dest.suffix + ".tmp")
    try:
        with (
            urllib.request.urlopen(url, timeout=_DOWNLOAD_TIMEOUT) as resp,
            tmp.open("wb") as f,
        ):
            content_length = resp.headers.get("Content-Length")
            if content_length:
                logger.info(
                    "Expected size: %.1f MB", int(content_length) / (1024 * 1024)
                )
            shutil.copyfileobj(resp, f)
        shutil.move(str(tmp), str(dest))
        size_mb = dest.stat().st_size / (1024 * 1024)
        logger.info("Downloaded %s (%.1f MB)", dest.name, size_mb)
    except ssl.SSLCertVerificationError:
        tmp.unlink(missing_ok=True)
        logger.critical(
            "SSL certificate verification failed for %s. "
            "Check system CA certificates or set SSL_CERT_FILE / SSL_CERT_DIR env var.",
            url,
        )
        raise
    except Exception as err:
        tmp.unlink(missing_ok=True)
        logger.critical("Failed to download %s: %s", url, err)
        raise


def _ensure_file(path: Path, url: str, label: str) -> None:
    """Download a single file if missing and URL is configured."""
    if path.is_file():
        return
    if not url:
        logger.warning("%s missing and no download URL configured: %s", label, path)
        return
    _download_file(url, path)


def ensure_kokoro_models(
    model_path: str,
    voices_path: str,
    model_url: str,
    voices_url: str,
) -> None:
    """Download Kokoro ONNX model and voices if not present."""
    model = Path(model_path)
    voices = Path(voices_path)

    if model.is_file() and voices.is_file():
        logger.info("Kokoro models already present, skipping download")
        return

    _ensure_file(model, model_url, "Kokoro model")
    _ensure_file(voices, voices_url, "Kokoro voices")


def ensure_qwen3_models(
    model_path: str,
    tokenizer_path: str,
    model_url: str,
    tokenizer_url: str,
) -> None:
    """Download Qwen3 GGUF model and tokenizer if not present."""
    model = Path(model_path)
    tokenizer = Path(tokenizer_path)

    if model.is_file() and tokenizer.is_file():
        logger.info("Qwen3 models already present, skipping download")
        return

    _ensure_file(model, model_url, "Qwen3 model")
    _ensure_file(tokenizer, tokenizer_url, "Qwen3 tokenizer")
