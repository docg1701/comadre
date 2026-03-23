"""Shared pytest configuration and marker registration."""

import pytest


def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers."""
    config.addinivalue_line(
        "markers", "slow: marks tests requiring real model inference"
    )
