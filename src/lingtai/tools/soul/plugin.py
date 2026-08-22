"""The Soul intrinsic-tool plugin descriptor.

One place where this package states who it is: its intrinsic-registry name, the
bundled ``manual/SKILL.md`` it owns, the directory that skill installs into
under ``.library/intrinsic/capabilities/``, and the actions it *itself* owns.
``manual`` is deliberately absent from :data:`SOUL_DECLARED_ACTIONS` —
:class:`~lingtai.tools._plugin.IntrinsicToolPlugin` appends the reserved action
bound to this package's own installed skill and rejects any attempt to declare
it here.

``__init__.py`` consumes this for the public schema, the dispatch family, and
the reserved manual child; ``lingtai.tools.registry`` must publish exactly
:meth:`~lingtai.tools._plugin.IntrinsicToolPlugin.intrinsic_declaration` for
``soul``, and ``Agent._install_intrinsic_manuals`` must materialize exactly
:meth:`~lingtai.tools._plugin.IntrinsicToolPlugin.manual_mount_declaration`.
Those two remain the runtime sources the host reads; this descriptor is what
they must agree with.

The manual moved here from ``lingtai.intrinsic_skills/soul-manual/`` — it was a
standalone bundle for a tool that plainly owns it. ``mount_name`` keeps the
installed directory (and therefore every ``manual_path`` the model has ever
seen) at ``soul-manual``: where the skill is *authored* is this package's
business, where it *lands* is a promise to the agent.
"""
from __future__ import annotations

from .._plugin import IntrinsicToolPlugin

SOUL_PLUGIN = IntrinsicToolPlugin(
    name="soul",
    package=__package__,
    summary="Inner voice — self-inquiry, soul-flow cadence, and the flow voice.",
    skill_name="soul-manual",
    mount_name="soul-manual",
)

#: Soul's own public actions, in stable model-facing order — the pre-plugin
#: order of the family's children, unchanged. The reserved ``manual`` action is
#: appended by the plugin, never declared here.
SOUL_DECLARED_ACTIONS: tuple[str, ...] = (
    "inquiry", "flow", "config", "voice", "dismiss",
)

#: The complete public action list, declared actions followed by ``manual``.
SOUL_ACTIONS: tuple[str, ...] = SOUL_PLUGIN.actions(SOUL_DECLARED_ACTIONS)
