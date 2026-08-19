"""Tests for VoiceRegistry: scan, lazy state materialization, LRU,
ephemeral TTLs + quotas, create/delete ownership, and visibility rules."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from pydantic import SecretStr

from comadre import voice_storage
from comadre.config import Settings
from comadre.exceptions import VoiceDeleteError, VoiceLimitError, VoiceNotFoundError
from comadre.service import VoiceRegistry


def _settings(tmp_path: Path, fernet_key: str, **overrides: object) -> Settings:
    model_file = tmp_path / "model.safetensors"
    model_file.write_bytes(b"fake-model")
    return Settings(
        key_registry_encryption_key=SecretStr(fernet_key),
        pocket_model_path=str(model_file),
        pocket_default_voice_path=str(tmp_path / "no-rafael.safetensors"),
        **overrides,  # type: ignore[arg-type]
    )


def _make_engine() -> MagicMock:
    import torch

    engine = MagicMock()
    engine.is_loaded = True
    engine.get_state_for_audio_prompt.return_value = {"flow": {"k": torch.zeros(1)}}
    return engine


def _rescan(registry: VoiceRegistry, pocket_dir: Path) -> None:
    """Re-scan the filesystem into the registry (new files were added)."""
    registry._files.clear()
    for entry in voice_storage.scan_entries(pocket_dir):
        registry._files[entry.name] = entry


def _add_wav(
    pocket_dir: Path, name: str, *, meta: dict[str, object] | None = None
) -> None:
    pocket_dir.mkdir(parents=True, exist_ok=True)
    (pocket_dir / f"{name}.wav").write_bytes(b"fake-wav")
    if meta is not None:
        voice_storage.write_meta(pocket_dir, name, **meta)


@pytest.fixture()
def registry_env(
    tmp_path: Path, fernet_key: str
) -> tuple[VoiceRegistry, Path, Settings]:
    settings = _settings(tmp_path, fernet_key)
    engine = _make_engine()
    registry = VoiceRegistry(engine, tmp_path, settings)  # type: ignore[arg-type]
    return registry, tmp_path / "pocket", settings


def test_scan_and_available_voices(
    registry_env: tuple[VoiceRegistry, Path, Settings],
) -> None:
    """Filesystem .wav entries surface sorted with the pocket/ prefix;
    invalid names (u_ non-ULID, traversal) are skipped."""
    registry, pocket_dir, _ = registry_env
    _add_wav(pocket_dir, "galvani")
    _add_wav(pocket_dir, "ana")
    _add_wav(pocket_dir, "bad..name")
    (pocket_dir / "u_not_ulid.wav").write_bytes(b"x")
    _rescan(registry, pocket_dir)
    assert registry.available_voices() == ["pocket/ana", "pocket/galvani"]


def test_resolve_loads_state_from_safetensors(
    registry_env: tuple[VoiceRegistry, Path, Settings],
) -> None:
    """A state file whose meta model_hash matches loads directly."""
    registry, pocket_dir, _settings = registry_env
    _add_wav(pocket_dir, "galvani", meta={"model_hash": registry.model_hash})
    (pocket_dir / "galvani.safetensors").write_bytes(b"state")
    _rescan(registry, pocket_dir)
    state = registry.resolve("galvani")
    assert state is registry._engine.get_state_for_audio_prompt.return_value
    registry._engine.get_state_for_audio_prompt.assert_called_once_with(
        pocket_dir / "galvani.safetensors"
    )


def test_lazy_materialization_from_wav_persists_state_and_meta(
    registry_env: tuple[VoiceRegistry, Path, Settings],
) -> None:
    """wav-only entries encode on first resolve; the .safetensors + .json
    land on disk with the current model_hash."""
    registry, pocket_dir, _settings = registry_env
    _add_wav(pocket_dir, "galvani")
    _rescan(registry, pocket_dir)
    with patch("comadre.service._audio_duration_seconds", return_value=6.0):
        state = registry.resolve("galvani")
    assert state is registry._engine.get_state_for_audio_prompt.return_value
    registry._engine.get_state_for_audio_prompt.assert_called_once_with(
        pocket_dir / "galvani.wav", truncate=True
    )
    assert (pocket_dir / "galvani.safetensors").is_file()
    meta = voice_storage.read_meta(pocket_dir, "galvani")
    assert meta["model_hash"] == registry.model_hash
    assert meta["ref_duration_s"] == 6.0


def test_model_hash_mismatch_reencodes_from_wav(
    registry_env: tuple[VoiceRegistry, Path, Settings],
) -> None:
    """A stale model_hash in meta forces re-encoding from the reference
    wav instead of loading the outdated state."""
    registry, pocket_dir, _settings = registry_env
    _add_wav(pocket_dir, "galvani", meta={"model_hash": "stale-hash"})
    _rescan(registry, pocket_dir)
    (pocket_dir / "galvani.safetensors").write_bytes(b"old-state")
    with patch("comadre.service._audio_duration_seconds", return_value=5.0):
        registry.resolve("galvani")
    registry._engine.get_state_for_audio_prompt.assert_called_once_with(
        pocket_dir / "galvani.wav", truncate=True
    )
    assert (
        voice_storage.read_meta(pocket_dir, "galvani")["model_hash"]
        == registry.model_hash
    )


def test_lru_cap_16(registry_env: tuple[VoiceRegistry, Path, Settings]) -> None:
    """The loaded-state LRU holds at most 16 entries; the oldest leave."""
    registry, pocket_dir, _settings = registry_env
    for i in range(20):
        _add_wav(pocket_dir, f"v{i}", meta={"model_hash": registry.model_hash})
    _rescan(registry, pocket_dir)
    for i in range(20):
        registry.resolve(f"v{i}")
    assert len(registry._loaded) == 16
    assert "v0" not in registry._loaded
    assert "v19" in registry._loaded


def test_ephemeral_ttl_sweep_idle_and_absolute(
    registry_env: tuple[VoiceRegistry, Path, Settings],
) -> None:
    """Idle TTL and absolute TTL both evict; a fresh voice survives."""
    registry, _pocket_dir, _settings = registry_env
    with patch("comadre.service._audio_duration_seconds", return_value=5.0):
        registry.create_from_upload(
            Path("fake.wav"),
            key_id="key1",
            customer_id="cust_a",
            display_name=None,
            persist=False,
        )
    assert registry._ephemeral["key1"]
    # Age the idle timestamp past the idle TTL.
    voice = next(iter(registry._ephemeral["key1"].values()))
    voice.last_used_at = datetime.now(UTC) - timedelta(seconds=99999)
    registry._sweep_ephemerals()
    assert registry._ephemeral.get("key1", {}) == {}


def test_ephemeral_per_key_max(
    registry_env: tuple[VoiceRegistry, Path, Settings],
) -> None:
    """A 6th ephemeral for the same key raises VoiceLimitError."""
    registry, _pocket_dir, _settings = registry_env
    with patch("comadre.service._audio_duration_seconds", return_value=5.0):
        for _ in range(5):
            registry.create_from_upload(
                Path("fake.wav"),
                key_id="key1",
                customer_id="cust_a",
                display_name=None,
                persist=False,
            )
        with pytest.raises(VoiceLimitError):
            registry.create_from_upload(
                Path("fake.wav"),
                key_id="key1",
                customer_id="cust_a",
                display_name=None,
                persist=False,
            )


def test_ephemeral_global_lru_cap_evicts_oldest(
    tmp_path: Path,
    fernet_key: str,
) -> None:
    """Cross-key global cap evicts the least-recently-used ephemeral."""
    settings = _settings(tmp_path, fernet_key, voice_ephemeral_global_max=3)
    registry = VoiceRegistry(_make_engine(), tmp_path, settings)  # type: ignore[arg-type]
    with patch("comadre.service._audio_duration_seconds", return_value=5.0):
        for i in range(4):
            registry.create_from_upload(
                Path("fake.wav"),
                key_id=f"key{i}",
                customer_id="cust_a",
                display_name=None,
                persist=False,
            )
    total = sum(len(v) for v in registry._ephemeral.values())
    assert total == 3
    assert "key0" not in registry._ephemeral  # oldest evicted


def test_persisted_create_writes_trio_and_stored_quota(
    registry_env: tuple[VoiceRegistry, Path, Settings],
) -> None:
    """persist=True writes .wav/.safetensors/.json and registers in the
    filesystem map; exceeding VOICE_STORED_MAX_PER_CUSTOMER raises."""
    registry, pocket_dir, settings = registry_env
    src = pocket_dir.parent / "upload.wav"
    src.write_bytes(b"wav-bytes")
    with patch("comadre.service._audio_duration_seconds", return_value=5.0):
        info = registry.create_from_upload(
            src,
            key_id="key1",
            customer_id="cust_a",
            display_name="Minha voz",
            persist=True,
        )
    assert info.persisted is True
    assert info.voice.startswith("pocket/u_")
    name = info.voice.removeprefix("pocket/")
    assert (pocket_dir / f"{name}.wav").is_file()
    assert (pocket_dir / f"{name}.safetensors").is_file()
    assert voice_storage.read_meta(pocket_dir, name)["customer_id"] == "cust_a"

    # Quota: cap at 1 stored clone.
    limited = Settings(
        key_registry_encryption_key=settings.key_registry_encryption_key,
        pocket_model_path=settings.pocket_model_path,
        pocket_default_voice_path=settings.pocket_default_voice_path,
        voice_stored_max_per_customer=1,
    )
    registry._settings = limited
    with (
        patch("comadre.service._audio_duration_seconds", return_value=5.0),
        pytest.raises(VoiceLimitError, match="Stored voice quota"),
    ):
        registry.create_from_upload(
            src,
            key_id="key1",
            customer_id="cust_a",
            display_name=None,
            persist=True,
        )


def test_delete_own_only(registry_env: tuple[VoiceRegistry, Path, Settings]) -> None:
    """Stored clones delete only by their customer; operator voices and
    foreign clones raise; ephemeral delete is key-scoped."""
    registry, pocket_dir, _settings = registry_env
    _add_wav(pocket_dir, "operadora")  # operator voice: no customer_id
    _rescan(registry, pocket_dir)
    src = pocket_dir.parent / "upload.wav"
    src.write_bytes(b"wav-bytes")
    with patch("comadre.service._audio_duration_seconds", return_value=5.0):
        info = registry.create_from_upload(
            src,
            key_id="key1",
            customer_id="cust_a",
            display_name=None,
            persist=True,
        )
    name = info.voice.removeprefix("pocket/")

    with pytest.raises(VoiceDeleteError):
        registry.delete(name, key_id="keyX", customer_id="cust_b")
    with pytest.raises(VoiceDeleteError):
        registry.delete("operadora", key_id="key1", customer_id="cust_a")

    registry.delete(name, key_id="key1", customer_id="cust_a")
    assert not (pocket_dir / f"{name}.wav").exists()
    with pytest.raises(VoiceNotFoundError):
        registry.delete(name, key_id="key1", customer_id="cust_a")


def test_list_for_visibility_rules(
    registry_env: tuple[VoiceRegistry, Path, Settings],
) -> None:
    """Operator voices visible to everyone; a customer sees only their
    own stored clones + their own keys ephemeral clones."""
    registry, pocket_dir, _settings = registry_env
    _add_wav(pocket_dir, "operadora", meta={"display_name": "Operadora"})
    _rescan(registry, pocket_dir)
    src = pocket_dir.parent / "upload.wav"
    src.write_bytes(b"wav-bytes")
    with patch("comadre.service._audio_duration_seconds", return_value=5.0):
        stored_a = registry.create_from_upload(
            src,
            key_id="key1",
            customer_id="cust_a",
            display_name="Voz A",
            persist=True,
        )
        stored_b = registry.create_from_upload(
            src,
            key_id="key2",
            customer_id="cust_b",
            display_name="Voz B",
            persist=True,
        )
        eph_a = registry.create_from_upload(
            src,
            key_id="key1",
            customer_id="cust_a",
            display_name=None,
            persist=False,
        )

    voices_a = {v.voice for v in registry.list_for(key_id="key1", customer_id="cust_a")}
    assert "pocket/operadora" in voices_a
    assert stored_a.voice in voices_a
    assert eph_a.voice in voices_a
    assert stored_b.voice not in voices_a

    voices_b = {v.voice for v in registry.list_for(key_id="key2", customer_id="cust_b")}
    assert stored_b.voice in voices_b
    assert stored_a.voice not in voices_b
    assert eph_a.voice not in voices_b


def test_voice_storage_delete_by_customer_purges_only_that_customer(
    tmp_path: Path,
) -> None:
    """LGPD purge deletes only the target customer stored clones;
    operator voices survive."""
    pocket_dir = tmp_path / "pocket"
    for name, cust in (("a1", "cust_a"), ("a2", "cust_a"), ("b1", "cust_b")):
        _add_wav(pocket_dir, name, meta={"customer_id": cust})
    _add_wav(pocket_dir, "operadora")
    deleted = voice_storage.delete_by_customer(pocket_dir, "cust_a")
    assert deleted == 2
    assert voice_storage.count_by_customer(pocket_dir, "cust_a") == 0
    assert voice_storage.count_by_customer(pocket_dir, "cust_b") == 1
    assert (pocket_dir / "operadora.wav").is_file()
