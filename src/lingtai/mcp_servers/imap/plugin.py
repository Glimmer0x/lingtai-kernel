"""The IMAP curated MCP plugin descriptor.

One place where this package states who it is: its registry name, the MCP
server identity, the stdio declaration the curated catalog publishes for it,
the bundled ``SKILL.md`` its ``manual`` action returns, its read-only settings
opt-in, and the actions it *itself* owns. ``settings`` and ``manual`` are
deliberately absent from
:data:`IMAP_DECLARED_ACTIONS` — :class:`~lingtai.mcp_servers._plugin.CuratedMcpPlugin`
composes those reserved actions and rejects any attempt to declare them here.

``_family.py`` consumes this for the public schema and dispatch, ``server.py``
for its server/tool identity, and ``manager.py`` for the manual payload. The
shipped ``lingtai/mcp_catalog.json`` entry must equal
:meth:`~lingtai.mcp_servers._plugin.CuratedMcpPlugin.mcp_declaration`; the
catalog file itself stays the runtime source the host reads.
"""
from __future__ import annotations

from .._plugin import CuratedMcpPlugin

IMAP_PLUGIN = CuratedMcpPlugin(
    name="imap",
    package=__package__,
    server_name="lingtai-imap",
    summary="Real email via IMAP/SMTP — multi-account support.",
    homepage="https://github.com/Lingtai-AI/lingtai-imap",
    skill_name="imap-mcp-manual",
    settings=True,
)

#: IMAP's own public actions, in stable model-facing order. The reserved
#: ``settings`` and ``manual`` actions are composed by the plugin.
IMAP_DECLARED_ACTIONS: tuple[str, ...] = (
    "send", "check", "read", "reply", "search",
    "delete", "move", "flag", "folders",
    "contacts", "add_contact", "remove_contact", "edit_contact",
    "accounts",
)

#: Complete public actions: declared actions, ``settings``, then ``manual``.
IMAP_ACTIONS: tuple[str, ...] = IMAP_PLUGIN.actions(IMAP_DECLARED_ACTIONS)
