"""The Vision local-tool plugin descriptor.

One place where this package states who it is: its capability/registry name,
the module the built-in registry resolves that name to, the default-boot
declaration, the packaged ``manual/SKILL.md`` it owns, and the actions it
*itself* owns. ``manual`` is deliberately absent from
:data:`VISION_DECLARED_ACTIONS` — :class:`~lingtai.tools._plugin.LocalToolPlugin`
appends the reserved action from the packaged skill and rejects any attempt to
declare it here.

``__init__.py`` consumes this for the composed family, the public description,
and the mount; ``tests/test_local_tool_plugin_package.py`` pins that
:meth:`~lingtai.tools._plugin.LocalToolPlugin.capability_declaration` equals the
entry ``lingtai/tools/registry.py`` publishes. The registry file itself stays
the runtime source the host reads.

Nothing about provider selection, credential resolution, or the fail-closed
manual-guidance routes lives here: those stay in ``__init__.py``, which the
plugin never enters.
"""
from __future__ import annotations

from .._plugin import LocalToolPlugin

VISION_PLUGIN = LocalToolPlugin(
    name="vision",
    package=__package__,
    summary=(
        "Image understanding on the active preset's own vision route, with a "
        "provider-neutral manual when no direct route is available."
    ),
    homepage="https://github.com/Lingtai-AI/lingtai",
    skill_name="vision-manual",
    # ``vision`` is always registered: its provider defaults to the active LLM,
    # and analyze may borrow another allowed preset's service per call. The
    # empty kwargs are the whole of its default configuration.
    default_on=True,
    default_kwargs={},
)

#: Vision's own public actions, in stable model-facing order. The reserved
#: ``manual`` action is appended by the plugin, never declared here.
VISION_DECLARED_ACTIONS: tuple[str, ...] = ("analyze", "check", "list")

#: The complete public action list, declared actions followed by ``manual``.
VISION_ACTIONS: tuple[str, ...] = VISION_PLUGIN.actions(VISION_DECLARED_ACTIONS)
