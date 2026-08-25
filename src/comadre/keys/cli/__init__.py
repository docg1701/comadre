"""comadre-keys CLI entry points (Typer app + rendering helpers).

Structured CLI logs must travel on stderr so that stdout stays
machine-parseable — ``comadre-keys list-keys --format json | jq`` would
otherwise see the log line and fail. ``get_logger()`` attaches a per-component
stdout handler, so EVERY ``keys.*`` component a command can emit needs its own
stderr handler here; routing only ``keys.cli`` left WARN lines from
``keys.db``/``keys.auth`` polluting JSON output (audit 2026-08-25, F1).
This module is imported before any command module, so pre-creating handlers
here means ``get_logger()`` later finds them already in place.
"""

from __future__ import annotations

import logging
import sys

from comadre.logging import PipeFormatter

# Every get_logger() component reachable from a CLI code path. When adding a
# new keys.* component, register it here or its logs go to stdout again.
_CLI_LOG_COMPONENTS = ("keys.cli", "keys.db", "keys.auth")


def _route_cli_loggers_to_stderr() -> None:
    for name in _CLI_LOG_COMPONENTS:
        logger = logging.getLogger(name)
        # Drop any handler that writes to stdout — it would pollute JSON output.
        for existing in list(logger.handlers):
            stream = getattr(existing, "stream", None)
            if stream is sys.stdout:
                logger.removeHandler(existing)
        if not logger.handlers:
            handler = logging.StreamHandler(sys.stderr)
            handler.setFormatter(PipeFormatter())
            logger.addHandler(handler)
            logger.setLevel(logging.INFO)
            logger.propagate = False


_route_cli_loggers_to_stderr()
