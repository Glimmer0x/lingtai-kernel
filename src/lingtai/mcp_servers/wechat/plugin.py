"""The WeChat curated MCP plugin descriptor.

One place where this package states who it is: its registry name, the MCP
server identity, the stdio declaration the curated catalog publishes for it,
the bundled ``SKILL.md`` its ``manual`` action returns, its settings opt-in,
and the actions it *itself* owns. Both reserved actions are absent from
:data:`WECHAT_DECLARED_ACTIONS` — :class:`~lingtai.mcp_servers._plugin.CuratedMcpPlugin`
appends ``settings`` immediately before ``manual`` and rejects attempts to
declare either here.

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
    settings=True,
)

#: WeChat's own public actions, in stable model-facing order. The reserved
#: ``settings`` and ``manual`` actions are appended, never declared here.
WECHAT_DECLARED_ACTIONS: tuple[str, ...] = (
    "send", "check", "read", "reply", "search",
    "contacts", "add_contact", "remove_contact", "accounts",
)

#: Complete public actions: declared actions, then ``settings``, then ``manual``.
WECHAT_ACTIONS: tuple[str, ...] = WECHAT_PLUGIN.actions(WECHAT_DECLARED_ACTIONS)
