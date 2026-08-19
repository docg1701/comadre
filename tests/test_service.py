"""Tests for the pocket-tts engine service.

Covers: preprocess chain (normalize + sigla spacing), validation
(format/empty/limit), copy_state=True semantics, raw bypass,
GenerationError on model failure, the ffmpeg pipeline with atempo
chains, and voice-name parse rules (traversal rejection, u_ ULID shape).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from comadre.exceptions import GenerationError, InvalidRequestError
from comadre.service import (
    PocketEngine,
    VoiceRegistry,
    _apply_pipeline,
    _atempo_chain,
    _parse_voice,
)


def _fake_state() -> dict[str, dict[str, object]]:
    import torch

    return {"flow": {"k": torch.zeros(2)}}


@pytest.fixture()
def engine() -> PocketEngine:
    """PocketEngine with mocked TTSModel inference + registry."""
    svc = PocketEngine()
    import torch

    mock_model = MagicMock()
    mock_model.sample_rate = 24000
    mock_model.generate_audio.return_value = torch.zeros(1, 24000)
    mock_model.get_state_for_audio_prompt.return_value = _fake_state()
    svc._model = mock_model

    mock_registry = MagicMock()
    mock_registry.resolve.return_value = _fake_state()
    svc.attach_registry(mock_registry)  # type: ignore[arg-type]
    return svc


def test_generate_speech_applies_normalize_and_sigla_spacing(
    engine: PocketEngine,
) -> None:
    """normalize_text + expand_siglas run before generation;
    copy_state=True reaches the model call."""
    with patch("comadre.service._apply_pipeline", return_value=b"processed"):
        result = engine.generate_speech(
            "CNPJ 21/03/2026", "pocket/rafael", "wav", speed=1.0
        )
    assert result == b"processed"
    mock_model = engine._model
    mock_model.generate_audio.assert_called_once()  # type: ignore[union-attr]
    args, kwargs = mock_model.generate_audio.call_args  # type: ignore[union-attr]
    assert kwargs["copy_state"] is True
    text = args[1]
    assert "C N P J" in text  # sigla spaced
    assert "vinte e um" in text  # date normalized


def test_generate_speech_sigla_spacing_off(engine: PocketEngine) -> None:
    """POCKET_SIGLA_SPACING=false skips expand_siglas."""
    engine._sigla_spacing = False
    with patch("comadre.service._apply_pipeline", return_value=b"x"):
        engine.generate_speech("CNPJ", "pocket/rafael", "wav")
    text = engine._model.generate_audio.call_args.args[1]  # type: ignore[union-attr]
    assert "CNPJ" in text and "C N P J" not in text


def test_generate_speech_raw_bypasses_pipeline(engine: PocketEngine) -> None:
    """raw=True skips _apply_pipeline and uses _encode_final."""
    with (
        patch("comadre.service._encode_final", return_value=b"raw") as mock_enc,
        patch("comadre.service._apply_pipeline") as mock_pipeline,
    ):
        result = engine.generate_speech("oi", "pocket/rafael", "ogg", raw=True)
    assert result == b"raw"
    mock_enc.assert_called_once()
    mock_pipeline.assert_not_called()


def test_generate_speech_rejects_oversize_empty_and_unsupported_format(
    engine: PocketEngine,
) -> None:
    """Pre-call validation: oversize text, empty/whitespace, and
    unsupported formats all raise InvalidRequestError BEFORE the model;
    the model is never asked to render input that would 4xx anyway."""
    too_long = "a" * (PocketEngine.CHAR_LIMIT + 1)
    with pytest.raises(InvalidRequestError) as exc_info:
        engine.generate_speech(too_long, "pocket/rafael", "wav")
    assert str(PocketEngine.CHAR_LIMIT) in exc_info.value.message
    assert exc_info.value.status_code == 400

    for bad in ("", "   "):
        with pytest.raises(InvalidRequestError):
            engine.generate_speech(bad, "pocket/rafael", "wav")

    # mp3 → 400 (only wav and ogg are supported).
    with pytest.raises(InvalidRequestError):
        engine.generate_speech("hello", "pocket/rafael", "mp3")

    engine._model.generate_audio.assert_not_called()  # type: ignore[union-attr]


def test_generate_speech_model_failure_becomes_generation_error(
    engine: PocketEngine,
) -> None:
    """A model RuntimeError surfaces as GenerationError (500 shape)."""
    engine._model.generate_audio.side_effect = RuntimeError("boom")  # type: ignore[union-attr]
    with pytest.raises(GenerationError, match="boom"):
        engine.generate_speech("oi", "pocket/rafael", "wav")


def test_generate_speech_model_not_loaded_raises_generation_error() -> None:
    """A clean GenerationError beats an opaque AttributeError on None."""
    svc = PocketEngine()
    assert not svc.is_loaded
    with pytest.raises(GenerationError, match="Model not loaded"):
        svc.generate_speech("hello", "pocket/rafael", "wav")


def test_parse_voice_rejects_traversal_and_bad_shapes() -> None:
    """Security: voice names must NOT allow path traversal / special
    chars; malformed shapes are rejected at the parse layer."""
    for hostile in (
        "pocket/../etc/passwd",
        "pocket/voice.wav",
        "pocket/x/y",
        "rafael",
        "pocket/",
        "chatterbox/voice",
        "qwen/voice",
        "kokoro/voice",
    ):
        with pytest.raises(InvalidRequestError):
            _parse_voice(hostile)


def test_parse_voice_accepts_operator_and_upload_shapes() -> None:
    """Operator names + u_<ULID> shapes parse; u_ is reserved."""
    assert _parse_voice("pocket/my-voice_01") == "my-voice_01"
    from ulid import ULID

    ulid_name = f"u_{ULID()}"
    assert _parse_voice(f"pocket/{ulid_name}") == ulid_name
    with pytest.raises(InvalidRequestError):
        _parse_voice("pocket/u_not-a-ulid")


def test_atempo_chain_decomposes_speeds_into_valid_factors() -> None:
    """0.25/0.5/2.0/4.0 decompose into chains of atempo factors in
    [0.5, 2.0]; 1.0 yields no filter."""
    assert _atempo_chain(1.0) == ""
    assert _atempo_chain(0.25) == "atempo=0.5,atempo=0.5"
    assert _atempo_chain(4.0) == "atempo=2.0,atempo=2.0"
    assert _atempo_chain(0.5) == "atempo=0.5"
    assert _atempo_chain(2.0) == "atempo=2.0"
    for speed in (0.25, 0.3, 0.5, 1.0, 1.5, 2.0, 3.0, 4.0):
        chain = _atempo_chain(speed)
        if speed == 1.0:
            assert chain == ""
            continue
        factors = [float(part.split("=")[1]) for part in chain.split(",")]
        assert all(0.5 <= f <= 2.0 for f in factors)
        product = 1.0
        for f in factors:
            product *= f
        assert abs(product - speed) < 1e-3


def test_apply_pipeline_appends_atempo_chain() -> None:
    """The atempo chain lands in the stage-1 ffmpeg filter for
    speed != 1.0; speed == 1.0 keeps the radio_warm base chain."""
    fake_wav = b"RIFF-fake-wav"
    with patch("comadre.service.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout=b"processed")
        with (
            patch("comadre.service._apply_noise_and_encode", return_value=b"out"),
            patch("comadre.service._encode_final", return_value=b"out"),
        ):
            _apply_pipeline(fake_wav, "wav", None, speed=1.5)
    args = mock_run.call_args[0][0]
    filter_arg = args[args.index("-af") + 1]
    assert "atempo=1.5" in filter_arg
    assert "highpass=f=100" in filter_arg  # base chain preserved
    assert "loudnorm=I=-16:TP=-1:LRA=4" in filter_arg


def test_apply_pipeline_speed_one_has_no_atempo() -> None:
    """speed == 1.0 → no atempo segment in the filter."""
    fake_wav = b"RIFF-fake-wav"
    with patch("comadre.service.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout=b"processed")
        with (
            patch("comadre.service._apply_noise_and_encode", return_value=b"out"),
            patch("comadre.service._encode_final", return_value=b"out"),
        ):
            _apply_pipeline(fake_wav, "wav", None, speed=1.0)
    args = mock_run.call_args[0][0]
    filter_arg = args[args.index("-af") + 1]
    assert "atempo" not in filter_arg


def test_voice_registry_smoke_constructs_from_empty_dir(
    tmp_path,
    fernet_key: str,
) -> None:
    """VoiceRegistry builds from an empty pocket dir with the rafael
    virtual entry missing (no default voice file) without crashing."""
    from pydantic import SecretStr

    from comadre.config import Settings

    model_file = tmp_path / "model.safetensors"
    model_file.write_bytes(b"model")
    settings = Settings(
        key_registry_encryption_key=SecretStr(fernet_key),
        pocket_model_path=str(model_file),
        pocket_default_voice_path=str(tmp_path / "rafael.safetensors"),
    )
    mock_engine = MagicMock()
    mock_engine.is_loaded = True
    registry = VoiceRegistry(mock_engine, tmp_path, settings)  # type: ignore[arg-type]
    assert registry.available_voices() == []
    assert registry.engine_status()["pocket"]["loaded"] is True
