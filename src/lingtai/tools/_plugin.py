"""Local-tool plugin packaging: one package owns its skill, its family, its mount.

A built-in model-facing tool is not just a module ``registry.setup_capability``
happens to import. It is a *plugin-style package*: the same folder ships the
implementation, the ``manual/`` skill bundle the kernel installs into the
agent's library, and the capability declaration the built-in registry publishes
for it. This module is the small shared piece that binds those three together
for one package, so a local tool cannot drift into declaring its module in one
place, its manual in another, and a public action list that silently disagrees
with both.

It is the ``lingtai.tools`` sibling of ``lingtai.mcp_servers._plugin``
(:class:`~lingtai.mcp_servers._plugin.CuratedMcpPlugin`), which does the same
job for a curated *MCP* package. The two are deliberately separate modules
because the import direction is one-way: ``mcp_servers`` may import
``lingtai.tools``, never the reverse (``tools/__init__.py`` "Import DAG").
Where the curated descriptor's mount declaration is a stdio launcher record,
this one's is a *capability* record — the shape ``tools/registry.py`` publishes.

Like its curated sibling it is **not** a plugin runtime. Nothing here discovers
packages, imports them by name, or reads configuration:
:data:`~lingtai.tools.registry.BUILTIN_TOOLS` / :data:`~lingtai.tools.registry.CORE_DEFAULTS`
remain the runtime source the host reads for what to boot, ``setup_capability``
remains the importer, ``Agent._install_intrinsic_manuals`` remains the installer
that copies ``manual/`` into ``.library/intrinsic/capabilities/<name>/``, and
``lingtai.services.plugin_registry`` still owns external Agent Plugins v1.0.0
directories. A :class:`LocalToolPlugin` is a declarative descriptor plus the
composition and mount helpers its own package calls explicitly.

The two hard promises it enforces:

1. **The reserved ``manual`` action** (``tools/CONTRACT.md`` "Every LingTai-owned
   family MUST offer a ``manual`` action"): a package declares only its *own*
   actions, and the plugin appends ``manual`` itself. A package cannot declare,
   re-schema, or hand in a handler for it — :meth:`LocalToolPlugin.build_family`
   takes an agent, never a child, and builds the manual child from the shared
   ``tool_family.manual`` builder bound to this plugin's own skill.
2. **The manual is the package's own skill.** The destination directory the
   plugin's ``manual`` action reads is *derived* from the package with the exact
   rule ``Agent._install_intrinsic_manuals`` uses, and is required to equal the
   public capability name. A package therefore cannot bind ``manual`` to another
   capability's installed skill, and a package whose ``manual/SKILL.md`` is
   missing, misnamed, or empty fails at import time rather than shipping a
   capability whose manual points somewhere else.
"""
from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any

from lingtai.kernel._frontmatter import strip_frontmatter

from . import _catalog
from .tool_family import RESERVED_MANUAL_NAME, ChildTool, ToolFamily
from .tool_family.manual import MANUAL_INPUT_SCHEMA, build_manual_child

__all__ = [
    "BUILTIN_SOURCE",
    "LIBRARY_CAPABILITIES_SEGMENTS",
    "MANUAL_ACTION",
    "MANUAL_DIRNAME",
    "SKILL_FILENAME",
    "LocalToolPlugin",
    "LocalToolPluginError",
    "manual_input_schema",
]

#: ``source`` stamped on every built-in capability declaration — the value that
#: tells a kernel-shipped tool apart from a ``plugin:<name>``-sourced Agent
#: Plugin component or a hand-registered one.
BUILTIN_SOURCE = "lingtai-builtin"

#: The reserved action name. Owned by ``lingtai.tools.tool_family``; re-exported
#: here so a tool package never spells the literal itself.
MANUAL_ACTION = RESERVED_MANUAL_NAME

#: The per-package skill bundle directory ``Agent._install_intrinsic_manuals``
#: copies. Everything inside it (sidecars included) is installed verbatim.
MANUAL_DIRNAME = "manual"

#: The skill catalog file inside :data:`MANUAL_DIRNAME`.
SKILL_FILENAME = "SKILL.md"

#: Where an installed capability manual lands under the agent working dir. The
#: same path ``tools/_manual.load_installed_manual`` reads, stated once here so
#: the descriptor can report the destination it owns without re-deriving it.
LIBRARY_CAPABILITIES_SEGMENTS = (".library", "intrinsic", "capabilities")

#: The only two implementation directories whose installed manual is published
#: under a different public name, transcribed from
#: ``Agent._install_intrinsic_manuals``. Retained implementation packages map to
#: their canonical model-facing name exactly once; every other package installs
#: under its own directory name.
_INSTALL_RENAMES = {"bash": "shell", "web_search": "web"}


class LocalToolPluginError(ValueError):
    """Raised for a local-tool packaging defect (bad descriptor or shape)."""


def manual_input_schema() -> dict[str, Any]:
    """A fresh copy of the generic reserved-``manual`` input schema.

    Deliberately a deep copy of ``tool_family.manual.MANUAL_INPUT_SCHEMA`` — the
    one owned definition — rather than a local near-copy, so a family composed
    through this plugin declares byte-for-byte the same strict-empty object the
    generic manual child dispatches.
    """
    return copy.deepcopy(MANUAL_INPUT_SCHEMA)


def _never_dispatches(_input: Mapping[str, Any]) -> dict[str, Any]:
    raise AssertionError("the schema-only plugin family never dispatches")


@dataclass(frozen=True)
class LocalToolPlugin:
    """One built-in tool package's identity, owned skill, and mount declaration.

    ``name`` is the capability name, the public tool/family name, and — because
    that is what ``Agent._install_intrinsic_manuals`` produces — the directory
    its manual installs into. ``package`` is the Python package that ships both
    the implementation and the ``manual/`` bundle; the two are required to agree
    under the installer's own rename rule, because :meth:`manual_child` binds
    the reserved ``manual`` action to ``name``'s installed skill. A descriptor
    whose package and name disagree would serve another capability's manual.

    The packaged skill is read once at construction and its frontmatter is
    checked against ``skill_name`` with the *catalog's* parser — the same one
    that will index the installed copy — so a package that renames, empties, or
    loses its manual fails loudly at import instead of shipping a capability
    whose ``manual`` action is degraded or foreign.
    """

    name: str
    package: str
    summary: str
    homepage: str
    skill_name: str
    default_on: bool = True
    default_kwargs: Mapping[str, Any] = field(default_factory=dict)

    # Read from the package's bundled manual/SKILL.md at construction. Excluded
    # from init/repr/eq: derived material, not declared identity.
    _skill_frontmatter: dict[str, str] = field(init=False, repr=False, compare=False)
    _skill_body: str = field(init=False, repr=False, compare=False)
    _skill_path: str = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        for attribute in ("name", "package", "summary", "homepage", "skill_name"):
            value = getattr(self, attribute)
            if not isinstance(value, str) or not value.strip():
                raise LocalToolPluginError(
                    f"LocalToolPlugin {attribute!r} must be a non-empty string"
                )
        if not isinstance(self.default_on, bool):
            raise LocalToolPluginError("LocalToolPlugin default_on must be a bool")
        if not isinstance(self.default_kwargs, Mapping):
            raise LocalToolPluginError(
                "LocalToolPlugin default_kwargs must be a mapping"
            )
        object.__setattr__(self, "default_kwargs", dict(self.default_kwargs))

        leaf = self.package.rpartition(".")[2]
        destination = _INSTALL_RENAMES.get(leaf, leaf)
        if destination != self.name:
            raise LocalToolPluginError(
                f"LocalToolPlugin package {self.package!r} installs its "
                f"{MANUAL_DIRNAME}/ as capability {destination!r}, not "
                f"{self.name!r}; the reserved {MANUAL_ACTION!r} action would "
                f"read another capability's installed skill"
            )

        frontmatter, body, path = self._load_packaged_skill()
        if frontmatter.get("name") != self.skill_name:
            raise LocalToolPluginError(
                f"LocalToolPlugin {self.name!r} packaged {MANUAL_DIRNAME}/"
                f"{SKILL_FILENAME} declares name {frontmatter.get('name')!r}, "
                f"expected {self.skill_name!r}"
            )
        if not frontmatter.get("description"):
            # The skills catalog rejects an entry with no description; a manual
            # that cannot be catalogued is not an owned skill.
            raise LocalToolPluginError(
                f"LocalToolPlugin {self.name!r} packaged {MANUAL_DIRNAME}/"
                f"{SKILL_FILENAME} has no frontmatter description"
            )
        if not body.strip():
            raise LocalToolPluginError(
                f"LocalToolPlugin {self.name!r} packaged {MANUAL_DIRNAME}/"
                f"{SKILL_FILENAME} has an empty body"
            )
        object.__setattr__(self, "_skill_frontmatter", frontmatter)
        object.__setattr__(self, "_skill_body", body)
        object.__setattr__(self, "_skill_path", path)

    def _load_packaged_skill(self) -> tuple[dict[str, str], str, str]:
        """Read ``<package>/manual/SKILL.md`` → (frontmatter, body, path).

        Frontmatter is parsed with ``tools._catalog.parse_frontmatter``, the
        parser the skills capability uses to index the *installed* copy, so
        "valid packaged skill" and "catalogable installed skill" are one
        statement. The body split uses the kernel-owned frontmatter primitive.
        """
        resource = resources.files(self.package).joinpath(
            MANUAL_DIRNAME, SKILL_FILENAME
        )
        try:
            text = resource.read_text(encoding="utf-8")
        except (OSError, FileNotFoundError) as e:
            raise LocalToolPluginError(
                f"LocalToolPlugin {self.name!r} has no packaged "
                f"{MANUAL_DIRNAME}/{SKILL_FILENAME}: {e}"
            ) from e
        return _catalog.parse_frontmatter(text), strip_frontmatter(text), str(resource)

    # -- the package's own skill -------------------------------------------

    @property
    def manual_dir(self) -> Path:
        """The packaged ``manual/`` bundle the kernel installer copies."""
        return Path(str(resources.files(self.package).joinpath(MANUAL_DIRNAME)))

    @property
    def skill_frontmatter(self) -> dict[str, str]:
        """Parsed packaged ``SKILL.md`` frontmatter (the catalog entry)."""
        return dict(self._skill_frontmatter)

    @property
    def skill_body(self) -> str:
        """The packaged ``SKILL.md`` markdown body, frontmatter stripped."""
        return self._skill_body

    @property
    def skill_path(self) -> str:
        """Absolute resolved path of the packaged ``SKILL.md``."""
        return self._skill_path

    def installed_manual_path(self, working_dir: Path | str) -> Path:
        """Where this plugin's skill lands for one agent, after install.

        The exact path ``tools/_manual.load_installed_manual`` reads for
        :attr:`name`, so the descriptor can state its own runtime manual source
        without a second derivation of the library layout.
        """
        return (
            Path(working_dir)
            .joinpath(*LIBRARY_CAPABILITIES_SEGMENTS)
            .joinpath(self.name, SKILL_FILENAME)
        )

    def manual_action_description(self) -> str:
        """The ``manual`` catalog line, built from the packaged skill.

        Advertises the owned skill's name and description in the model-facing
        tool description while the full body stays progressive-disclosure
        behind the ``manual`` action.
        """
        name = self._skill_frontmatter.get("name", self.skill_name)
        description = self._skill_frontmatter.get("description", "")
        return (
            f"Call {self.name}(action='{MANUAL_ACTION}', input={{}}, "
            f"reasoning='load the {self.name} manual') for the "
            f"progressive-disclosure usage manual (skill '{name}'): "
            f"{description}"
        ).strip()

    def describe(self, base: str) -> str:
        """One public tool description: the package's prose plus that line."""
        if not isinstance(base, str) or not base.strip():
            raise LocalToolPluginError(
                f"LocalToolPlugin {self.name!r} description must be non-empty"
            )
        return f"{base.strip()} {self.manual_action_description()}"

    def manual_child(self, agent: Any) -> ChildTool:
        """The plugin-owned reserved ``manual`` child for one agent.

        Built by the shared ``tool_family.manual`` builder against *this*
        plugin's capability name, so the action reads the package's own
        installed skill and no package-side handler can be substituted for it.
        """
        return build_manual_child(agent, self.name)

    def schema_only_manual_child(self) -> ChildTool:
        """The declared-but-never-dispatched ``manual`` child.

        For a module-level schema-only family built before any agent exists: it
        carries the identical strict-empty input schema (so the composed wire
        schema is the same object shape the dispatching family produces) and a
        handler that asserts rather than answering.
        """
        return ChildTool(
            MANUAL_ACTION,
            manual_input_schema(),
            _never_dispatches,
            title=f"{MANUAL_ACTION} input",
        )

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
        schemas[MANUAL_ACTION] = manual_input_schema()
        return schemas

    def build_family(
        self, declared: Sequence[ChildTool], agent: Any | None = None
    ) -> ToolFamily:
        """Compose this plugin's one public family, ``manual`` always appended.

        ``declared`` is the package's own children. ``agent`` decides which
        ``manual`` child the plugin appends: with an agent, the real one bound
        to the package's installed skill; without one, the schema-only child.
        The caller never supplies a ``manual`` child, which is what makes the
        action impossible to rebind from the package side.
        """
        self._check_declared_names([child.name for child in declared])
        manual = (
            self.manual_child(agent)
            if agent is not None
            else self.schema_only_manual_child()
        )
        return ToolFamily(self.name, [*declared, manual])

    def _check_declared_names(self, declared: "Sequence[str] | Any") -> None:
        names = list(declared)
        if not names:
            raise LocalToolPluginError(
                f"LocalToolPlugin {self.name!r} must declare at least one action"
            )
        if MANUAL_ACTION in names:
            raise LocalToolPluginError(
                f"LocalToolPlugin {self.name!r} must not declare the reserved "
                f"{MANUAL_ACTION!r} action; it is appended from the packaged "
                f"{MANUAL_DIRNAME}/{SKILL_FILENAME}"
            )
        if len(set(names)) != len(names):
            raise LocalToolPluginError(
                f"LocalToolPlugin {self.name!r} declared a duplicate action"
            )

    # -- shipped capability declaration + mount ----------------------------

    def capability_declaration(self) -> dict[str, Any]:
        """This package's built-in capability record, in registry shape.

        The same facts ``tools/registry.py`` publishes: which capability name
        resolves to which module (``BUILTIN_TOOLS``), whether it boots on every
        agent and with which kwargs (``CORE_DEFAULTS``), and which library
        directory its manual installs into. Returning it here registers and
        boots nothing: ``registry.py`` remains the runtime source the host
        reads, and this descriptor is what that entry must agree with.
        """
        return {
            "name": self.name,
            "module": self.package,
            "source": BUILTIN_SOURCE,
            "summary": self.summary,
            "homepage": self.homepage,
            "default_on": self.default_on,
            "default_kwargs": dict(self.default_kwargs),
            "manual_destination": self.name,
        }

    def mount(
        self,
        agent: Any,
        family: ToolFamily,
        handler: Any,
        description: str,
    ) -> None:
        """Register this plugin's one public tool on ``agent``. The mount point.

        The package supplies only what it owns — its composed family, the
        dispatch handler it wants registered, and its own prose. Name, wire
        schema, and glossary package come from the descriptor, so a mounted
        tool cannot be published under a name the declaration does not claim or
        with a glossary from another package.

        Three things are refused rather than mounted, because the boundary that
        makes a tool reachable is where the promises have to hold: a family
        that is not this plugin's, a family that has lost its reserved
        ``manual`` child, and a description that does not carry
        :meth:`manual_action_description` — a mounted tool whose model-facing
        text never mentions its own manual is a manual nobody can find. Compose
        the description with :meth:`describe`.
        """
        if not isinstance(family, ToolFamily):
            raise LocalToolPluginError(
                f"LocalToolPlugin {self.name!r} can only mount a ToolFamily"
            )
        if family.name != self.name:
            raise LocalToolPluginError(
                f"LocalToolPlugin {self.name!r} cannot mount family "
                f"{family.name!r} under its own name"
            )
        if not family.has_manual():
            raise LocalToolPluginError(
                f"LocalToolPlugin {self.name!r} cannot mount a family without "
                f"the reserved {MANUAL_ACTION!r} action"
            )
        if not callable(handler):
            raise LocalToolPluginError(
                f"LocalToolPlugin {self.name!r} mount handler must be callable"
            )
        if not isinstance(description, str) or (
            self.manual_action_description() not in description
        ):
            raise LocalToolPluginError(
                f"LocalToolPlugin {self.name!r} mount description must advertise "
                f"the packaged skill; compose it with describe()"
            )
        agent.add_tool(
            self.name,
            schema=family.build_schema(),
            handler=handler,
            description=description,
            glossary_package=self.package,
        )
