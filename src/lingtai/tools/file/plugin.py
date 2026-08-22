"""The ``file`` tool plugin descriptor.

One place where this package states who it is: its public capability/family
name, the module the built-in registry resolves for it, its boot defaults and
provider metadata, the bundled ``manual/SKILL.md`` its ``manual`` action
returns, and the actions it *itself* owns. ``manual`` is deliberately absent
from :data:`FILE_DECLARED_ACTIONS` —
:class:`~lingtai.tools._plugin.ToolPlugin` appends the reserved action from the
packaged skill and rejects any attempt to declare it here.

``__init__.py`` consumes this for the public schema, the dispatching family, the
``PROVIDERS`` mapping, and the ``setup()`` mount. The registry entries
``BUILTIN_TOOLS["file"]`` / ``CORE_DEFAULTS["file"]`` and the manual destination
``Agent._install_intrinsic_manuals`` writes this package's ``manual/`` bundle
into must equal
:meth:`~lingtai.tools._plugin.ToolPlugin.capability_declaration`; those host
tables and that install sweep stay the runtime source the host reads.
"""
from __future__ import annotations

from .._plugin import ToolPlugin

FILE_PLUGIN = ToolPlugin(
    name="file",
    package=__package__,
    module_dir="file",
    summary="Unified file capability over one working tree — read, write, edit, glob, grep.",
    skill_name="file-manual",
    # ``file`` boots on every agent with no configuration: it needs no provider,
    # no credentials, and no policy file. This is the ``CORE_DEFAULTS`` entry.
    defaults={},
    # One built-in implementation over the injected ``agent._file_io`` service;
    # there is no provider matrix to choose from.
    providers={"providers": [], "default": "builtin"},
)

#: The file family's own public actions, in stable model-facing order. The
#: reserved ``manual`` action is appended by the plugin, never declared here.
FILE_DECLARED_ACTIONS: tuple[str, ...] = ("read", "write", "edit", "glob", "grep")

#: The complete public action list, declared actions followed by ``manual``.
FILE_ACTIONS: tuple[str, ...] = FILE_PLUGIN.actions(FILE_DECLARED_ACTIONS)
