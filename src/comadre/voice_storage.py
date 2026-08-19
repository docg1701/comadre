"""Pure filesystem operations for /voices/pocket/ artifacts.

No model, no HTTP, no business logic — used by both the API-side
VoiceRegistry (service.py) and the comadre-keys CLI LGPD verbs
(export-customer voice listing, delete-customer --hard voice purge).
Path names are built only from validated voice names (operator RE or
u_<ULID> shape) — the whitelists exclude separators, so path traversal
is impossible by construction.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

# Operator voice names: alphanumeric, hyphens, underscores.
_OPERATOR_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]+$")
# API uploads: u_ prefix + 26-char Crockford base32 ULID.
_UPLOAD_NAME_RE = re.compile(r"^u_[0-9A-HJKMNP-TV-Z]{26}$")


@dataclass(frozen=True, slots=True)
class VoiceFileEntry:
    """One voice on the filesystem: reference WAV + optional state/meta.

    Meta keys: display_name, customer_id, key_id, created_at (ISO 8601
    UTC), ref_duration_s, model_hash. Operator-provisioned voices carry
    no customer_id / key_id (they are not owned by any customer).
    """

    name: str
    ref_path: Path
    state_path: Path
    meta: dict[str, object]


def is_valid_voice_name(name: str) -> bool:
    """Return True when name is a safe pocket voice name (no traversal).

    The ``u_`` prefix is reserved for API uploads (u_<ULID>); operator
    names must not use it — u_-prefixed names that are not ULIDs are
    rejected so stray operator files can never shadow clones.
    """
    if _UPLOAD_NAME_RE.match(name):
        return True
    if name.startswith("u_"):
        return False
    return bool(_OPERATOR_NAME_RE.match(name))


def _meta_path(pocket_dir: Path, name: str) -> Path:
    return pocket_dir / f"{name}.json"


def read_meta(pocket_dir: Path, name: str) -> dict[str, object]:
    """Read <name>.json; missing/corrupt/non-dict yields {}."""
    try:
        raw = json.loads(_meta_path(pocket_dir, name).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def write_meta(pocket_dir: Path, name: str, **fields: object) -> None:
    """Merge fields into <name>.json, preserving existing keys."""
    meta = read_meta(pocket_dir, name)
    meta.update(fields)
    pocket_dir.mkdir(parents=True, exist_ok=True)
    tmp = _meta_path(pocket_dir, name).with_suffix(".json.tmp")
    tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(_meta_path(pocket_dir, name))


def scan_entries(pocket_dir: Path) -> list[VoiceFileEntry]:
    """Scan /voices/pocket for <name>.wav (+ optional .safetensors/.json)."""
    if not pocket_dir.is_dir():
        return []
    entries: list[VoiceFileEntry] = []
    for ref in sorted(pocket_dir.glob("*.wav")):
        name = ref.stem
        if not is_valid_voice_name(name):
            continue
        entries.append(
            VoiceFileEntry(
                name=name,
                ref_path=ref,
                state_path=pocket_dir / f"{name}.safetensors",
                meta=read_meta(pocket_dir, name),
            )
        )
    return entries


def delete_entries(pocket_dir: Path, name: str) -> bool:
    """Delete .wav/.safetensors/.json for a name; True when any existed."""
    paths = [
        pocket_dir / f"{name}{suffix}" for suffix in (".wav", ".safetensors", ".json")
    ]
    existed = any(p.is_file() for p in paths)
    for p in paths:
        p.unlink(missing_ok=True)
    return existed


def _customer_entries(pocket_dir: Path, customer_id: str) -> list[VoiceFileEntry]:
    return [
        e for e in scan_entries(pocket_dir) if e.meta.get("customer_id") == customer_id
    ]


def count_by_customer(pocket_dir: Path, customer_id: str) -> int:
    """Number of stored clones owned by customer_id."""
    return len(_customer_entries(pocket_dir, customer_id))


def list_for_customer(pocket_dir: Path, customer_id: str) -> list[VoiceFileEntry]:
    """Stored clones owned by customer_id (LGPD export surface)."""
    return _customer_entries(pocket_dir, customer_id)


def delete_by_customer(pocket_dir: Path, customer_id: str) -> int:
    """Purge every stored clone owned by customer_id; returns count.

    Operator-provisioned voices (no customer_id meta) are never touched.
    """
    entries = _customer_entries(pocket_dir, customer_id)
    for entry in entries:
        delete_entries(pocket_dir, entry.name)
    return len(entries)
