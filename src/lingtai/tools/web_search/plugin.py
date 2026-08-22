"""The ``web`` built-in tool plugin descriptor.

One place where this package states who it is: the public capability/tool name
it publishes, the retained implementation package it ships from, the packaged
``manual/`` skill it owns, where the host mounts that skill, and the actions it
*itself* owns. ``manual`` is deliberately absent from
:data:`WEB_DECLARED_ACTIONS` — :class:`~lingtai.tools._plugin.ToolPlugin`
appends the reserved action from the packaged bundle and rejects any attempt to
declare, re-schema, or rebind it here.

``__init__.py`` consumes this for its model-facing schema, its per-Agent family,
and its ``add_tool`` registration; the shipped ``plugin.json`` beside this
module is the runtime record the host actually reads (it discovers tool plugins
from disk, without importing any tool package), and it must equal
:meth:`~lingtai.tools._plugin.ToolPlugin.tool_declaration`.

Nothing about ``web``'s search/browse/provider boundaries lives here. Provider
admission, the settings-only Anthropic/Gemini opt-in, the canonical-backend
identity gate, and the internal browser Core/Port stay exactly where they were
in ``__init__.py``: this descriptor owns packaging, not policy.
"""
from __future__ import annotations

from .._plugin import ToolPlugin

#: ``web``'s own public actions, in stable model-facing order. The reserved
#: ``manual`` action is appended by the plugin, never declared here.
WEB_DECLARED_ACTIONS: tuple[str, ...] = ("search", "browse")

WEB_PLUGIN = ToolPlugin(
    name="web",
    # The retained implementation directory. It deliberately differs from the
    # public name — which is exactly why the host must be *told* the mount
    # destination (``manual.install_as``) rather than hardcode a
    # ``web_search`` → ``web`` special case.
    package=__package__,
    summary="Unified web capability — search, static browse, and its owned manual.",
    homepage=(
        "https://github.com/Lingtai-AI/lingtai-kernel/blob/main/"
        "src/lingtai/tools/web_search/CONTRACT.md"
    ),
    skill_name="web-manual",
    declared_actions=WEB_DECLARED_ACTIONS,
)

#: The complete public action list, declared actions followed by ``manual``.
WEB_ACTIONS: tuple[str, ...] = WEB_PLUGIN.actions
