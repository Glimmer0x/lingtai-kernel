"""The Cloud Mail curated MCP plugin descriptor.

One place where this package states who it is: its registry name, the MCP
server identity, the stdio declaration the curated catalog publishes for it,
the bundled ``SKILL.md`` its ``manual`` action returns, its settings opt-in,
and the actions it *itself* owns. ``settings`` and ``manual`` are deliberately
absent from :data:`CLOUD_MAIL_DECLARED_ACTIONS` —
:class:`~lingtai.mcp_servers._plugin.CuratedMcpPlugin` inserts them in canonical
order and rejects any attempt to declare them here.

``_family.py`` consumes this for the public schema and dispatch, ``server.py``
for its server identity, and ``manager.py`` for the manual payload.
The shipped ``lingtai/mcp_catalog.json`` entry must equal
:meth:`~lingtai.mcp_servers._plugin.CuratedMcpPlugin.mcp_declaration`; the
catalog file itself stays the runtime source the host reads.
"""
from __future__ import annotations

from .._plugin import CuratedMcpPlugin

CLOUD_MAIL_PLUGIN = CuratedMcpPlugin(
    name="cloud_mail",
    package=__package__,
    server_name="lingtai-cloud-mail",
    summary=(
        "Cloud Mail REST email client — Cloudflare Workers Cloud Mail polling "
        "with LICC inbox callback."
    ),
    homepage="https://github.com/maillab/cloud-mail",
    skill_name="cloud-mail-mcp-manual",
    settings=True,
)

#: Cloud Mail's own public actions, in stable model-facing order. The reserved
#: ``settings`` and ``manual`` actions are inserted by the plugin.
CLOUD_MAIL_DECLARED_ACTIONS: tuple[str, ...] = (
    "check", "search", "read", "send", "accounts", "add_user",
)

#: Complete public order: declared actions, ``settings``, then ``manual``.
CLOUD_MAIL_ACTIONS: tuple[str, ...] = CLOUD_MAIL_PLUGIN.actions(CLOUD_MAIL_DECLARED_ACTIONS)
