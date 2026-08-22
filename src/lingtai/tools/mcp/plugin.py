"""The ``mcp`` built-in tool plugin descriptor.

One place where this package states who it is, and one file — ``plugin.json``,
right next to this module — that says the same thing in the format the kernel's
Agent Plugins reader understands. :data:`MCP_TOOL_PLUGIN` binds the two: it
declares the model-facing tool name, the Python package that ships the manifest,
and the owned ``skills/mcp-manual`` skill the reserved ``manual`` action serves,
and :class:`~lingtai.tools._plugin.BuiltinToolPlugin` raises at import if any of
the three disagrees with the manifest on disk.

``mcp/__init__.py`` consumes this for the public family (schema-only and
agent-bound alike) and for the manual child's mount name. ``Agent._install_
intrinsic_manuals`` never sees this module: it discovers the same package from
``plugin.json`` alone, through ``lingtai.services.plugin_registry.read_plugin``
— the descriptor is the package's statement of identity, not a second reader.

``manual`` is deliberately absent from :data:`MCP_DECLARED_ACTIONS`: the plugin
appends the reserved action from the owned skill and rejects any attempt to
declare it here. Nothing in this package declares an MCP server — there is no
``mcp.json`` beside the manifest, and there must never be one. The registry this
tool renders is per-agent state at ``<agent>/mcp_registry.jsonl``, written by the
model with ``write``/``edit`` and activated by an ``init.json`` top-level ``mcp``
entry; packaging the tool changes none of that.
"""
from __future__ import annotations

from .._plugin import BuiltinToolPlugin

__all__ = [
    "MCP_ACTIONS",
    "MCP_DECLARED_ACTIONS",
    "MCP_TOOL_PLUGIN",
]

MCP_TOOL_PLUGIN = BuiltinToolPlugin(
    name="mcp",
    package=__package__,
    manual_skill="mcp-manual",
)

#: mcp's own public actions, in stable model-facing order. The reserved
#: ``manual`` action is appended by the plugin, never declared here.
MCP_DECLARED_ACTIONS: tuple[str, ...] = ("info",)

#: The complete public action list, declared actions followed by ``manual``.
MCP_ACTIONS: tuple[str, ...] = MCP_TOOL_PLUGIN.actions(MCP_DECLARED_ACTIONS)
