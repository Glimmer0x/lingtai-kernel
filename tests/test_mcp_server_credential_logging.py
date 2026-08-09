"""Regression tests for #812: curated MCP stderr must not leak Telegram bot credentials.

The shared ``lingtai.mcp_servers._entrypoint`` logging setup is the single
place every curated MCP server configures stderr logging. These tests pin:

- ``httpx``/``httpcore`` INFO request lines (whose URL embeds the Bot API token
  in the request path) are suppressed by default;
- records that still contain a Telegram bot token or a
  ``api.telegram.org/bot<TOKEN>/...`` URL are redacted before any handler
  renders them;
- ordinary non-secret Telegram/MCP diagnostics remain visible.
"""
from __future__ import annotations

import io
import logging

import pytest

from lingtai.mcp_servers import _entrypoint

# Deliberately fake: never use a real token in tests or logs.
_FAKE_TOKEN = "123456789:AAH3fakefakefakefakefakefakefakefakefakefake"
_FAKE_URL = f"https://api.telegram.org/bot{_FAKE_TOKEN}/getMe"


def _attach_capture_handler() -> tuple[io.StringIO, logging.Handler]:
    """Attach a DEBUG StringIO handler to root; returns (stream, handler).

    Must run before ``configure_stdio_logging()`` so the redaction filter is
    installed on this handler too — the same way the real stderr handler gets
    it — and records emitted by descendant loggers are rendered through it.
    """
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logging.getLogger().addHandler(handler)
    return stream, handler


class _LoggingState:
    """Save/restore the root logger and HTTP-client logger state."""

    def __init__(self) -> None:
        root = logging.getLogger()
        self._root_handlers = root.handlers[:]
        self._root_level = root.level
        self._root_filters = root.filters[:]
        self._httpx_level = logging.getLogger("httpx").level
        self._httpcore_level = logging.getLogger("httpcore").level

    def restore(self) -> None:
        root = logging.getLogger()
        root.handlers[:] = self._root_handlers
        root.setLevel(self._root_level)
        root.filters[:] = self._root_filters
        logging.getLogger("httpx").setLevel(self._httpx_level)
        logging.getLogger("httpcore").setLevel(self._httpcore_level)


@pytest.fixture
def saved_logging_state():
    state = _LoggingState()
    yield state
    state.restore()


def _record(msg: str) -> logging.LogRecord:
    return logging.LogRecord(
        name="lingtai.mcp_servers.telegram",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=(),
        exc_info=None,
    )


# ---------------------------------------------------------------------------
# Filter unit behaviour
# ---------------------------------------------------------------------------


def test_filter_redacts_bot_api_url():
    rec = _record(f"startup failed: {_FAKE_URL}")
    assert _entrypoint._telegram_credential_filter.filter(rec) is True
    assert _FAKE_TOKEN not in rec.getMessage()
    assert "[REDACTED]" in rec.getMessage()
    # Non-secret host/prefix survives so diagnostics stay useful.
    assert "api.telegram.org/bot" in rec.getMessage()


def test_filter_redacts_bare_token():
    rec = _record(f"token {_FAKE_TOKEN} rotated")
    assert _entrypoint._telegram_credential_filter.filter(rec) is True
    assert _FAKE_TOKEN not in rec.getMessage()
    assert "[REDACTED]" in rec.getMessage()
    assert "rotated" in rec.getMessage()


def test_filter_keeps_ordinary_diagnostics():
    rec = _record("Telegram account 'myagent' started (@test_bot)")
    assert _entrypoint._telegram_credential_filter.filter(rec) is True
    assert rec.getMessage() == "Telegram account 'myagent' started (@test_bot)"


# ---------------------------------------------------------------------------
# End-to-end: stderr output of a configured stdio server
# ---------------------------------------------------------------------------


def test_httpx_info_request_lines_are_suppressed(saved_logging_state):
    stream, handler = _attach_capture_handler()
    try:
        _entrypoint.configure_stdio_logging()
        httpx_logger = logging.getLogger("httpx")
        # The INFO request line is dropped at the logger level, so it must not
        # reach any handler at all.
        assert httpx_logger.getEffectiveLevel() >= logging.WARNING
        httpx_logger.info('HTTP Request: POST %s "HTTP/1.1 200 OK"', _FAKE_URL)
        # A WARNING that still carries the URL is redacted before rendering.
        httpx_logger.warning('HTTP Request: POST %s "HTTP/1.1 200 OK"', _FAKE_URL)
    finally:
        logging.getLogger().removeHandler(handler)
    captured = stream.getvalue()
    assert _FAKE_TOKEN not in captured
    assert _FAKE_URL not in captured
    assert captured.count("HTTP Request") == 1  # only the WARNING line


def test_stderr_never_contains_token(saved_logging_state):
    stream, handler = _attach_capture_handler()
    try:
        _entrypoint.configure_stdio_logging()
        logger = logging.getLogger("lingtai.mcp_servers.telegram")
        logger.error("startup failed: %s", _FAKE_URL)
        logger.error("token %s rotated", _FAKE_TOKEN)
        logger.info("Telegram account 'myagent' started (@test_bot)")
    finally:
        logging.getLogger().removeHandler(handler)
    captured = stream.getvalue()
    assert _FAKE_TOKEN not in captured
    assert _FAKE_URL not in captured
    assert "[REDACTED]" in captured
    # Ordinary non-secret diagnostics remain visible.
    assert "Telegram account 'myagent' started (@test_bot)" in captured


def test_configure_stdio_logging_attaches_filter_once(saved_logging_state):
    _entrypoint.configure_stdio_logging()
    _entrypoint.configure_stdio_logging()
    root = logging.getLogger()
    assert root.filters.count(_entrypoint._telegram_credential_filter) == 1
    assert root.handlers  # basicConfig created the stderr handler
    for handler in root.handlers:
        assert handler.filters.count(_entrypoint._telegram_credential_filter) == 1
