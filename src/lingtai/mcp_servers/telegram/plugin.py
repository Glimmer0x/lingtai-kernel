"""The Telegram curated MCP plugin descriptor.

One place where this package states who it is: its registry name, the MCP
server identity, the stdio declaration the curated catalog publishes for it,
the bundled ``SKILL.md`` its ``manual`` action returns, and the actions it
*itself* owns. ``manual`` is deliberately absent from
:data:`TELEGRAM_DECLARED_ACTIONS` — :class:`~lingtai.mcp_servers._plugin.CuratedMcpPlugin`
appends the reserved action from the packaged skill and rejects any attempt to
declare it here.

``_family.py`` consumes this for the public schema, settings opt-in, and
dispatch, ``server.py`` for its server/manifest identity, and ``manager.py``
for the manual payload.
The shipped ``lingtai/mcp_catalog.json`` entry must equal
:meth:`~lingtai.mcp_servers._plugin.CuratedMcpPlugin.mcp_declaration`; the
catalog file itself stays the runtime source the host reads.
"""
from __future__ import annotations

from .._plugin import CuratedMcpPlugin

TELEGRAM_PLUGIN = CuratedMcpPlugin(
    name="telegram",
    package=__package__,
    server_name="lingtai-telegram",
    summary="Telegram bot client — Bot API send/receive with LICC inbox callback.",
    homepage="https://github.com/Lingtai-AI/lingtai-telegram",
    skill_name="telegram-mcp-manual",
    settings=True,
)

#: Telegram's own public actions, in stable model-facing order. The reserved
#: ``manual`` action is appended by the plugin, never declared here.
TELEGRAM_DECLARED_ACTIONS: tuple[str, ...] = (
    "send", "check", "read", "reply", "search", "delete", "edit",
    "contacts", "add_contact", "remove_contact", "accounts",
)

#: The complete public action list, declared actions followed by ``manual``.
TELEGRAM_ACTIONS: tuple[str, ...] = TELEGRAM_PLUGIN.actions(TELEGRAM_DECLARED_ACTIONS)
