"""Model auto-download for first-time container startup.

Downloads the pinned pocket-tts artifacts from HuggingFace into the
POCKET_*_PATH destinations. Runtime generation is fully offline
(HF_HUB_OFFLINE=1): downloads happen once (first boot, with HF_TOKEN)
and are skipped when the destination files already exist.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from huggingface_hub import hf_hub_download

from comadre.logging import get_logger

logger = get_logger("download")

# Pinned revisions from the migration plan section 7.7.
_GATED_REPO = "kyutai/pocket-tts"
_GATED_REVISION = "39592ff23c9ef80098bb74895d104c26275fe2c9"
_PUBLIC_REPO = "kyutai/pocket-tts-without-voice-cloning"
_TOKENIZER_REVISION = "d29db7978e464fb90cb3359ee0c69a273b9142cc"
_EMBEDDINGS_REVISION = "e041936c75475d350b405bc870bcf7c22da4e9e6"


def _is_offline() -> bool:
    """Return True when HF_HUB_OFFLINE=1 (runtime offline mode)."""
    return os.environ.get("HF_HUB_OFFLINE") == "1"


def _fetch_file(
    repo_id: str,
    filename: str,
    revision: str,
    dest: Path,
) -> None:
    """Download a single HF file into dest (skip when dest exists).

    Offline mode (HF_HUB_OFFLINE=1) reads ONLY the local HF cache via
    ``local_files_only=True``; a cache miss fails fast with the "run once
    with HF_TOKEN" message.
    """
    if dest.is_file():
        return
    offline = _is_offline()
    if not offline:
        logger.info("Downloading %s/%s@%s", repo_id, filename, revision)
    try:
        cached = hf_hub_download(
            repo_id=repo_id,
            filename=filename,
            revision=revision,
            local_files_only=offline,
        )
    except Exception as exc:
        if offline:
            raise FileNotFoundError(
                f"Model file missing and HF_HUB_OFFLINE=1: {dest} "
                f"({repo_id}/{filename}). Run once with HF_TOKEN set (and "
                "HF_HUB_OFFLINE unset) to download the pinned model "
                "artifacts, then restart in offline mode."
            ) from exc
        raise
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(cached, dest)
    size_mb = dest.stat().st_size / (1024 * 1024)
    logger.info("Downloaded %s (%.1f MB)", dest.name, size_mb)


def ensure_pocket_models(
    language: str,
    model_path: str,
    tokenizer_path: str,
    default_voice_path: str,
) -> None:
    """Download (if missing) the pocket-tts model, tokenizer, and rafael state.

    ``language`` selects the languages/<lang>/ subtree in the HF repos
    (the POCKET_LANGUAGE value: portuguese or portuguese_24l).
    """
    model = Path(model_path)
    tokenizer = Path(tokenizer_path)
    rafael = Path(default_voice_path)

    if model.is_file() and tokenizer.is_file() and rafael.is_file():
        logger.info("pocket-tts models already present, skipping download")
        return

    _fetch_file(
        _GATED_REPO,
        f"languages/{language}/model.safetensors",
        _GATED_REVISION,
        model,
    )
    _fetch_file(
        _PUBLIC_REPO,
        f"languages/{language}/tokenizer.model",
        _TOKENIZER_REVISION,
        tokenizer,
    )
    _fetch_file(
        _PUBLIC_REPO,
        f"languages/{language}/embeddings/rafael.safetensors",
        _EMBEDDINGS_REVISION,
        rafael,
    )
