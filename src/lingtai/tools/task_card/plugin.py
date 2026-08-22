"""The Task Card local-tool plugin descriptor.

One place where this package states who it is: its capability/registry name,
the module the built-in registry mounts, the summary that record carries, the
bundled ``manual/SKILL.md`` its ``manual`` action serves, the installed library
destination that bundle lands in, and the actions it *itself* owns. ``manual``
is deliberately absent from :data:`TASK_CARD_DECLARED_ACTIONS` —
:class:`~lingtai.tools._plugin.LocalToolPlugin` appends the reserved action
from the packaged skill and rejects any attempt to declare it here.

``__init__.py`` consumes this for the model-facing schema, the description, the
manager's dispatch family, the notification channel it registers, and the name
it mounts under in :func:`~lingtai.tools.task_card.setup`. The shipped
``lingtai.tools.registry`` entries (``BUILTIN_TOOLS``, ``CORE_DEFAULTS``) must
equal :meth:`~lingtai.tools._plugin.LocalToolPlugin.tool_declaration`; the
registry itself stays the runtime source the host reads, because importing it
must not eagerly import every tool package.

Nothing about the Task Card artifact moves here. The renderer subprocess, the
atomic ``taskcard/status`` + ``taskcard/taskcard.md`` writes, the persisted
watch descriptor, the resident meta projection, and the read-only
Telegram/Feishu projections all stay exactly where they are: this descriptor
governs packaging and the model-facing surface, not the capability's behavior.
"""
from __future__ import annotations

from .._plugin import LocalToolPlugin

TASK_CARD_PLUGIN = LocalToolPlugin(
    name="task_card",
    package=__package__,
    summary=(
        "Intrinsic declarative Task Card artifact — one renderer watch writing "
        "the agent-local taskcard/status and taskcard/taskcard.md files."
    ),
    manual_skill="task_card",
    skill_name="task_card-manual",
    default_configuration={},
)

#: Task Card's own public actions, in stable model-facing order. The reserved
#: ``manual`` action is appended by the plugin, never declared here.
TASK_CARD_DECLARED_ACTIONS: tuple[str, ...] = (
    "start", "inspect", "retry", "stop", "remove",
)

#: The complete public action list, declared actions followed by ``manual``.
TASK_CARD_ACTIONS: tuple[str, ...] = TASK_CARD_PLUGIN.actions(TASK_CARD_DECLARED_ACTIONS)
