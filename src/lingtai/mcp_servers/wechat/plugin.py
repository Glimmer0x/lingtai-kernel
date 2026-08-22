"""The WeChat curated MCP plugin descriptor.

One place where this package states who it is: its registry name, the MCP
server identity, the stdio declaration the curated catalog publishes for it,
the bundled ``SKILL.md`` its ``manual`` action returns, and the actions it
*itself* owns. ``manual`` is deliberately absent from
:data:`WECHAT_DECLARED_ACTIONS` — :class:`~lingtai.mcp_servers._plugin.CuratedMcpPlugin`
appends the reserved action from the packaged skill and rejects any attempt to
declare it here.

``_family.py`` consumes this for the public schema and dispatch, ``server.py``
for its server/manifest identity, and ``manager.py`` for the manual payload.
The shipped ``lingtai/mcp_catalog.json`` entry must equal
:meth:`~lingtai.mcp_servers._plugin.CuratedMcpPlugin.mcp_declaration`; the
catalog file itself stays the runtime source the host reads.
"""
from __future__ import annotations

from .._plugin import CuratedMcpPlugin

WECHAT_PLUGIN = CuratedMcpPlugin(
    name="wechat",
    package=__package__,
    server_name="lingtai-wechat",
    summary="WeChat client via iLink Bot API — text/media send/receive with LICC inbox callback.",
    homepage="https://github.com/Lingtai-AI/lingtai-wechat",
    skill_name="wechat-mcp-manual",
)

#: WeChat's own public actions, in stable model-facing order. The reserved
#: ``manual`` action is appended by the plugin, never declared here.
WECHAT_DECLARED_ACTIONS: tuple[str, ...] = (
    "send", "check", "read", "reply", "search",
    "contacts", "add_contact", "remove_contact", "accounts",
)

#: The complete public action list, declared actions followed by ``manual``.
WECHAT_ACTIONS: tuple[str, ...] = WECHAT_PLUGIN.actions(WECHAT_DECLARED_ACTIONS)
