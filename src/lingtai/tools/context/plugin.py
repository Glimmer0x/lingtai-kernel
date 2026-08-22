"""The Context intrinsic tool plugin descriptor.

One place where this package states who it is: its registry name and public
root, the module the built-in registry wires for it, the packaged ``manual/``
bundle its reserved ``manual`` action reads, and the actions it *itself* owns.
``manual`` is deliberately absent from :data:`CONTEXT_DECLARED_ACTIONS` —
:class:`~lingtai.tools._plugin.IntrinsicToolPlugin` appends the reserved action
bound to the packaged skill and rejects any attempt to declare it here.

``__init__.py`` consumes this for its public root name, action order, family
composition, and manual binding. The shipped
``lingtai.tools.registry.INTRINSICS`` entry must equal
:meth:`~lingtai.tools._plugin.IntrinsicToolPlugin.intrinsic_declaration`'s
``name``/``module``, and the mount ``Agent._install_intrinsic_manuals``
materializes must equal :meth:`manual_mount` — the registry mapping and the
installer stay the runtime sources the host reads.

The bundle name is ``context-manual``, not ``context``: that skill name is
already written into the prompt corpus, the rendered skills catalog, and every
cross-manual reference, so packaging it into its owning tool moves *where the
document lives*, never what it is called.
"""
from __future__ import annotations

from .._plugin import IntrinsicToolPlugin

CONTEXT_PLUGIN = IntrinsicToolPlugin(
    name="context",
    package=__package__,
    summary=(
        "The agent's own context — shed it (molt), compact it (summarize), "
        "rebuild it."
    ),
    homepage="https://github.com/Lingtai-AI/lingtai-kernel",
    skill_name="context-manual",
)

#: Context's own public actions, in stable model-facing order: the lifecycle
#: operation first, then the two context-hygiene operations in the order they
#: are used (record, then apply). The reserved ``manual`` action is appended by
#: the plugin, never declared here.
CONTEXT_DECLARED_ACTIONS: tuple[str, ...] = ("molt", "summarize", "rebuild")

#: The complete public action list, declared actions followed by ``manual``.
CONTEXT_ACTIONS: tuple[str, ...] = CONTEXT_PLUGIN.actions(CONTEXT_DECLARED_ACTIONS)
