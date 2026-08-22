"""The notification intrinsic-tool plugin descriptor.

One place where this package states who it is: its public tool name, the
``registry.INTRINSICS`` record the kernel wires, the one-line summary its model
description opens with, the bundled ``manual/SKILL.md`` the agent library
installs, and the actions it *itself* owns. ``manual`` is deliberately absent
from :data:`NOTIFICATION_DECLARED_ACTIONS` —
:class:`~lingtai.tools._plugin.IntrinsicToolPlugin` appends the reserved action
bound to this package's own installed skill and rejects any attempt to declare
it here.

``schema.py`` consumes this for the model-facing description, and
``__init__.py`` for the composed schema, the per-call dispatching family, and
the reserved ``manual`` child. The shipped ``registry.INTRINSICS['notification']``
entry must equal
:meth:`~lingtai.tools._plugin.IntrinsicToolPlugin.intrinsic_declaration`; the
registry module itself stays the runtime source the kernel reads.
"""
from __future__ import annotations

from .._plugin import IntrinsicToolPlugin

NOTIFICATION_PLUGIN = IntrinsicToolPlugin(
    name="notification",
    package=__package__,
    summary=(
        "Notification surface — read and clear the agent's notification "
        "channels, and manage external-hook registrations. Self-actions, no "
        "permissions needed."
    ),
    skill_name="notification-manual",
)

#: Notification's own public actions, in stable model-facing order: the
#: voluntary read, the three atomic dismiss verbs, the four hook-registry verbs,
#: and consumer-only ``delay``. This one tuple is the single source for the
#: schema's ``action`` enum order, the ``input`` branch order, and the child
#: registration order. The reserved ``manual`` action is appended by the
#: plugin, never declared here.
NOTIFICATION_DECLARED_ACTIONS: tuple[str, ...] = (
    "check",
    "dismiss_channel",
    "dismiss_event",
    "dismiss_ref",
    "add",
    "drop",
    "edit",
    "list",
    "delay",
)

#: The complete public action list, declared actions followed by ``manual``.
NOTIFICATION_ACTIONS: tuple[str, ...] = NOTIFICATION_PLUGIN.actions(
    NOTIFICATION_DECLARED_ACTIONS
)
