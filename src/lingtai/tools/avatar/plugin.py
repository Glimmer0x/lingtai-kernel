"""The Avatar built-in tool plugin descriptor.

One place where this package states who it is: its capability/tool name, the
module the capability registry imports for it, the always-on boot kwargs the
registry's ``CORE_DEFAULTS`` carries, the bundled ``manual/SKILL.md`` its
``manual`` action returns, and the actions it *itself* owns. ``manual`` is
deliberately absent from :data:`AVATAR_DECLARED_ACTIONS` —
:class:`~lingtai.tools._plugin.BuiltinToolPlugin` appends the reserved action
from the packaged skill and rejects any attempt to declare it here.

``__init__.py`` consumes this for the public schema, the family composition, the
model-facing description, and the one ``add_tool`` registration ``setup()``
performs. The shipped ``lingtai.tools.registry`` entries for ``avatar`` must
equal :meth:`~lingtai.tools._plugin.BuiltinToolPlugin.capability_declaration`;
the registry mapping itself stays the runtime source the host reads and lazily
imports, so importing the registry never imports this package.

This is a *kernel-shipped built-in* plugin package. It has nothing to do with
``lingtai.tools.plugin``, the read-only catalog tool for external Agent Plugins
v1.0.0 directories that ``lingtai.services.plugin_registry`` mounts.
"""
from __future__ import annotations

from .._plugin import BuiltinToolPlugin

AVATAR_PLUGIN = BuiltinToolPlugin(
    name="avatar",
    package=__package__,
    summary=(
        "Spawn independent peer agents (分身) as detached processes and "
        "distribute rules across the avatar subtree."
    ),
    skill_name="avatar-manual",
    # Avatar boots on every agent with no configuration — the registry's
    # CORE_DEFAULTS entry this must agree with is the empty mapping.
    default_kwargs={},
)

#: Avatar's own public actions, in stable model-facing order. The reserved
#: ``manual`` action is appended by the plugin, never declared here.
AVATAR_DECLARED_ACTIONS: tuple[str, ...] = ("spawn", "rules")

#: The complete public action list, declared actions followed by ``manual``.
AVATAR_ACTIONS: tuple[str, ...] = AVATAR_PLUGIN.actions(AVATAR_DECLARED_ACTIONS)

#: The model-facing root description. Terse by design: the safety contract lives
#: in the strict per-action ``input`` schemas plus the packaged manual, not in a
#: long description string. The manual pointer is the plugin's own skill name,
#: so a renamed skill cannot leave the description advertising a dead pointer.
AVATAR_DESCRIPTION = (
    "Spawn an independent agent (他我), set network rules for descendants, "
    "or read the avatar manual. Requires an explicit action — no default. "
    "avatar(action='spawn', input={'name': 'researcher', ...}, "
    "reasoning='<the avatar's mission>'): inherits init.json, boots on "
    "default preset; your reasoning becomes the avatar's first prompt. "
    "avatar(action='rules', input={'rules_content': '...'}, reasoning='...'): "
    "distribute rules to self + all descendants (requires karma). "
    f"avatar(action='manual', input={{}}, reasoning='...'): return the "
    f"{AVATAR_PLUGIN.skill_name} skill body. See {AVATAR_PLUGIN.skill_name} "
    "skill for full guidance."
)
