"""Tool plugin packaging: one package owns its skill, declaration, and family shape.

A built-in LingTai tool is not just a directory the registry happens to import.
It is a *plugin-style package*: the same folder ships the operation code, the
bundled ``manual/SKILL.md`` the host installs into the agent's intrinsic
library, and the capability declaration the built-in registry publishes for it
(module path, boot defaults, provider metadata, manual destination). This module
is the small shared piece that binds those three together for one package, so a
tool cannot drift into declaring its module in one place, its manual in another,
and a public action list that silently disagrees with both.

It is the ``lingtai.tools`` twin of :mod:`lingtai.mcp_servers._plugin`, which
does the same job for a curated MCP package, and it keeps that module's
deliberate limits. It is **not** a plugin runtime. Nothing here discovers
packages, imports them by name, mounts them, registers them, or reads
configuration: capability activation, boot defaults, guard/execution policy,
prompt lifecycle, and the manual install sweep all remain the host's.
``lingtai.tools.registry`` still owns :data:`~lingtai.tools.registry.BUILTIN_TOOLS`
/ :data:`~lingtai.tools.registry.CORE_DEFAULTS` and ``setup_capability``,
``lingtai.agent.Agent._install_intrinsic_manuals`` still owns the
``.library/intrinsic/capabilities/`` sweep, and
``lingtai.services.plugin_registry`` still owns external Agent Plugins v1.0.0
directories. A :class:`ToolPlugin` is a declarative descriptor plus three
composition helpers that its own package calls explicitly.

The one hard promise it enforces is the reserved ``manual`` action
(``tools/CONTRACT.md`` "Every LingTai-owned family MUST offer a ``manual``
action"): a package declares only its *own* actions, and this module appends
``manual`` itself, bound to the destination the host installs this package's
bundled manual into. A package that tries to declare, re-schema, or re-handle
``manual`` raises :class:`ToolPluginError` at import time rather than shipping a
family whose manual is missing or points somewhere other than its packaged
skill.
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
    "MANUAL_ACTION",
    "MANUAL_BUNDLE_DIRNAME",
    "SKILL_FILENAME",
    "ToolPlugin",
    "ToolPluginError",
    "strict_empty_input_schema",
]

#: The reserved action name. Owned by ``lingtai.tools.tool_family``; re-exported
#: here so a tool package never spells the literal itself.
MANUAL_ACTION = RESERVED_MANUAL_NAME

#: The per-package manual bundle directory ``Agent._install_intrinsic_manuals``
#: scans for. Every tool package that owns its manual ships exactly this folder;
#: the host copies it to ``.library/intrinsic/capabilities/<destination>/``.
MANUAL_BUNDLE_DIRNAME = "manual"

#: The bundled manual document inside :data:`MANUAL_BUNDLE_DIRNAME`.
SKILL_FILENAME = "SKILL.md"


class ToolPluginError(ValueError):
    """Raised for a tool-plugin packaging defect (bad descriptor or shape)."""


def strict_empty_input_schema() -> dict[str, Any]:
    """The canonical closed, argument-free ``input`` schema for an action.

    A deep copy of the one ``tool_family.manual``-owned literal, so a family
    that *declares* this schema and the child that dispatches it cannot drift,
    and so no two callers share a mutable nested ``properties`` map.
    """
    return copy.deepcopy(MANUAL_INPUT_SCHEMA)


def _schema_only_manual_handler(_input: Mapping[str, Any]) -> dict[str, Any]:
    raise AssertionError("the agent-less schema-only manual child never dispatches")


@dataclass(frozen=True)
class ToolPlugin:
    """One built-in tool package's identity, packaged manual, and declaration.

    ``name`` is the public capability name, the model-facing family name, and —
    because that is exactly what ``Agent._install_intrinsic_manuals`` computes —
    the directory this package's manual bundle is installed into. ``package`` is
    the Python package that ships both the operation modules and the
    ``manual/SKILL.md`` the ``manual`` action returns, and ``module_dir`` is that
    package's own last path segment. The two are stated separately, and required
    to agree, because a retained implementation directory may differ from the
    canonical capability it serves (``lingtai.tools.bash`` → ``shell``,
    ``lingtai.tools.web_search`` → ``web``): the registry publishes
    ``package`` as this capability's module, and the installer maps
    ``module_dir`` onto ``name``.

    The bundled manual is loaded once at construction and its frontmatter
    ``name`` is checked against ``skill_name``, so a package that renames or
    loses its manual fails loudly at import instead of serving an empty or
    foreign ``manual``.
    """

    name: str
    package: str
    module_dir: str
    summary: str
    skill_name: str
    defaults: Mapping[str, Any] = field(default_factory=dict)
    providers: Mapping[str, Any] = field(default_factory=lambda: {"providers": [], "default": "builtin"})

    # Loaded from the package's bundled manual/SKILL.md at construction. Excluded
    # from init/repr/eq: they are derived material, not part of the descriptor's
    # declared identity.
    _skill_frontmatter: dict[str, str] = field(init=False, repr=False, compare=False)
    _skill_body: str = field(init=False, repr=False, compare=False)
    _skill_path: str = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        for attribute in ("name", "package", "module_dir", "summary", "skill_name"):
            value = getattr(self, attribute)
            if not isinstance(value, str) or not value.strip():
                raise ToolPluginError(
                    f"ToolPlugin {attribute!r} must be a non-empty string"
                )
        if self.package.rpartition(".")[2] != self.module_dir:
            raise ToolPluginError(
                f"ToolPlugin package {self.package!r} must be the "
                f"{self.module_dir!r} module so its declared capability module "
                f"is its own package"
            )
        for attribute in ("defaults", "providers"):
            if not isinstance(getattr(self, attribute), Mapping):
                raise ToolPluginError(f"ToolPlugin {attribute!r} must be a mapping")
        frontmatter, body, path = self._load_packaged_skill()
        if frontmatter.get("name") != self.skill_name:
            raise ToolPluginError(
                f"ToolPlugin {self.name!r} bundled "
                f"{MANUAL_BUNDLE_DIRNAME}/{SKILL_FILENAME} declares name "
                f"{frontmatter.get('name')!r}, expected {self.skill_name!r}"
            )
        if not body.strip():
            raise ToolPluginError(
                f"ToolPlugin {self.name!r} bundled "
                f"{MANUAL_BUNDLE_DIRNAME}/{SKILL_FILENAME} has an empty body"
            )
        object.__setattr__(self, "_skill_frontmatter", frontmatter)
        object.__setattr__(self, "_skill_body", body)
        object.__setattr__(self, "_skill_path", path)

    def _load_packaged_skill(self) -> tuple[dict[str, str], str, str]:
        resource = resources.files(self.package).joinpath(
            MANUAL_BUNDLE_DIRNAME, SKILL_FILENAME
        )
        try:
            text = resource.read_text(encoding="utf-8")
        except (FileNotFoundError, OSError) as exc:
            raise ToolPluginError(
                f"ToolPlugin {self.name!r} ships no "
                f"{MANUAL_BUNDLE_DIRNAME}/{SKILL_FILENAME} in {self.package!r}"
            ) from exc
        frontmatter, body = split_frontmatter(text)
        return frontmatter, body, str(resource)

    # -- packaged skill / manual ------------------------------------------

    @property
    def manual_destination(self) -> str:
        """Where the host installs this package's manual bundle.

        ``Agent._install_intrinsic_manuals`` copies ``<package>/manual/`` to
        ``.library/intrinsic/capabilities/<canonical capability name>/``, so the
        destination is the public :attr:`name` — never the retained
        implementation directory. The reserved ``manual`` child reads back from
        exactly this destination.
        """
        return self.name

    @property
    def skill_frontmatter(self) -> dict[str, str]:
        """Parsed packaged ``SKILL.md`` frontmatter (the manual's catalog entry)."""
        return dict(self._skill_frontmatter)

    @property
    def skill_body(self) -> str:
        """The full packaged ``SKILL.md`` markdown body behind ``action='manual'``."""
        return self._skill_body

    @property
    def skill_path(self) -> str:
        """Absolute resolved path of the packaged ``manual/SKILL.md``."""
        return self._skill_path

    def manual_child(self, agent: Any | None = None) -> ChildTool:
        """The plugin-owned reserved ``manual`` child.

        With an *agent*, the child is the kernel-owned
        :func:`~lingtai.tools.tool_family.manual.build_manual_child` bound to
        this plugin's declared :attr:`manual_destination`, so ``manual`` never
        routes through the package's business dispatcher and cannot be rebound
        to other material. The host boundary is unchanged: the body and the
        model-visible ``manual_path`` still come from the agent's own installed
        ``.library/intrinsic/capabilities/`` tree, not from a package read.

        Without an *agent* the child is schema-only — the same strict-empty
        input with a handler that raises — which is what a package's
        module-level schema composition uses before any agent exists.
        """
        if agent is None:
            return ChildTool(
                name=MANUAL_ACTION,
                input_schema=strict_empty_input_schema(),
                handler=_schema_only_manual_handler,
                title=f"{MANUAL_ACTION} input",
            )
        return build_manual_child(agent, self.manual_destination)

    # -- family composition -------------------------------------------------

    def actions(self, declared: Sequence[str]) -> tuple[str, ...]:
        """Declared actions plus the reserved ``manual``, in that order."""
        self._check_declared_names(declared)
        return tuple(declared) + (MANUAL_ACTION,)

    def action_input_schemas(
        self, declared: Mapping[str, Mapping[str, Any]]
    ) -> dict[str, dict[str, Any]]:
        """Declared ``input`` schemas plus the reserved ``manual`` schema."""
        self._check_declared_names(declared.keys())
        schemas: dict[str, dict[str, Any]] = {
            action: dict(schema) for action, schema in declared.items()
        }
        schemas[MANUAL_ACTION] = strict_empty_input_schema()
        return schemas

    def build_family(
        self, declared: Sequence[ChildTool], agent: Any | None = None
    ) -> ToolFamily:
        """Compose this plugin's one public family, manual always appended."""
        self._check_declared_names([child.name for child in declared])
        return ToolFamily(self.name, [*declared, self.manual_child(agent)])

    def _check_declared_names(self, declared: "Sequence[str] | Any") -> None:
        names = list(declared)
        if not names:
            raise ToolPluginError(
                f"ToolPlugin {self.name!r} must declare at least one action"
            )
        if MANUAL_ACTION in names:
            raise ToolPluginError(
                f"ToolPlugin {self.name!r} must not declare the reserved "
                f"{MANUAL_ACTION!r} action; it is appended from the packaged "
                f"{MANUAL_BUNDLE_DIRNAME}/{SKILL_FILENAME}"
            )
        if len(set(names)) != len(names):
            raise ToolPluginError(
                f"ToolPlugin {self.name!r} declared a duplicate action"
            )

    # -- shipped capability declaration ------------------------------------

    def capability_declaration(self) -> dict[str, Any]:
        """This package's built-in capability record, in registry record shape.

        The four facts the host publishes about a built-in tool, in one place:
        the module ``registry.BUILTIN_TOOLS`` resolves for this capability, the
        boot kwargs ``registry.CORE_DEFAULTS`` seeds it with, the provider
        metadata ``registry.get_all_providers`` reads off the module, and the
        ``.library/intrinsic/capabilities/`` directory the manual installer
        writes this package's bundle into.

        Returning it here does not register, mount, or activate anything: the
        registry tables remain the runtime source the host reads and
        ``setup_capability``/``_install_intrinsic_manuals`` remain the only
        mount paths. This descriptor is what those entries must agree with.
        """
        return {
            "name": self.name,
            "module": self.package,
            "defaults": dict(self.defaults),
            "providers": self.providers_declaration(),
            "manual_destination": self.manual_destination,
        }

    def providers_declaration(self) -> dict[str, Any]:
        """The module-level ``PROVIDERS`` mapping ``get_all_providers`` reads."""
        return copy.deepcopy(dict(self.providers))
