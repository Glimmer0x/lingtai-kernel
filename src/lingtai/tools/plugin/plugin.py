"""The ``plugin`` capability's own tool-plugin descriptor.

One place where this package states who it is: its public tool and capability
name, the module the built-in registry imports for it, whether it is default-on,
the bundled ``manual/SKILL.md`` its ``manual`` action serves, and the actions it
*itself* owns. ``manual`` is deliberately absent from
:data:`PLUGIN_DECLARED_ACTIONS` — :class:`~lingtai.tools._plugin.ToolPlugin`
appends the reserved action from the packaged skill and rejects any attempt to
declare it here.

``__init__.py`` consumes this for the tool name, the composed schema, the family
it dispatches, and the manual mount. ``lingtai.tools.registry``'s
``BUILTIN_TOOLS``/``CORE_DEFAULTS`` entries must equal
:meth:`~lingtai.tools._plugin.ToolPlugin.capability_declaration`; the registry
tables themselves stay the runtime source the host reads, because the registry
must remain importable without importing every tool.

**This package is a tool plugin, not an Agent Plugin.** It is the model-facing
tool that *reports* Agent Plugins (agent-plugins.org v1.0.0) — so it is the one
package where confusing the two would be self-referential. It ships no
``plugin.json``, is never scanned by ``services.plugin_registry.read_plugins``,
never appears in its own ``info`` snapshot, and owns no ``source="plugin:plugin"``
registry record. ``ToolPlugin`` enforces the first of those at import time; the
rest follow from it, and ``tests/test_tool_plugin_package.py`` pins all of them.
"""
from __future__ import annotations

from .._plugin import ToolPlugin

TOOL_PLUGIN = ToolPlugin(
    name="plugin",
    package=__package__,
    summary=(
        "Agent Plugins (agent-plugins.org v1.0.0) catalog and boot registration "
        "snapshot — read-only presentation, mounts nothing."
    ),
    skill_name="plugin-manual",
    # The public capability name and the implementation directory agree here, so
    # the manual mounts at ``.library/intrinsic/capabilities/plugin/``. It is
    # still declared rather than inferred: ``shell``/``web`` prove the two can
    # differ, and the installer must read a declaration, not a coincidence.
    manual_destination="plugin",
    # Default-on for the same reason ``mcp`` is: the capability is pure
    # presentation, writes nothing, and costs one directory scan.
    default_kwargs={},
)

#: This capability's own public actions, in stable model-facing order. The
#: reserved ``manual`` action is appended by the plugin, never declared here.
PLUGIN_DECLARED_ACTIONS: tuple[str, ...] = ("info",)

#: The complete public action list, declared actions followed by ``manual``.
PLUGIN_ACTIONS: tuple[str, ...] = TOOL_PLUGIN.actions(PLUGIN_DECLARED_ACTIONS)
