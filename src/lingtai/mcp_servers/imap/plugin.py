"""The IMAP curated MCP plugin descriptor.

One place where this package states who it is: its registry name, the MCP
server identity, the stdio declaration the curated catalog publishes for it,
the bundled ``SKILL.md`` its ``manual`` action returns, and the actions it
*itself* owns. ``manual`` is deliberately absent from
:data:`IMAP_DECLARED_ACTIONS` — :class:`~lingtai.mcp_servers._plugin.CuratedMcpPlugin`
appends the reserved action from the packaged skill and rejects any attempt to
declare it here. Mirrors ``telegram/plugin.py``, the reference slice for
``_plugin.py``.

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
)

#: IMAP's own public actions, in stable model-facing order. The reserved
#: ``manual`` action is appended by the plugin, never declared here.
IMAP_DECLARED_ACTIONS: tuple[str, ...] = (
    "send", "check", "read", "reply", "search",
    "delete", "move", "flag", "folders",
    "contacts", "add_contact", "remove_contact", "edit_contact",
    "accounts",
)

#: The complete public action list, declared actions followed by ``manual``.
IMAP_ACTIONS: tuple[str, ...] = IMAP_PLUGIN.actions(IMAP_DECLARED_ACTIONS)
