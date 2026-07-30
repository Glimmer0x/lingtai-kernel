"""LingTai Telegram MCP server.

Exposes the omnibus ``telegram`` tool (send/check/read/reply/search/...)
over MCP/stdio and pushes inbound messages into the host agent's inbox
via LICC. Reads multi-account config from a JSON file pointed at by the
LINGTAI_TELEGRAM_CONFIG env var.
"""
from .account import (
    inline_keyboard_approve_reject,
    inline_keyboard_options,
    inline_keyboard_yes_no,
)
from .licc import push_inbox_event


def __getattr__(name: str):
    if name in {"serve", "build_server", "build_manager", "load_config"}:
        from importlib import import_module

        server = import_module(f"{__name__}.server")
        return getattr(server, name)
    raise AttributeError(name)

__all__ = [
    "serve",
    "build_server",
    "build_manager",
    "load_config",
    "push_inbox_event",
    "inline_keyboard_yes_no",
    "inline_keyboard_approve_reject",
    "inline_keyboard_options",
]
