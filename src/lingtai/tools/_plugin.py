"""Built-in tool plugin packaging: one package owns its manual, actions, and mount record.

A built-in capability tool is not just a module ``registry.BUILTIN_TOOLS``
happens to name. It is a *plugin-style package*: the same folder ships the
handler code, the bundled ``manual/`` skill the agent library mounts, and the
capability record the host publishes for it. This module is the small shared
piece that binds those three together for one package, so a built-in tool
cannot drift into declaring its module path in one place, its manual in
another, and a public action list that silently disagrees with both.

It is the ``lingtai.tools`` twin of ``lingtai.mcp_servers._plugin`` — same
descriptor shape, same reserved-``manual`` promise — with the one difference
that matters for a built-in: an MCP package publishes a *launcher* record and
answers ``manual`` straight from its own wheel, while a built-in tool publishes
a *capability* record and answers ``manual`` from the copy the initializer
mounted into the agent's own ``.library``. Both facts are declared here, in one
place, by the package that owns them.

It deliberately is **not** a plugin runtime. Nothing here discovers packages,
imports them by name, spawns them, registers them, reads configuration, or
touches an agent's workdir. Capability activation, kwargs resolution, ordering,
supervision, and lifecycle all remain the host's: ``lingtai.tools.registry``
still owns ``BUILTIN_TOOLS``/``CORE_DEFAULTS``/``setup_capability`` and
``lingtai.agent`` still owns ``_install_intrinsic_manuals``. A
:class:`BuiltinToolPlugin` is a declarative descriptor plus three composition
helpers that its own package calls explicitly, and the shipped registry/
initializer stay the runtime source the host reads — this descriptor is what
those must agree with, proven by test rather than by generating them at import.

The one hard promise it enforces is the reserved ``manual`` action
(``tools/CONTRACT.md`` "Every LingTai-owned family MUST offer a ``manual``
action"): a package declares only its *own* actions, and this module appends
``manual`` itself, bound to the packaged skill's mounted destination. A package
that tries to declare, re-schema, or re-handle ``manual`` raises
:class:`BuiltinToolPluginError` at import time rather than shipping a family
whose manual is missing or points somewhere other than its own mounted skill.
"""
from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from importlib import resources
from typing import Any

from lingtai.kernel._frontmatter import split_frontmatter

from .tool_family import RESERVED_MANUAL_NAME, ChildTool, ToolFamily
from .tool_family.manual import MANUAL_INPUT_SCHEMA, build_manual_child

__all__ = [
    "BUILTIN_SOURCE",
    "INTRINSIC_CAPABILITIES_RELPATH",
    "MANUAL_ACTION",
    "MANUAL_BUNDLE_DIRNAME",
    "SKILL_FILENAME",
    "TOOLS_PACKAGE",
    "BuiltinToolPlugin",
    "BuiltinToolPluginError",
]

#: ``source`` stamped on every built-in capability record — the value that tells
#: a kernel-shipped capability apart from a ``plugin:<name>``-sourced external
#: Agent Plugin (``services/plugin_registry.py``) or a curated MCP
#: (``mcp_servers/_plugin.py``'s ``lingtai-curated``).
BUILTIN_SOURCE = "lingtai-builtin"

#: The reserved action name. Owned by ``lingtai.tools.tool_family``; re-exported
#: here so a tool package never spells the literal itself.
MANUAL_ACTION = RESERVED_MANUAL_NAME

#: The package that owns every built-in tool; every descriptor's ``package``
#: must live under it.
TOOLS_PACKAGE = "lingtai.tools"

#: The per-package manual bundle directory ``Agent._install_intrinsic_manuals``
#: copies verbatim, and the skill file inside it.
MANUAL_BUNDLE_DIRNAME = "manual"
SKILL_FILENAME = "SKILL.md"

#: Where that bundle lands inside an agent's working directory. The trailing
#: path component is the *public* capability name, not the implementation
#: package — which is why the descriptor carries both.
INTRINSIC_CAPABILITIES_RELPATH = ".library/intrinsic/capabilities"


class BuiltinToolPluginError(ValueError):
    """Raised for a built-in tool packaging defect (bad descriptor or shape)."""


@dataclass(frozen=True)
class BuiltinToolPlugin:
    """One built-in tool package's identity, packaged manual, and mount record.

    ``name`` is the public capability name, the registered model-facing tool
    name, the family name, and the directory the packaged manual is mounted
    under in an agent's ``.library``. ``package`` is the Python package that
    ships the handler code and the ``manual/`` bundle, and ``implementation``
    is that package's last component — the directory
    ``Agent._install_intrinsic_manuals`` scans. The two are stated separately
    because the kernel deliberately mounts some packages under a different
    public name (``bash`` → ``shell``, ``web_search`` → ``web``); a descriptor
    that collapsed them could not describe those tools at all, and one whose
    ``implementation`` disagreed with its own ``package`` would advertise a
    manual source belonging to a different tool.

    The bundled skill is loaded once at construction and its frontmatter
    ``name`` is checked against ``manual_skill_name``, so a package that
    renames or loses its manual fails loudly at import instead of serving an
    empty or foreign ``manual``.
    """

    name: str
    package: str
    implementation: str
    summary: str
    manual_skill_name: str

    # Loaded from the package's bundled manual/SKILL.md at construction.
    # Excluded from init/repr/eq: derived material, not declared identity.
    _skill_frontmatter: dict[str, str] = field(init=False, repr=False, compare=False)
    _skill_body: str = field(init=False, repr=False, compare=False)
    _skill_path: str = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        for attribute in (
            "name", "package", "implementation", "summary", "manual_skill_name",
        ):
            value = getattr(self, attribute)
            if not isinstance(value, str) or not value.strip():
                raise BuiltinToolPluginError(
                    f"BuiltinToolPlugin {attribute!r} must be a non-empty string"
                )
        if not self.package.startswith(f"{TOOLS_PACKAGE}."):
            raise BuiltinToolPluginError(
                f"BuiltinToolPlugin package {self.package!r} must live under "
                f"{TOOLS_PACKAGE!r} so the capability registry can import it"
            )
        if self.package.rpartition(".")[2] != self.implementation:
            raise BuiltinToolPluginError(
                f"BuiltinToolPlugin package {self.package!r} must be the "
                f"{self.implementation!r} module so its declared manual source "
                f"is its own bundle"
            )
        frontmatter, body, path = self._load_packaged_skill()
        if frontmatter.get("name") != self.manual_skill_name:
            raise BuiltinToolPluginError(
                f"BuiltinToolPlugin {self.name!r} bundled {SKILL_FILENAME} declares "
                f"name {frontmatter.get('name')!r}, expected {self.manual_skill_name!r}"
            )
        if not body.strip():
            raise BuiltinToolPluginError(
                f"BuiltinToolPlugin {self.name!r} bundled {SKILL_FILENAME} "
                f"has an empty body"
            )
        object.__setattr__(self, "_skill_frontmatter", frontmatter)
        object.__setattr__(self, "_skill_body", body)
        object.__setattr__(self, "_skill_path", path)

    def _load_packaged_skill(self) -> tuple[dict[str, str], str, str]:
        """Read this package's own ``manual/SKILL.md`` → (frontmatter, body, path)."""
        try:
            resource = resources.files(self.package).joinpath(
                MANUAL_BUNDLE_DIRNAME, SKILL_FILENAME
            )
            text = resource.read_text(encoding="utf-8")
        except (FileNotFoundError, ModuleNotFoundError, OSError) as e:
            raise BuiltinToolPluginError(
                f"BuiltinToolPlugin {self.name!r} cannot read its bundled "
                f"{MANUAL_BUNDLE_DIRNAME}/{SKILL_FILENAME}: {e}"
            ) from e
        frontmatter, body = split_frontmatter(text)
        return frontmatter, body, str(resource)

    # -- packaged skill / mount contract -----------------------------------

    @property
    def skill_frontmatter(self) -> dict[str, str]:
        """Parsed packaged ``SKILL.md`` frontmatter (the manual's catalog entry)."""
        return self._skill_frontmatter

    @property
    def skill_body(self) -> str:
        """The packaged ``SKILL.md`` markdown body the initializer mounts."""
        return self._skill_body

    @property
    def skill_path(self) -> str:
        """Absolute resolved path of the packaged ``manual/SKILL.md``."""
        return self._skill_path

    def packaged_manual_relpath(self) -> str:
        """Repo-relative source of the manual bundle the initializer copies."""
        return (
            f"src/{self.package.replace('.', '/')}/{MANUAL_BUNDLE_DIRNAME}"
        )

    def mounted_manual_relpath(self) -> str:
        """Workdir-relative destination the mounted manual is read back from.

        The exact path ``tools/_manual.load_installed_manual`` composes for
        this plugin's :attr:`name`, and therefore the path ``action='manual'``
        reports to the model.
        """
        return f"{INTRINSIC_CAPABILITIES_RELPATH}/{self.name}/{SKILL_FILENAME}"

    # -- family composition -------------------------------------------------

    def manual_input_schema(self) -> dict[str, Any]:
        """A fresh copy of the one shared strict-empty ``manual`` input schema."""
        # Deep copy for the same reason ``build_manual_child`` does it: a shallow
        # one would share the nested ``properties`` map across every family.
        return copy.deepcopy(MANUAL_INPUT_SCHEMA)

    def manual_child(self, agent: Any) -> ChildTool:
        """The plugin-owned reserved ``manual`` child.

        Bound to this descriptor's :attr:`name` — the mounted destination of
        its own packaged bundle — so ``manual`` never routes through the
        package's business manager and cannot be rebound to another tool's
        skill. ``agent`` may be ``None`` for a schema-only family, exactly as
        it may be for :func:`~lingtai.tools.tool_family.manual.build_manual_child`;
        such a family never dispatches.
        """
        return build_manual_child(agent, self.name)

    def actions(self, declared: Sequence[str]) -> tuple[str, ...]:
        """Declared actions plus the reserved ``manual``, in that order."""
        self._check_declared_names(declared)
        return tuple(declared) + (MANUAL_ACTION,)

    def action_input_schemas(
        self, declared: Sequence[tuple[str, Mapping[str, Any]]]
    ) -> tuple[tuple[str, dict[str, Any]], ...]:
        """Declared ``input`` schemas plus the reserved ``manual`` schema, in order.

        Ordered pairs rather than a mapping because this sequence *is* the
        model-facing enum order and the ``input`` branch order of the composed
        schema, not an incidental lookup table.
        """
        self._check_declared_names([action for action, _ in declared])
        return (
            *((action, dict(schema)) for action, schema in declared),
            (MANUAL_ACTION, self.manual_input_schema()),
        )

    def build_family(self, declared: Sequence[ChildTool], agent: Any) -> ToolFamily:
        """Compose this plugin's one public family, manual always appended."""
        self._check_declared_names([child.name for child in declared])
        return ToolFamily(self.name, [*declared, self.manual_child(agent)])

    def _check_declared_names(self, declared: Sequence[str]) -> None:
        names = list(declared)
        if not names:
            raise BuiltinToolPluginError(
                f"BuiltinToolPlugin {self.name!r} must declare at least one action"
            )
        if MANUAL_ACTION in names:
            raise BuiltinToolPluginError(
                f"BuiltinToolPlugin {self.name!r} must not declare the reserved "
                f"{MANUAL_ACTION!r} action; it is appended from the packaged "
                f"{MANUAL_BUNDLE_DIRNAME}/{SKILL_FILENAME}"
            )
        if len(set(names)) != len(names):
            raise BuiltinToolPluginError(
                f"BuiltinToolPlugin {self.name!r} declared a duplicate action"
            )

    # -- shipped capability declaration -------------------------------------

    def capability_declaration(self) -> dict[str, Any]:
        """This package's built-in capability record, in host-registry shape.

        ``module`` is exactly what ``registry.BUILTIN_TOOLS[name]`` must hold
        (the path ``setup_capability`` imports), and ``manual_source`` /
        ``manual_mount`` are exactly the copy ``Agent._install_intrinsic_manuals``
        performs for this package. Returning them here registers and mounts
        nothing: the shipped registry and initializer remain the runtime source
        the host reads, and this descriptor is what they must agree with.
        """
        return {
            "name": self.name,
            "summary": self.summary,
            "module": self.package,
            "source": BUILTIN_SOURCE,
            "manual_skill": self.manual_skill_name,
            "manual_source": self.packaged_manual_relpath(),
            "manual_mount": self.mounted_manual_relpath(),
        }
