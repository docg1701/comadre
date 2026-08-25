"""Audit 2026-08-25 F1 — every CLI-reachable logger writes to stderr.

``comadre-keys <cmd> --format json | jq`` breaks if any WARN from a
non-CLI component (keys.db, keys.auth) lands on stdout. The routing in
``comadre.keys.cli.__init__`` must cover all ``_CLI_LOG_COMPONENTS``.
"""

from __future__ import annotations

import logging
import sys

import comadre.keys.cli  # noqa: F401 — import triggers the stderr routing
from comadre.keys.cli import _CLI_LOG_COMPONENTS, _route_cli_loggers_to_stderr


def test_no_cli_component_logs_to_stdout() -> None:
    for name in _CLI_LOG_COMPONENTS:
        logger = logging.getLogger(name)
        assert logger.handlers, f"{name} has no handler after cli import"
        streams = [getattr(h, "stream", None) for h in logger.handlers]
        assert sys.stdout not in streams, f"{name} still writes to stdout"
        assert sys.stderr in streams, f"{name} does not write to stderr"


def test_routing_swaps_preexisting_stdout_handlers(monkeypatch) -> None:
    """If a component logger already carries a stdout handler (e.g. created
    by get_logger before the routing runs), routing replaces it."""
    for name in ("keys.cli", "keys.db", "keys.auth"):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.addHandler(logging.StreamHandler(sys.stdout))

    _route_cli_loggers_to_stderr()

    for name in _CLI_LOG_COMPONENTS:
        streams = [getattr(h, "stream", None) for h in logging.getLogger(name).handlers]
        assert sys.stdout not in streams
        assert sys.stderr in streams
