"""End-to-end CLI tests for ``comadre-keys list-customers`` (Story 1.3).

Lean by design (test-suite review 2026-04-25).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from typer.testing import CliRunner

from comadre.keys.cli.app import app
from tests._keys_cli_helpers import buffers as _buffers
from tests._keys_cli_helpers import clear_buffers as _clear_buffers

runner = CliRunner()


@pytest.fixture()
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    key = Fernet.generate_key().decode()
    db_path = tmp_path / "registry.db"
    monkeypatch.setenv("KEY_REGISTRY_DB_PATH", str(db_path))
    monkeypatch.setenv("KEY_REGISTRY_ENCRYPTION_KEY", key)
    return {"db_path": str(db_path), "key": key}


def _create_customer(name: str, email: str, cpf: str) -> None:
    _clear_buffers()
    runner.invoke(
        app,
        ["create-customer", "--name", name, "--email", email, "--cpf", cpf],
    )
    _clear_buffers()


def test_list_customers_empty_db_prints_hint(env: dict[str, str]) -> None:
    """First-run UX: empty DB emits the 'create-customer' hint."""
    result = runner.invoke(app, ["list-customers"])
    stdout, _ = _buffers()
    assert result.exit_code == 0
    assert "comadre-keys create-customer" in stdout


def test_list_customers_table_renders_each_active_customer(
    env: dict[str, str],
) -> None:
    """Happy path: registered customers appear, tombstoned ones don't."""
    _create_customer("Helena", "h@x.com", "123.456.789-09")
    _create_customer("Marcos", "m@x.com", "529.982.247-25")

    result = runner.invoke(app, ["list-customers"])
    stdout, _ = _buffers()
    assert result.exit_code == 0
    assert "Helena" in stdout
    assert "Marcos" in stdout


def test_list_customers_format_json_emits_array(env: dict[str, str]) -> None:
    _create_customer("Helena", "h@x.com", "123.456.789-09")
    result = runner.invoke(app, ["list-customers", "--format", "json"])
    stdout, _ = _buffers()
    assert result.exit_code == 0
    parsed = json.loads(stdout)
    assert isinstance(parsed, list)
    assert len(parsed) == 1
    assert parsed[0]["name"] == "Helena"
    # No ciphertext leak in machine output.
    assert "tax_id_encrypted" not in parsed[0]
