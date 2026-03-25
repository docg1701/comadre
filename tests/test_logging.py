"""Tests for the structured logging module."""

import logging
import re
from io import StringIO

import pytest

from comadre.logging import PipeFormatter, get_logger, setup_logging

ISO8601_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
ANSI_ESCAPE_PATTERN = re.compile(r"\x1b\[")
PIPE_FORMAT_PATTERN = re.compile(r".+\s\|\s.+\s\|\s.+\s\|\s.+")


@pytest.fixture(autouse=True)
def _cleanup_loggers() -> None:
    """Remove test loggers after each test to avoid handler accumulation."""
    yield  # type: ignore[misc]
    manager = logging.Logger.manager
    for name in list(manager.loggerDict):
        logger = manager.loggerDict.get(name)
        if isinstance(logger, logging.Logger):
            logger.handlers.clear()
            logger.setLevel(logging.NOTSET)
            logger.propagate = True


def _capture_log_output(logger: logging.Logger, level: int, message: str) -> str:
    """Capture log output from a logger into a string."""
    buffer = StringIO()
    handler = logging.StreamHandler(buffer)
    handler.setFormatter(PipeFormatter())
    logger.addHandler(handler)
    logger.setLevel(level)
    logger.log(level, message)
    logger.removeHandler(handler)
    return buffer.getvalue().strip()


class TestPipeFormatter:
    """Tests for the PipeFormatter class."""

    def test_format_matches_pipe_pattern(self) -> None:
        record = logging.LogRecord(
            name="startup",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Server starting",
            args=(),
            exc_info=None,
        )
        formatter = PipeFormatter()
        output = formatter.format(record)

        assert PIPE_FORMAT_PATTERN.match(output)

    def test_timestamp_is_iso8601_utc(self) -> None:
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="test message",
            args=(),
            exc_info=None,
        )
        formatter = PipeFormatter()
        output = formatter.format(record)
        timestamp = output.split(" | ")[0]

        assert ISO8601_PATTERN.match(timestamp)
        assert timestamp.endswith("Z")

    @pytest.mark.parametrize(
        ("level", "expected_label"),
        [
            (logging.DEBUG, "DEBUG"),
            (logging.INFO, "INFO "),
            (logging.WARNING, "WARN "),
            (logging.ERROR, "ERROR"),
            (logging.CRITICAL, "CRIT "),
        ],
    )
    def test_fixed_width_level_formatting(
        self, level: int, expected_label: str
    ) -> None:
        record = logging.LogRecord(
            name="test",
            level=level,
            pathname="",
            lineno=0,
            msg="test",
            args=(),
            exc_info=None,
        )
        formatter = PipeFormatter()
        output = formatter.format(record)
        level_field = output.split(" | ")[1]

        assert level_field == expected_label
        assert len(level_field) == 5

    def test_no_ansi_escape_codes(self) -> None:
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="colored output test",
            args=(),
            exc_info=None,
        )
        formatter = PipeFormatter()
        output = formatter.format(record)

        assert not ANSI_ESCAPE_PATTERN.search(output)

    def test_exception_info_included(self) -> None:
        try:
            raise ValueError("boom")
        except ValueError:
            import sys

            exc_info = sys.exc_info()
        record = logging.LogRecord(
            name="test",
            level=logging.ERROR,
            pathname="",
            lineno=0,
            msg="something failed",
            args=(),
            exc_info=exc_info,
        )
        formatter = PipeFormatter()
        output = formatter.format(record)

        assert "something failed" in output
        assert "ValueError: boom" in output
        assert "Traceback" in output

    def test_component_appears_in_output(self) -> None:
        record = logging.LogRecord(
            name="startup",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Loading model",
            args=(),
            exc_info=None,
        )
        formatter = PipeFormatter()
        output = formatter.format(record)
        component = output.split(" | ")[2]

        assert component == "startup"


class TestGetLogger:
    """Tests for the get_logger function."""

    def test_returns_logger_with_correct_name(self) -> None:
        logger = get_logger("startup")
        assert logger.name == "startup"

    def test_logger_has_pipe_formatter(self) -> None:
        logger = get_logger("request")
        assert len(logger.handlers) > 0
        assert isinstance(logger.handlers[0].formatter, PipeFormatter)

    def test_logger_output_format(self) -> None:
        logger = get_logger("health")
        output = _capture_log_output(logger, logging.INFO, "Health check passed")

        assert PIPE_FORMAT_PATTERN.match(output)
        parts = output.split(" | ")
        assert len(parts) == 4
        assert parts[2] == "health"
        assert parts[3] == "Health check passed"

    def test_no_duplicate_handlers_on_repeated_calls(self) -> None:
        logger_name = "no_dup_test"
        logger1 = get_logger(logger_name)
        handler_count = len(logger1.handlers)
        logger2 = get_logger(logger_name)

        assert logger1 is logger2
        assert len(logger2.handlers) == handler_count

    def test_propagate_is_false(self) -> None:
        logger = get_logger("voice")
        assert logger.propagate is False


class TestSetupLogging:
    """Tests for the setup_logging function."""

    @pytest.fixture(autouse=True)
    def _save_root_logger(self) -> None:  # type: ignore[misc]
        """Save and restore root logger state around each test."""
        root = logging.getLogger()
        original_level = root.level
        original_handlers = root.handlers[:]
        yield
        root.handlers = original_handlers
        root.setLevel(original_level)

    def test_configures_root_logger(self) -> None:
        root = logging.getLogger()
        root.handlers.clear()

        setup_logging(level=logging.DEBUG)

        assert root.level == logging.DEBUG
        assert len(root.handlers) > 0
        assert isinstance(root.handlers[0].formatter, PipeFormatter)

    def test_no_duplicate_handlers_on_repeated_calls(self) -> None:
        root = logging.getLogger()
        root.handlers.clear()

        setup_logging()
        handler_count = len(root.handlers)
        setup_logging()

        assert len(root.handlers) == handler_count
