"""Intrinsic tool plugin packaging: one package owns its skill, declaration, and family shape.

A model-facing LingTai tool is not just a module the registry happens to wire
onto an agent. It is a *plugin-style package*: the same folder ships the tool
code, the bundled ``manual/`` skill bundle the agent reads, and the registration
declaration the built-in registry publishes for it. This module is the small
shared piece that binds those three together for one package, so a tool cannot
drift into declaring its registration in one place, its manual in another, and a
public action list that silently disagrees with both.

It is the model-facing twin of ``lingtai.mcp_servers._plugin`` — same shape,
same discipline, different host. Where a curated MCP publishes a stdio launcher
into ``mcp_catalog.json`` and reads its own packaged ``SKILL.md`` out-of-process,
an intrinsic tool publishes a registry entry into
``lingtai.tools.registry.INTRINSICS`` and its packaged ``manual/`` bundle is
*installed* by the host into the agent's working directory first. That
difference is deliberate and preserved: :meth:`IntrinsicToolPlugin.manual_child`
still reads the **installed** copy through the shared
``tool_family.manual.build_manual_child`` loader, because the agent's own
``.library/intrinsic/capabilities/<skill>/SKILL.md`` — not a wheel-internal
resource — is what the model is told the path of.

Like its MCP twin it deliberately is **not** a plugin runtime. Nothing here
discovers packages, imports them by name, boots them, registers them, installs
anything, or reads configuration: activation, capability setup, manual
installation, prompt composition, and lifecycle all remain the host's.
``lingtai.tools.registry`` still owns the intrinsic mapping and the capability
registry, ``lingtai.agent.Agent._install_intrinsic_manuals`` still owns the wipe
-and-rewrite of ``.library/intrinsic/``, and ``lingtai.services.plugin_registry``
still owns external Agent Plugins v1.0.0 directories. An
:class:`IntrinsicToolPlugin` is a declarative descriptor plus three composition
helpers that its own package calls explicitly.

The one hard promise it enforces is the reserved ``manual`` action
(``tools/CONTRACT.md`` "Every LingTai-owned family MUST offer a ``manual``
action"): a package declares only its *own* actions, and this module appends
``manual`` itself, bound to the package's own bundled skill name. A package that
tries to declare, re-schema, or re-handle ``manual`` raises
:class:`IntrinsicToolPluginError` at import time rather than shipping a family
whose manual is missing or points somewhere other than its packaged bundle.
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
    "INTRINSIC_SOURCE",
    "MANUAL_ACTION",
    "MANUAL_BUNDLE_DIRNAME",
    "MANUAL_INSTALL_ROOT",
    "SKILL_FILENAME",
    "IntrinsicToolPlugin",
    "IntrinsicToolPluginError",
    "strict_empty_input_schema",
]

#: ``source`` stamped on every intrinsic registration record — the value that
#: tells a kernel-shipped model-facing tool apart from a ``plugin:<name>``-sourced
#: Agent Plugin or a hand-registered MCP family.
INTRINSIC_SOURCE = "lingtai-intrinsic"

#: The reserved action name. Owned by ``lingtai.tools.tool_family``; re-exported
#: here so a tool package never spells the literal itself.
MANUAL_ACTION = RESERVED_MANUAL_NAME

#: The packaged skill-bundle directory every tool plugin ships, and the one
#: ``Agent._install_intrinsic_manuals``'s ``install_from`` scan looks for.
MANUAL_BUNDLE_DIRNAME = "manual"

#: The bundle's entry document. Sidecars (``assets/``, ``reference/<name>/``)
#: are discovered by following relative paths documented inside it, never by a
#: structured list on this descriptor — the same minimal contract the curated
#: MCP manuals keep.
SKILL_FILENAME = "SKILL.md"

#: Where the host installs a mounted bundle inside the agent's working
#: directory. Declared here so a descriptor can state the full mount it expects
#: and a test can pin it against what the host actually writes.
MANUAL_INSTALL_ROOT = ".library/intrinsic/capabilities"


class IntrinsicToolPluginError(ValueError):
    """Raised for an intrinsic-tool packaging defect (bad descriptor or shape)."""


def strict_empty_input_schema() -> dict[str, Any]:
    """The canonical closed, argument-free ``input`` schema for an action.

    A deep copy of the one owned ``MANUAL_INPUT_SCHEMA`` literal rather than a
    second spelling of it, so a plugin-composed schema and the child that
    dispatches it cannot drift.
    """
    return copy.deepcopy(MANUAL_INPUT_SCHEMA)


@dataclass(frozen=True)
class IntrinsicToolPlugin:
    """One model-facing tool package's identity, packaged skill, and registration.

    ``name`` is the registry key and the public family/root name; ``package`` is
    the Python package that ships both the tool module and the ``manual/``
    bundle behind the reserved ``manual`` action. The two are required to agree
    (``package`` must end in ``name``) because :meth:`intrinsic_declaration`
    publishes ``package`` as this plugin's implementation module — a descriptor
    whose module and registry name disagree would advertise an implementation
    for something else.

    ``skill_name`` is the bundle's own name: the packaged ``SKILL.md``
    frontmatter ``name``, the directory the host installs it into under
    ``.library/intrinsic/capabilities/``, and therefore the name the ``manual``
    child loads. It is deliberately *not* required to equal ``name``: this
    tool's manual has been the long-established ``context-manual`` skill in
    every prompt, every cross-manual reference, and the rendered skills catalog,
    and packaging it into its owning tool must not rename it.

    The bundled skill is loaded once at construction and its frontmatter
    ``name`` is checked against ``skill_name``, so a package that renames or
    loses its manual fails loudly at import instead of shipping a tool whose
    ``manual`` action resolves to nothing.
    """

    name: str
    package: str
    summary: str
    homepage: str
    skill_name: str

    # Loaded from the package's bundled manual/SKILL.md at construction.
    # Excluded from init/repr/eq: derived material, not declared identity.
    _skill_frontmatter: dict[str, str] = field(init=False, repr=False, compare=False)
    _skill_body: str = field(init=False, repr=False, compare=False)
    _skill_path: str = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        for attribute in ("name", "package", "summary", "homepage", "skill_name"):
            value = getattr(self, attribute)
            if not isinstance(value, str) or not value.strip():
                raise IntrinsicToolPluginError(
                    f"IntrinsicToolPlugin {attribute!r} must be a non-empty string"
                )
        if self.package.rpartition(".")[2] != self.name:
            raise IntrinsicToolPluginError(
                f"IntrinsicToolPlugin package {self.package!r} must be the "
                f"{self.name!r} module so its declared implementation is its own module"
            )
        try:
            resource = resources.files(self.package).joinpath(
                MANUAL_BUNDLE_DIRNAME, SKILL_FILENAME
            )
            text = resource.read_text(encoding="utf-8")
        except (FileNotFoundError, ModuleNotFoundError, NotADirectoryError) as exc:
            raise IntrinsicToolPluginError(
                f"IntrinsicToolPlugin {self.name!r} ships no "
                f"{MANUAL_BUNDLE_DIRNAME}/{SKILL_FILENAME} in {self.package!r}"
            ) from exc
        frontmatter, body = split_frontmatter(text)
        if frontmatter.get("name") != self.skill_name:
            raise IntrinsicToolPluginError(
                f"IntrinsicToolPlugin {self.name!r} bundled {SKILL_FILENAME} "
                f"declares name {frontmatter.get('name')!r}, expected {self.skill_name!r}"
            )
        if not body.strip():
            raise IntrinsicToolPluginError(
                f"IntrinsicToolPlugin {self.name!r} bundled {SKILL_FILENAME} has an empty body"
            )
        object.__setattr__(self, "_skill_frontmatter", frontmatter)
        object.__setattr__(self, "_skill_body", body)
        object.__setattr__(self, "_skill_path", str(resource))

    # -- packaged skill / manual ------------------------------------------

    @property
    def skill_frontmatter(self) -> dict[str, str]:
        """Parsed packaged ``SKILL.md`` frontmatter (the manual's catalog entry)."""
        return self._skill_frontmatter

    @property
    def skill_body(self) -> str:
        """The packaged ``SKILL.md`` markdown body the host installs verbatim."""
        return self._skill_body

    @property
    def skill_path(self) -> str:
        """Absolute resolved path of the packaged ``SKILL.md`` inside the wheel."""
        return self._skill_path

    def manual_child(self, agent: Any) -> ChildTool:
        """The plugin-owned reserved ``manual`` child, bound to one agent.

        Deliberately delegates to the shared ``build_manual_child`` loader, so
        the child answers from the **installed** bundle in the agent's own
        working directory — the copy whose ``manual_path`` the model is given
        and can read. The plugin's contribution is that the skill name it is
        bound to is the descriptor's, so no handler edit can point ``manual`` at
        another package's document.
        """
        return build_manual_child(agent, self.skill_name)

    def manual_mount(self) -> dict[str, Any]:
        """The mount this package's bundle expects from the host installer.

        The record shape ``Agent._install_intrinsic_manuals`` materializes:
        the ``manual/`` bundle in *this* package, copied to
        ``.library/intrinsic/capabilities/<skill_name>/`` in the agent's working
        directory. Returning it here installs nothing — the host's wipe-and-
        rewrite remains the runtime source; this is what that install must agree
        with.
        """
        return {
            "package": self.package,
            "bundle": f"{MANUAL_BUNDLE_DIRNAME}/",
            "install_root": MANUAL_INSTALL_ROOT,
            "installed_dir": self.skill_name,
            "skill": self.skill_name,
        }

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

    def build_family(self, declared: Sequence[ChildTool], agent: Any) -> ToolFamily:
        """Compose this plugin's one public family, manual always appended.

        ``agent`` may be ``None`` for a schema-only family whose children are
        never dispatched — the manual child's own schema does not depend on it.
        """
        self._check_declared_names([child.name for child in declared])
        return ToolFamily(self.name, [*declared, self.manual_child(agent)])

    def _check_declared_names(self, declared: "Sequence[str] | Any") -> None:
        names = list(declared)
        if not names:
            raise IntrinsicToolPluginError(
                f"IntrinsicToolPlugin {self.name!r} must declare at least one action"
            )
        if MANUAL_ACTION in names:
            raise IntrinsicToolPluginError(
                f"IntrinsicToolPlugin {self.name!r} must not declare the reserved "
                f"{MANUAL_ACTION!r} action; it is appended from the packaged "
                f"{MANUAL_BUNDLE_DIRNAME}/{SKILL_FILENAME}"
            )
        if len(set(names)) != len(names):
            raise IntrinsicToolPluginError(
                f"IntrinsicToolPlugin {self.name!r} declared a duplicate action"
            )

    # -- shipped registration declaration ----------------------------------

    def intrinsic_declaration(self) -> dict[str, Any]:
        """This package's built-in registration record, in registry shape.

        The facts ``lingtai.tools.registry.INTRINSICS`` publishes for this tool:
        the public root name and the module that implements it. Returning it
        here does not register or boot anything — ``registry.INTRINSICS`` stays
        the mapping ``BaseAgent._wire_intrinsics`` reads, and this descriptor is
        what that entry must agree with.
        """
        return {
            "name": self.name,
            "module": self.package,
            "source": INTRINSIC_SOURCE,
            "summary": self.summary,
            "homepage": self.homepage,
        }
