"""The System intrinsic plugin descriptor.

One place where this package states who it is: its registry name and public
family name, the module the registry mounts for it, the summary/homepage its
mount record publishes, the shipped ``SKILL.md`` its ``manual`` action serves,
and the actions it *itself* owns. ``manual`` is deliberately absent from
:data:`SYSTEM_DECLARED_ACTIONS` —
:class:`~lingtai.tools._plugin.IntrinsicPlugin` appends the reserved action
from this plugin's own skill and rejects any attempt to declare it here.

``schema.py`` consumes this for the canonical action order and the per-action
``input`` registry, ``__init__.py`` for family composition and dispatch, and
``registry.py`` discovers it through the package's ``PLUGIN`` attribute to
build the ``INTRINSICS`` mount record instead of restating system's identity by
hand.

**Where the manual lives.** System's manual is the ``system-manual`` bundle in
``lingtai.intrinsic_skills`` rather than a ``tools/system/manual/`` folder,
because it is the second-layer *router* for every runtime/substrate/procedure
reference — the agent reads it (and the resident prompt sections cite it) as
``system-manual``, not as "the system tool's manual". Ownership is what this
descriptor adds: it is the single place that names that bundle, it resolves and
validates the shipped copy at import (a renamed, moved, or emptied
``system-manual`` fails the import rather than silently degrading every agent's
``manual`` to an empty body), and it derives the installed capability directory
``manual`` reads back from the same two fields the boot installer uses. The
bundle's location and the ``.library/intrinsic/capabilities/system-manual/``
install path are unchanged.
"""
from __future__ import annotations

from .._plugin import INTRINSIC_SKILLS_PACKAGE, IntrinsicPlugin

SYSTEM_PLUGIN = IntrinsicPlugin(
    name="system",
    package=__package__,
    summary=(
        "Runtime, lifecycle, and identity — refresh/preset swap, self-sleep, "
        "karma-gated control of other agents, preset listing, true name and "
        "nickname."
    ),
    homepage="https://github.com/Lingtai-AI/lingtai-kernel",
    skill_name="system-manual",
    skill_package=INTRINSIC_SKILLS_PACKAGE,
    skill_dir="system-manual",
)

#: System's own public actions, in stable model-facing order — the
#: pre-migration enum order, unchanged. The reserved ``manual`` action is
#: appended by the plugin, never declared here.
SYSTEM_DECLARED_ACTIONS: tuple[str, ...] = (
    "refresh",
    "sleep",
    "lull",
    "interrupt",
    "suspend",
    "cpr",
    "clear",
    "nirvana",
    "presets",
    "name_set",
    "name_nickname",
)

#: The complete public action list, declared actions followed by ``manual``.
SYSTEM_ACTIONS: tuple[str, ...] = SYSTEM_PLUGIN.actions(SYSTEM_DECLARED_ACTIONS)
