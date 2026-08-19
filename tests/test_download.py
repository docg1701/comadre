"""Tests for ``comadre.download`` (pocket-tts model auto-download).

v3: mocked ``hf_hub_download`` per the migration plan section 7.7 —
pinned revisions, skip-when-present, offline fail-fast.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from comadre.download import (
    _EMBEDDINGS_REVISION,
    _GATED_REPO,
    _GATED_REVISION,
    _PUBLIC_REPO,
    _TOKENIZER_REVISION,
    ensure_pocket_models,
)


def test_ensure_pocket_models_skips_when_all_present(tmp_path: Path) -> None:
    """All three artifacts present → zero hub calls."""
    model = tmp_path / "model.safetensors"
    tokenizer = tmp_path / "tokenizer.model"
    rafael = tmp_path / "rafael.safetensors"
    for f in (model, tokenizer, rafael):
        f.write_bytes(b"x")
    with patch("comadre.download.hf_hub_download") as mock_hub:
        ensure_pocket_models(
            language="portuguese",
            model_path=model,
            tokenizer_path=tokenizer,
            default_voice_path=rafael,
        )
        mock_hub.assert_not_called()


def test_ensure_pocket_models_downloads_missing_with_pinned_revisions(
    tmp_path: Path,
) -> None:
    """Missing files trigger hf_hub_download with the pinned revisions."""
    model = tmp_path / "model.safetensors"
    tokenizer = tmp_path / "tokenizer.model"
    rafael = tmp_path / "rafael.safetensors"

    def _fake_hub(**kwargs: object) -> Path:
        src = tmp_path / f"cache-{kwargs['filename'].split('/')[-1]}"
        src.write_bytes(b"content")
        return src

    calls: list[dict[str, object]] = []

    def _recording_hub(**kwargs: object) -> Path:
        calls.append(kwargs)
        return _fake_hub(**kwargs)

    with patch("comadre.download.hf_hub_download", side_effect=_recording_hub):
        ensure_pocket_models(
            language="portuguese",
            model_path=model,
            tokenizer_path=tokenizer,
            default_voice_path=rafael,
        )
    assert model.is_file() and tokenizer.is_file() and rafael.is_file()
    assert len(calls) == 3
    by_repo = {c["repo_id"]: c for c in calls}
    model_call = by_repo[_GATED_REPO]
    assert model_call["revision"] == _GATED_REVISION
    assert model_call["filename"] == "languages/portuguese/model.safetensors"
    assert by_repo[_PUBLIC_REPO]["revision"] in (
        _TOKENIZER_REVISION,
        _EMBEDDINGS_REVISION,
    )


def test_ensure_pocket_models_offline_fails_fast_when_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """HF_HUB_OFFLINE=1 + cache miss → FileNotFoundError with the
    run-once-with-HF_TOKEN message; the cache-only lookup is attempted."""
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    model = tmp_path / "model.safetensors"
    tokenizer = tmp_path / "tokenizer.model"
    rafael = tmp_path / "rafael.safetensors"
    with (
        patch(
            "comadre.download.hf_hub_download",
            side_effect=FileNotFoundError("cache miss"),
        ) as mock_hub,
        pytest.raises(FileNotFoundError, match="HF_HUB_OFFLINE"),
    ):
        ensure_pocket_models(
            language="portuguese",
            model_path=model,
            tokenizer_path=tokenizer,
            default_voice_path=rafael,
        )
    mock_hub.assert_called_once()
    assert mock_hub.call_args.kwargs["local_files_only"] is True
