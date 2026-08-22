"""The Shell built-in tool plugin descriptor.

One place where this package states who it is: its public capability/family
name, the retained implementation module the registry mounts, the bundled
``manual/SKILL.md`` its ``manual`` action serves, the capability record the host
must agree with, and the actions it *itself* owns. ``manual`` is deliberately
absent from :data:`SHELL_DECLARED_ACTIONS` —
:class:`~lingtai.tools._plugin.KernelToolPlugin` appends the reserved action
from the packaged skill and rejects any attempt to declare it here.

``_tool_family.py`` consumes this for the public schema and dispatch,
``__init__.py`` for the registered tool name, and
``Agent._install_intrinsic_manuals`` reaches it through
:func:`lingtai.tools._plugin.manual_destination_for` to learn that this
package's ``manual/`` bundle installs under ``capabilities/shell/`` rather than
under its own directory name. ``lingtai.tools.registry``'s ``BUILTIN_TOOLS`` /
``CORE_DEFAULTS`` entries must equal :meth:`capability_declaration`; those
tables themselves stay the runtime source the host reads.

Nothing here executes a command, selects a dialect, or touches containment. The
descriptor is declarative: ``ShellPolicy``, ``ShellDialect``, the sandbox
containment check, and the durable async supervisor are all unchanged and stay
where they are, behind ``setup()`` and ``ShellManager``.
"""
from __future__ import annotations

from .._plugin import KernelToolPlugin, register_tool_plugin

#: Shell's descriptor. ``name`` is the model-facing capability; ``package`` is
#: the retained ``bash`` implementation directory the registry maps it to (the
#: one place that historical split is written down, instead of a literal in the
#: registry and a second literal in the manual installer). ``default_kwargs``
#: mirrors ``registry.CORE_DEFAULTS["shell"]``: unsandboxed by default, with a
#: host that wants containment passing ``policy_file`` through init.json.
SHELL_PLUGIN = register_tool_plugin(
    KernelToolPlugin(
        name="shell",
        package=__package__,
        summary=(
            "Shell command execution with file-based policy, host dialect "
            "detection, and durable async jobs."
        ),
        skill_name="shell-manual",
        default_kwargs={"yolo": True},
    )
)

#: Shell's own public actions, in stable model-facing order. The reserved
#: ``manual`` action is appended by the plugin, never declared here.
SHELL_DECLARED_ACTIONS: tuple[str, ...] = ("run", "poll", "cancel")

#: The complete public action list, declared actions followed by ``manual``.
SHELL_ACTIONS: tuple[str, ...] = SHELL_PLUGIN.actions(SHELL_DECLARED_ACTIONS)
