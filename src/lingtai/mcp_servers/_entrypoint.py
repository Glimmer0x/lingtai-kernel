"""Shared stdio entrypoint for curated MCP servers.

Every bundled MCP server's ``__main__.py`` ran the same three steps: configure
INFO logging to **stderr** (so logs never corrupt the JSON-RPC stdout channel),
``asyncio.run(serve())``, and swallow ``KeyboardInterrupt`` on Ctrl-C. This is
the single copy.

Since INFO logging is enabled for the whole addon process, HTTP client
libraries (``httpx``/``httpcore``) would otherwise persist full request URLs at
INFO level. Credential-bearing URL path segments (Telegram Bot API embeds the
bot token as ``/bot<id>:<secret>/...``) are redacted by a logging filter before
any handler persists the record.
"""
from __future__ import annotations

import asyncio
import logging
import re
import sys
from collections.abc import Awaitable, Callable


# Matches the Telegram Bot API URL path segment that embeds the bot token
# (https://api.telegram.org/bot<id>:<secret>/<method> and the
# /file/bot<id>:<secret>/... download form). Keeps the "/bot" prefix visible so
# the redacted record remains recognizable. Mirrors the trajectory redactor in
# ``lingtai.kernel.trace_redaction``.
_TELEGRAM_BOT_URL_RE = re.compile(r"(/bot)\d{6,12}:[A-Za-z0-9_-]{30,}(?![A-Za-z0-9_-])")
_TELEGRAM_BOT_URL_REDACTED = r"\1<REDACTED:telegram_bot_token>"


class _HttpUrlCredentialFilter(logging.Filter):
    """Redact credential-bearing URL path segments from HTTP client logs."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            return True  # malformed record: leave it to the normal formatter
        redacted = _TELEGRAM_BOT_URL_RE.sub(_TELEGRAM_BOT_URL_REDACTED, message)
        if redacted != message:
            record.msg = redacted
            record.args = ()
        return True


def _protect_http_loggers() -> None:
    """Attach the credential-redacting filter to HTTP client loggers."""
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).addFilter(_HttpUrlCredentialFilter())


def run_stdio_server_main(serve: Callable[[], Awaitable[None]]) -> None:
    """Configure stderr logging and run ``serve()`` until interrupted."""
    # Logs to stderr so they don't pollute the MCP stdio channel.
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stderr,
    )
    _protect_http_loggers()
    try:
        asyncio.run(serve())
    except KeyboardInterrupt:
        pass
