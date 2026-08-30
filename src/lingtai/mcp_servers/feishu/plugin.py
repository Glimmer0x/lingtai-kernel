"""The Feishu curated MCP plugin descriptor.

One place where this package states who it is: its registry name, the MCP
server identity, the stdio declaration the curated catalog publishes for it,
the bundled ``SKILL.md`` its ``manual`` action returns, and the actions it
*itself* owns. ``settings`` and ``manual`` are deliberately absent from
:data:`FEISHU_DECLARED_ACTIONS` — :class:`~lingtai.mcp_servers._plugin.CuratedMcpPlugin`
composes both reserved actions and rejects any attempt to declare them here.

``_family.py`` consumes this for the public schema and dispatch, ``server.py``
for its server/manifest identity, and ``manager.py`` for the manual payload.
The shipped ``lingtai/mcp_catalog.json`` entry must equal
:meth:`~lingtai.mcp_servers._plugin.CuratedMcpPlugin.mcp_declaration`; the
catalog file itself stays the runtime source the host reads. Mirrors the
Telegram MCP's packaging (``../telegram/plugin.py``).
"""
from __future__ import annotations

from .._plugin import CuratedMcpPlugin

FEISHU_PLUGIN = CuratedMcpPlugin(
    name="feishu",
    package=__package__,
    server_name="lingtai-feishu",
    summary="Feishu/Lark message client — Open API send/receive with LICC inbox callback.",
    homepage="https://github.com/Lingtai-AI/lingtai-feishu",
    skill_name="feishu-mcp-manual",
    settings=True,
)

#: Feishu's own public actions, in stable model-facing order. The reserved
#: ``settings`` and ``manual`` actions are appended by the plugin.
FEISHU_DECLARED_ACTIONS: tuple[str, ...] = (
    "send", "check", "read", "reply", "react", "search", "delete", "edit",
    "contacts", "add_contact", "remove_contact", "accounts",
)

#: The complete public action list, declared actions followed by ``settings``
#: and ``manual``.
FEISHU_ACTIONS: tuple[str, ...] = FEISHU_PLUGIN.actions(FEISHU_DECLARED_ACTIONS)
