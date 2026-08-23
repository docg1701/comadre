"""Single-source-of-truth guard: package metadata version == pyproject.

Regression guard: v3.0.4 shipped with /health reporting 3.0.3 because
``__init__.py`` carried a hardcoded copy that the release bump missed.
``__version__`` now derives from installed metadata, which uv sync
generates from pyproject — this test fails if that ever drifts again.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import comadre


def test_version_matches_pyproject() -> None:
    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    declared = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"][
        "version"
    ]
    assert comadre.__version__ == declared
