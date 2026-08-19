"""Slow integration tests for the real pocket-tts model.

Run with: uv run pytest -m slow
Skip when the model files are absent (local dev without download).
"""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np
import pytest
from pocket_tts import TTSModel, export_model_state

pytestmark = pytest.mark.slow


def _wav_file(path: Path, seconds: int = 5, sample_rate: int = 24000) -> Path:
    frames = seconds * sample_rate
    samples = np.sin(2 * np.pi * 220 * np.arange(frames) / sample_rate) * 0.3
    int16_samples = (np.clip(samples, -1.0, 1.0) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(int16_samples.tobytes())
    return path


def _model_files_present() -> bool:
    return all(
        Path(p).is_file()
        for p in (
            "models/pocket-tts/portuguese/model.safetensors",
            "models/pocket-tts/portuguese/tokenizer.model",
            "models/pocket-tts/portuguese/embeddings/rafael.safetensors",
            "models/pocket-tts-config/portuguese.yaml",
        )
    )


@pytest.fixture(scope="module")
def model() -> TTSModel:
    if not _model_files_present():
        pytest.skip("pocket-tts model files not present")
    return TTSModel.load_model(config="models/pocket-tts-config/portuguese.yaml")


def test_generate_audio_non_silent(model: TTSModel) -> None:
    """rafael state + generate_audio yields non-silent 24 kHz audio."""
    state = model.get_state_for_audio_prompt(
        "models/pocket-tts/portuguese/embeddings/rafael.safetensors"
    )
    audio = model.generate_audio(state, "Olá, este é um teste de voz.", copy_state=True)
    assert audio.shape[0] == 1  # mono
    assert model.sample_rate == 24000
    samples = audio.numpy().reshape(-1)
    assert samples.size > 0
    assert float(np.abs(samples).max()) > 1e-4  # non-silent


def test_clone_export_import_roundtrip(model: TTSModel, tmp_path: Path) -> None:
    """A 5 s reference encodes into a state; export → safetensors → import
    reproduces a usable state for generation."""
    ref = _wav_file(tmp_path / "ref.wav", seconds=5)
    state = model.get_state_for_audio_prompt(ref, truncate=True)
    export_path = tmp_path / "clone.safetensors"
    export_model_state(state, export_path)
    assert export_path.stat().st_size > 0

    imported = model.get_state_for_audio_prompt(export_path)
    audio = model.generate_audio(imported, "Olá.", copy_state=True)
    assert float(np.abs(audio.numpy()).max()) > 1e-4
