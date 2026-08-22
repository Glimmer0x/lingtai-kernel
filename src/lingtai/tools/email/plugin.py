"""The Email intrinsic's plugin descriptor — one place this tool states who it is.

Email is a *real* Agent Plugin, not a tool that merely reads a bundled file: the
package ships ``agent_plugin/`` (an Agent Plugins v1.0.0 directory carrying
``plugin.json`` and ``skills/email-manual/SKILL.md``), and
:class:`~lingtai.tools._plugin.IntrinsicToolPlugin` validates it at import
through ``lingtai.services.plugin_registry.read_plugin`` — the same discovery
path a third-party plugin declared in ``manifest.plugins`` goes through. What
the plugin owns is the Email manual; what it deliberately does **not** own is a
launcher, because the ``email`` family executes in the host process.

``manual`` is deliberately absent from :data:`EMAIL_DECLARED_ACTIONS`: the
plugin appends the reserved action from its own skill and rejects any attempt to
declare it here. ``_family_schema.py`` consumes :data:`EMAIL_ACTIONS` for the
public enum and branch order, ``__init__.py`` for family composition and the
manual child, and ``tools/registry.py`` for the intrinsic's registered name.
"""
from __future__ import annotations

from .._plugin import IntrinsicToolPlugin

EMAIL_PLUGIN = IntrinsicToolPlugin(
    name="email",
    package=__package__,
    # The manifest name lives in the standard's global namespace, so it carries
    # the kernel's prefix; the tool the model calls stays ``email``.
    plugin_name="lingtai-email",
    skill_name="email-manual",
    # The host installs the owned skill under this name
    # (``.library/intrinsic/capabilities/email/``), which is the path Email's
    # pinned ``manual`` result has always reported.
    manual_skill="email",
    summary=(
        "LingTai internal email — filesystem mailbox, contacts, and delivery "
        "between agents in one .lingtai/ network."
    ),
)

#: Email's own public actions, in stable model-facing order — identical to the
#: pre-plugin ``ACTION_ORDER`` minus its trailing ``manual``, which the plugin
#: appends and no package may declare.
EMAIL_DECLARED_ACTIONS: tuple[str, ...] = (
    "send", "check", "read", "dismiss", "reply", "reply_all",
    "search", "archive", "delete",
    "contacts", "add_contact", "remove_contact", "edit_contact",
)

#: The complete public action list, declared actions followed by ``manual``.
EMAIL_ACTIONS: tuple[str, ...] = EMAIL_PLUGIN.actions(EMAIL_DECLARED_ACTIONS)
