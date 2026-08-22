"""The Daemon built-in tool plugin descriptor.

One place where this package states who it is: its public capability name, the
module the capability registry imports for it, the packaged ``manual/`` bundle
the initializer mounts, the skill that bundle declares, and the actions it
*itself* owns. ``manual`` is deliberately absent from
:data:`DAEMON_DECLARED_ACTIONS` —
:class:`~lingtai.tools._plugin.BuiltinToolPlugin` appends the reserved action,
bound to this package's own mounted skill, and rejects any attempt to declare
it here.

``_tool_family.py`` consumes this for the public action order, the composed
schema, and the dispatch registry; ``__init__.py`` for the registered public
tool name. The shipped ``registry.BUILTIN_TOOLS`` entry must equal this
descriptor's :meth:`~lingtai.tools._plugin.BuiltinToolPlugin.capability_declaration`
``module``, and the initializer's mount must equal its ``manual_mount``; the
registry and the initializer themselves stay the runtime source the host reads.

Nothing about the daemon *engine* lives here. Manager construction, backend
routing, run directories, the detached supervisor, completion signalling,
cancellation, timeouts, notifications, config resolution, and every auth or
credential boundary stay exactly where they were — this descriptor is
declarative packaging only.
"""
from __future__ import annotations

from .._plugin import BuiltinToolPlugin

DAEMON_PLUGIN = BuiltinToolPlugin(
    name="daemon",
    package=__package__,
    implementation="daemon",
    summary=(
        "Daemon (神識) — delegate work to ephemeral subagents for context "
        "isolation, with supervised lifecycle and exactly-once terminal "
        "notification."
    ),
    manual_skill_name="daemon-manual",
)

#: Daemon's own public actions, in stable model-facing order. The reserved
#: ``manual`` action is appended by the plugin, never declared here.
DAEMON_DECLARED_ACTIONS: tuple[str, ...] = (
    "emanate",
    "list",
    "ask",
    "check",
    "reclaim",
)

#: The complete public action list, declared actions followed by ``manual``.
#: This is the model-facing ``action`` enum order, the ``input`` branch order,
#: and the dispatch order — one list, three roles.
DAEMON_ACTIONS: tuple[str, ...] = DAEMON_PLUGIN.actions(DAEMON_DECLARED_ACTIONS)
