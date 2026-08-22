"""Intrinsic-tool plugin packaging: a host tool that is a *real* Agent Plugin.

``mcp_servers/_plugin.py`` did this for curated MCP servers — one package owns
its server code, its bundled ``SKILL.md``, and the stdio declaration the curated
catalog publishes for it. This module is the same idea for a tool that runs
**inside the host process** rather than behind a subprocess: a tool package
ships an Agent Plugins v1.0.0 directory (``plugin.json`` + ``skills/``), and the
kernel's own plugin machinery — ``lingtai.services.plugin_registry`` — is what
validates and discovers it. Nothing here re-implements the standard: the
manifest grammar, the §4.1 containment rule, and the skill walk all come from
that one service, so a packaged first-party plugin is held to exactly the
contract a third-party directory dropped into ``manifest.plugins`` is held to.

That service is reached **lazily**, and the split is not cosmetic.
``tests/test_kernel_isolation.py`` pins the ``lingtai → lingtai.tools →
lingtai.kernel`` import DAG: importing ``lingtai.tools.registry`` must not pull
``lingtai.services`` into the process, exactly as the ``plugin`` and ``mcp``
tools import their registries inside their handlers. So construction does the
cheap, dependency-light half — the package's own manifest identity, the owned
skill, the no-launcher promise — from the filesystem plus the kernel-owned
frontmatter parser, and :attr:`IntrinsicToolPlugin.plugin_record` runs the real
``read_plugin`` on first access (cached). Both halves are pinned by test, so the
package cannot claim plugin-hood the registry would reject.

The difference from the curated-MCP case is the *mount*, and it is deliberate.
A curated MCP declares an ``mcp.json`` server and is mounted by being launched.
An intrinsic tool's family already executes in-process, so its plugin declares
**no** MCP server at all: what the plugin owns and mounts is its Agent Skill.
Registering it therefore composes one more skill directory into the skills
catalog and can never spawn a subprocess — the host boundary the plugin registry
already draws ("registration is registry-level only … nothing is executed") is
what makes shipping a first-party plugin inside the wheel safe.

Four promises this module enforces, the first three at import time of the owning
package and the fourth on first use of the registry-backed record:

* **The plugin owns the manual.** The declared skill must exist in the package,
  carry the declared frontmatter ``name``, and have a non-empty body.
* **An intrinsic's plugin declares no launcher.** Its family already executes
  in the host process, so a shipped ``mcp.json`` is a packaging defect: it would
  make ``register_plugins`` write a registry record for a server this tool does
  not have. Registering an intrinsic's plugin mounts documentation, never a
  process.
* **The reserved ``manual`` action is the plugin's, not the package's.**
  ``tools/CONTRACT.md`` requires every LingTai-owned family to offer ``manual``;
  a package declares only its *own* actions and this module appends ``manual``,
  bound to the plugin-owned skill. Declaring, re-schema-ing, or rebinding it
  raises :class:`IntrinsicToolPluginError`.
* **The package really is a plugin.** ``read_plugin`` must accept the shipped
  directory with zero problems and report exactly the owned skill — checked when
  :attr:`IntrinsicToolPlugin.plugin_record` is first read, and pinned by test so
  a malformed manifest fails the build rather than an agent.

What stays with the host, unchanged: *where* an owned skill is installed
(``Agent._install_intrinsic_manuals`` decides the destination), whether the tool
is registered at all (``tools/registry.py`` ``INTRINSICS``), dispatch, karma,
audit, and lifecycle. This module is a declarative descriptor plus composition
helpers its own package calls explicitly — not a plugin runtime, and not a
second registry.
"""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any, Mapping, Sequence

from lingtai.kernel._frontmatter import split_frontmatter

from .tool_family import RESERVED_MANUAL_NAME, ChildTool, ToolFamily
from .tool_family.manual import MANUAL_INPUT_SCHEMA, build_manual_child

__all__ = [
    "MANUAL_ACTION",
    "PLUGIN_DIRNAME",
    "SKILLS_DIRNAME",
    "SKILL_FILENAME",
    "IntrinsicToolPlugin",
    "IntrinsicToolPluginError",
    "owned_skill_dir",
]

#: The reserved action name. Owned by ``lingtai.tools.tool_family``; re-exported
#: here so a packaged tool never spells the literal itself.
MANUAL_ACTION = RESERVED_MANUAL_NAME

#: The directory name a tool package uses for its shipped Agent Plugins root.
#: One spelling, shared by the descriptor and by the host installer that copies
#: an owned skill into ``.library/intrinsic/`` — so "where the plugin lives" is
#: not stated twice and cannot drift.
PLUGIN_DIRNAME = "agent_plugin"

#: Agent Plugins v1.0.0 fixed names, restated here only as local constants for
#: path building. ``plugin_registry`` remains the module that *interprets* them.
MANIFEST_FILENAME = "plugin.json"
MCP_CONFIG_FILENAME = "mcp.json"
SKILLS_DIRNAME = "skills"
SKILL_FILENAME = "SKILL.md"


class IntrinsicToolPluginError(ValueError):
    """Raised for an intrinsic-tool packaging defect (bad plugin or shape)."""


def owned_skill_dir(tool_root: Path) -> Path | None:
    """The single Agent Skill directory a tool package's plugin owns, if any.

    Filesystem-only and import-free on purpose: this is what the host's manual
    installer calls while walking ``lingtai/tools/`` without importing every
    tool module. Returns the one ``<tool>/agent_plugin/skills/<skill>/``
    directory that carries a ``SKILL.md``, or None when the package ships no
    plugin (the ordinary ``<tool>/manual/`` bundle) or ships something other
    than exactly one owned skill — an ambiguous package installs nothing here
    rather than picking a winner by sort order.
    """
    skills_dir = Path(tool_root) / PLUGIN_DIRNAME / SKILLS_DIRNAME
    if not (Path(tool_root) / PLUGIN_DIRNAME / MANIFEST_FILENAME).is_file():
        return None
    if not skills_dir.is_dir():
        return None
    owned = [
        entry
        for entry in sorted(skills_dir.iterdir())
        if entry.is_dir()
        and not entry.name.startswith(".")
        and (entry / SKILL_FILENAME).is_file()
    ]
    return owned[0] if len(owned) == 1 else None


@dataclass(frozen=True)
class IntrinsicToolPlugin:
    """One host tool's shipped Agent Plugins package, validated at import.

    ``name`` is the public tool name (the key ``tools/registry.py`` registers
    and the family root the model calls). ``package`` is the Python package that
    ships both the tool code and the plugin directory; the two must agree
    (``package`` ends in ``name``) because the whole point is that the tool and
    the plugin material are one artifact.

    ``plugin_name`` is the ``plugin.json`` manifest name — the identity the
    plugin registry knows this package by, deliberately distinct from the tool
    name because a plugin name is a global, standard-governed namespace while a
    tool name is a local one. ``skill_name`` is the frontmatter name of the
    Agent Skill the plugin owns, and ``manual_skill`` is the host-installed
    directory name ``manual`` reads back from — the host's choice, restated here
    so the family's ``manual`` child and the installer agree by construction.
    """

    name: str
    package: str
    plugin_name: str
    skill_name: str
    manual_skill: str
    summary: str

    # Derived at construction from the shipped package. Excluded from
    # init/repr/eq: they are material, not declared identity.
    _root: Path = field(init=False, repr=False, compare=False)
    _manifest: dict[str, Any] = field(init=False, repr=False, compare=False)
    _skill_dir: Path = field(init=False, repr=False, compare=False)
    _skill_frontmatter: dict[str, str] = field(init=False, repr=False, compare=False)
    _skill_body: str = field(init=False, repr=False, compare=False)
    # One-slot cache for the lazily read registry record (see ``plugin_record``).
    _record_cache: dict[str, Any] = field(
        init=False, repr=False, compare=False, default_factory=dict
    )

    def __post_init__(self) -> None:
        for attribute in (
            "name", "package", "plugin_name", "skill_name", "manual_skill", "summary",
        ):
            value = getattr(self, attribute)
            if not isinstance(value, str) or not value.strip():
                raise IntrinsicToolPluginError(
                    f"IntrinsicToolPlugin {attribute!r} must be a non-empty string"
                )
        if self.package.rpartition(".")[2] != self.name:
            raise IntrinsicToolPluginError(
                f"IntrinsicToolPlugin package {self.package!r} must be the "
                f"{self.name!r} module so the tool and its plugin are one package"
            )

        # The dependency-light half. Path work plus the kernel-owned frontmatter
        # parser only — no import of `lingtai.services`, which the tools package
        # may not pull at import time (`tests/test_kernel_isolation.py`).
        root = Path(str(resources.files(self.package))) / PLUGIN_DIRNAME
        manifest_path = root / MANIFEST_FILENAME
        if not manifest_path.is_file():
            raise IntrinsicToolPluginError(
                f"IntrinsicToolPlugin {self.name!r} ships no Agent Plugin: "
                f"{manifest_path} is missing"
            )
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            raise IntrinsicToolPluginError(
                f"IntrinsicToolPlugin {self.name!r} cannot read {manifest_path}: {e}"
            ) from e
        if not isinstance(manifest, dict):
            raise IntrinsicToolPluginError(
                f"IntrinsicToolPlugin {self.name!r} shipped {MANIFEST_FILENAME} "
                f"is not a JSON object"
            )
        if manifest.get("name") != self.plugin_name:
            raise IntrinsicToolPluginError(
                f"IntrinsicToolPlugin {self.name!r} shipped plugin.json declares "
                f"name {manifest.get('name')!r}, expected {self.plugin_name!r}"
            )
        if (root / MCP_CONFIG_FILENAME).exists():
            raise IntrinsicToolPluginError(
                f"IntrinsicToolPlugin {self.name!r} must declare no MCP server; "
                f"its family executes in the host process, but the shipped plugin "
                f"carries {MCP_CONFIG_FILENAME}"
            )

        skill_dir = root / SKILLS_DIRNAME / self.skill_name
        skill_file = skill_dir / SKILL_FILENAME
        if not skill_file.is_file():
            raise IntrinsicToolPluginError(
                f"IntrinsicToolPlugin {self.name!r} shipped plugin must own "
                f"exactly the skill {self.skill_name!r}; {skill_file} is missing"
            )
        frontmatter, body = split_frontmatter(skill_file.read_text(encoding="utf-8"))
        if frontmatter.get("name") != self.skill_name:
            raise IntrinsicToolPluginError(
                f"IntrinsicToolPlugin {self.name!r} owned {SKILL_FILENAME} declares "
                f"name {frontmatter.get('name')!r}, expected {self.skill_name!r}"
            )
        if not body.strip():
            raise IntrinsicToolPluginError(
                f"IntrinsicToolPlugin {self.name!r} owned {SKILL_FILENAME} has an empty body"
            )

        object.__setattr__(self, "_root", root)
        object.__setattr__(self, "_manifest", manifest)
        object.__setattr__(self, "_skill_dir", skill_dir)
        object.__setattr__(self, "_skill_frontmatter", frontmatter)
        object.__setattr__(self, "_skill_body", body)

    # -- the shipped plugin -------------------------------------------------

    @property
    def plugin_root(self) -> Path:
        """Absolute path of the shipped Agent Plugins v1.0.0 directory."""
        return self._root

    @property
    def manifest(self) -> dict[str, Any]:
        """The parsed ``plugin.json`` as shipped, unvalidated by this module."""
        # Deep: the record carries nested lists a caller must not be able to
        # mutate back into the descriptor.
        return copy.deepcopy(self._manifest)

    @property
    def plugin_record(self) -> dict[str, Any]:
        """The ``plugin_registry.read_plugin`` record, read once on demand.

        This is the half that proves the package is a *real* plugin rather than
        a directory shaped like one: the standard's manifest grammar, its §4.1
        containment rule, and its skill walk are applied by the one service that
        owns them, so a first-party plugin passes exactly what a third-party one
        must. The import is deliberately inside the call — the
        ``lingtai.tools → lingtai`` lazy back-edge rule the ``plugin`` and
        ``mcp`` tools already follow, pinned by ``tests/test_kernel_isolation.py``.

        Raises :class:`IntrinsicToolPluginError` if the registry rejects the
        plugin, reports any skipped component, disagrees about the owned skill,
        or finds a declared MCP server.
        """
        if self._record_cache:
            return copy.deepcopy(self._record_cache["record"])

        from lingtai.services.plugin_registry import read_plugin

        record, problems = read_plugin(self._root)
        if record is None:
            reason = problems[0]["error"] if problems else "unknown"
            raise IntrinsicToolPluginError(
                f"IntrinsicToolPlugin {self.name!r} ships an invalid Agent Plugin "
                f"at {self._root}: {reason}"
            )
        if problems:
            # A component-level problem is a *skipped* component: the plugin
            # would register minus that piece. For a first-party package shipped
            # in the wheel that is a build defect, not a runtime degradation.
            raise IntrinsicToolPluginError(
                f"IntrinsicToolPlugin {self.name!r} shipped plugin has "
                f"{len(problems)} problem(s): {problems[0].get('error', 'unknown')}"
            )
        if record["name"] != self.plugin_name:
            raise IntrinsicToolPluginError(
                f"IntrinsicToolPlugin {self.name!r} shipped plugin.json declares "
                f"name {record['name']!r}, expected {self.plugin_name!r}"
            )
        if record["mcp_servers"]:
            raise IntrinsicToolPluginError(
                f"IntrinsicToolPlugin {self.name!r} must declare no MCP server; "
                f"its family executes in the host process, but the shipped "
                f"plugin declares {record['mcp_servers']!r}"
            )
        if record["skills"] != [self.skill_name] or [
            Path(p) for p in record["skill_paths"]
        ] != [self._skill_dir]:
            raise IntrinsicToolPluginError(
                f"IntrinsicToolPlugin {self.name!r} shipped plugin must own "
                f"exactly the skill {self.skill_name!r}, found {record['skills']!r}"
            )
        self._record_cache["record"] = record
        return copy.deepcopy(record)

    # -- the plugin-owned skill --------------------------------------------

    @property
    def skill_dir(self) -> Path:
        """Absolute directory of the Agent Skill this plugin owns."""
        return self._skill_dir

    @property
    def skill_path(self) -> Path:
        """Absolute path of the owned ``SKILL.md``."""
        return self._skill_dir / SKILL_FILENAME

    @property
    def skill_frontmatter(self) -> dict[str, str]:
        """Parsed frontmatter of the owned skill (its catalog entry)."""
        return dict(self._skill_frontmatter)

    @property
    def skill_body(self) -> str:
        """Markdown body of the owned skill — what ``manual`` serves."""
        return self._skill_body

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
        schemas[MANUAL_ACTION] = dict(MANUAL_INPUT_SCHEMA)
        return schemas

    def manual_child(self, agent: Any) -> ChildTool:
        """The plugin-owned reserved ``manual`` child, bound to *agent*.

        The body it returns is this plugin's own skill: the host installs the
        owned skill directory under ``manual_skill`` and
        ``build_manual_child`` reads it back from there, so the tool's manual
        and the plugin's skill are the same document by construction.
        """
        return build_manual_child(agent, self.manual_skill)

    def build_family(self, agent: Any, declared: Sequence[ChildTool]) -> ToolFamily:
        """Compose this tool's one public family, ``manual`` always appended."""
        self._check_declared_names([child.name for child in declared])
        return ToolFamily(self.name, [*declared, self.manual_child(agent)])

    def schema_family(self, declared: Sequence[ChildTool]) -> ToolFamily:
        """Compose the schema-only family used before any agent exists.

        Same registry, same reserved append, a ``manual`` child that never
        dispatches — an intrinsic composes its model-facing schema at import
        time, long before an agent is around to read an installed manual from.
        """
        self._check_declared_names([child.name for child in declared])

        def _never(_input: Mapping[str, Any]) -> dict[str, Any]:
            raise AssertionError(
                f"the schema-only {self.name!r} manual child never dispatches"
            )

        return ToolFamily(
            self.name,
            [*declared, ChildTool(MANUAL_ACTION, dict(MANUAL_INPUT_SCHEMA), _never)],
        )

    def _check_declared_names(self, declared: "Sequence[str] | Any") -> None:
        names = list(declared)
        if not names:
            raise IntrinsicToolPluginError(
                f"IntrinsicToolPlugin {self.name!r} must declare at least one action"
            )
        if MANUAL_ACTION in names:
            raise IntrinsicToolPluginError(
                f"IntrinsicToolPlugin {self.name!r} must not declare the reserved "
                f"{MANUAL_ACTION!r} action; it is appended from the plugin-owned "
                f"{SKILL_FILENAME}"
            )
        if len(set(names)) != len(names):
            raise IntrinsicToolPluginError(
                f"IntrinsicToolPlugin {self.name!r} declared a duplicate action"
            )
