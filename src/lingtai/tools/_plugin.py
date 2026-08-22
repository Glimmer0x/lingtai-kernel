"""Kernel tool plugin packaging: one package owns its skill, its family shape, and its mount record.

A built-in capability is not just a module the registry happens to import. It is
a *plugin-style package*: the same folder ships the execution engine, the
bundled ``manual/SKILL.md`` the reserved ``manual`` action serves, and the
capability record the host mounts it by. This module is the small shared piece
that binds those three together for one package, so a capability cannot drift
into declaring its module in one place, its manual destination in another, and a
public action list that silently disagrees with both.

It is the ``lingtai.tools`` sibling of :mod:`lingtai.mcp_servers._plugin`
(``CuratedMcpPlugin``), and it keeps that module's discipline: it deliberately
is **not** a plugin runtime. Nothing here activates a capability, constructs a
manager, reads configuration, or decides namespace/collision questions —
activation, execution policy, containment, and lifecycle all remain the host's.
:mod:`lingtai.tools.registry` still owns ``BUILTIN_TOOLS``/``CORE_DEFAULTS`` and
``setup_capability``; ``lingtai.agent.Agent._install_intrinsic_manuals`` still
owns the library wipe-and-rewrite; ``lingtai.services.plugin_registry`` still
owns external Agent Plugins v1.0.0 directories. A :class:`KernelToolPlugin` is a
declarative descriptor plus composition helpers its own package calls
explicitly, and one narrow *discovery* seam (:func:`tool_plugin_for`) the
installer uses to ask a package where its manual belongs instead of hard-coding
the answer.

The one hard promise it enforces is the reserved ``manual`` action
(``tools/CONTRACT.md`` "Every LingTai-owned family MUST offer a ``manual``
action"): a package declares only its *own* actions, and this module appends
``manual`` itself, bound to the package's bundled ``SKILL.md``. A package that
tries to declare, re-schema, or re-handle ``manual`` raises
:class:`KernelToolPluginError` at import time rather than shipping a family
whose manual is missing or points somewhere other than its packaged skill.

Where this differs from the curated-MCP descriptor, and why:

- A curated MCP's launcher is ``python -m <package>``, so its registry name and
  module name must be equal. A built-in capability is mounted in-process, and
  several capabilities keep a *retained implementation directory* whose name is
  not the model-facing one (``bash`` → ``shell``, ``web_search`` → ``web``).
  :class:`KernelToolPlugin` therefore carries ``name`` (public capability,
  family, and installed-manual destination) and ``package`` (implementation
  module) as two separate facts, and :meth:`capability_declaration` publishes
  the mapping between them as the record the host must agree with.
- A curated MCP serves its manual straight out of its own package. A built-in
  capability's manual is *installed* into the agent's ``.library/intrinsic/``
  by the host, and the model-visible ``manual_path`` must stay host-local.
  :meth:`manual_payload` keeps that boundary — it reads the installed copy
  first — while the packaged skill remains the source of truth and the fallback,
  so ``manual`` can no longer answer with an empty body when the library is
  missing.
"""
from __future__ import annotations

import copy
import importlib
import importlib.util
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from importlib import resources
from types import MappingProxyType
from typing import Any

from lingtai.kernel._frontmatter import split_frontmatter

from ._manual import load_installed_manual
from .tool_family import RESERVED_MANUAL_NAME, ChildTool, ToolFamily
from .tool_family.manual import MANUAL_INPUT_SCHEMA

__all__ = [
    "KERNEL_SOURCE",
    "MANUAL_ACTION",
    "MANUAL_DIRNAME",
    "MANUAL_SOURCE_INSTALLED",
    "MANUAL_SOURCE_PACKAGED",
    "SKILL_FILENAME",
    "KernelToolPlugin",
    "KernelToolPluginError",
    "manual_destination_for",
    "register_tool_plugin",
    "registered_tool_plugins",
    "tool_plugin_for",
]

#: ``source`` stamped on every kernel-shipped capability record — the value that
#: tells a built-in capability apart from a ``plugin:<name>``-sourced external
#: Agent Plugin or a hand-registered one.
KERNEL_SOURCE = "lingtai-kernel"

#: The reserved action name. Owned by :mod:`lingtai.tools.tool_family`;
#: re-exported here so a tool package never spells the literal itself.
MANUAL_ACTION = RESERVED_MANUAL_NAME

#: The bundled-manual directory name inside a tool package, and the skill file
#: inside it. ``Agent._install_intrinsic_manuals`` copies this whole directory
#: (manual plus its ``reference/`` submanuals) into the agent's library.
MANUAL_DIRNAME = "manual"
SKILL_FILENAME = "SKILL.md"

#: ``structuredContent.manual_source`` values: the host-installed library copy
#: (the normal case) versus the packaged skill this plugin owns (the fallback).
MANUAL_SOURCE_INSTALLED = "installed"
MANUAL_SOURCE_PACKAGED = "packaged"


class KernelToolPluginError(ValueError):
    """Raised for a built-in tool packaging defect (bad descriptor or shape)."""


@dataclass(frozen=True)
class KernelToolPlugin:
    """One built-in tool package's identity, packaged skill, and mount record.

    ``name`` is the public capability name, the model-facing family name, and
    the directory the packaged manual installs to under
    ``.library/intrinsic/capabilities/``. ``package`` is the Python package that
    ships both the execution engine and the ``manual/SKILL.md`` the ``manual``
    action serves; it must live under ``lingtai.tools`` because that is the
    module path :data:`lingtai.tools.registry.BUILTIN_TOOLS` resolves.

    The bundled skill is loaded once at construction and its frontmatter
    ``name`` is checked against ``skill_name``, so a package that renames or
    loses its manual fails loudly at import instead of serving a foreign or
    empty ``manual``.
    """

    name: str
    package: str
    summary: str
    skill_name: str
    default_kwargs: Mapping[str, Any] = field(default_factory=dict)

    # Loaded from the package's bundled manual/SKILL.md at construction.
    # Excluded from init/repr/eq: derived material, not declared identity.
    _skill_frontmatter: dict[str, str] = field(init=False, repr=False, compare=False)
    _skill_text: str = field(init=False, repr=False, compare=False)
    _skill_body: str = field(init=False, repr=False, compare=False)
    _skill_path: str = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        for attribute in ("name", "package", "summary", "skill_name"):
            value = getattr(self, attribute)
            if not isinstance(value, str) or not value.strip():
                raise KernelToolPluginError(
                    f"KernelToolPlugin {attribute!r} must be a non-empty string"
                )
        if not self.package.startswith(f"{__package__}."):
            raise KernelToolPluginError(
                f"KernelToolPlugin package {self.package!r} must be a "
                f"{__package__}.<pkg> module so the registry can mount it"
            )
        if not isinstance(self.default_kwargs, Mapping):
            raise KernelToolPluginError(
                f"KernelToolPlugin {self.name!r} default_kwargs must be a mapping"
            )
        object.__setattr__(
            self, "default_kwargs", MappingProxyType(dict(self.default_kwargs))
        )
        frontmatter, text, body, path = self._load_packaged_skill()
        if frontmatter.get("name") != self.skill_name:
            raise KernelToolPluginError(
                f"KernelToolPlugin {self.name!r} bundled {MANUAL_DIRNAME}/{SKILL_FILENAME} "
                f"declares name {frontmatter.get('name')!r}, expected {self.skill_name!r}"
            )
        if not body.strip():
            raise KernelToolPluginError(
                f"KernelToolPlugin {self.name!r} bundled "
                f"{MANUAL_DIRNAME}/{SKILL_FILENAME} has an empty body"
            )
        object.__setattr__(self, "_skill_frontmatter", frontmatter)
        object.__setattr__(self, "_skill_text", text)
        object.__setattr__(self, "_skill_body", body)
        object.__setattr__(self, "_skill_path", path)

    def _load_packaged_skill(self) -> tuple[dict[str, str], str, str, str]:
        resource = (
            resources.files(self.package).joinpath(MANUAL_DIRNAME).joinpath(SKILL_FILENAME)
        )
        try:
            text = resource.read_text(encoding="utf-8")
        except (FileNotFoundError, OSError) as exc:
            raise KernelToolPluginError(
                f"KernelToolPlugin {self.name!r} has no bundled "
                f"{MANUAL_DIRNAME}/{SKILL_FILENAME} in {self.package!r}"
            ) from exc
        frontmatter, body = split_frontmatter(text)
        return frontmatter, text, body, str(resource)

    # -- identity ----------------------------------------------------------

    @property
    def implementation_dir(self) -> str:
        """The package's directory name — the *retained* implementation name.

        ``bash`` for the ``shell`` capability. This is what the installer sees
        when it walks ``lingtai/tools/``, and what :func:`tool_plugin_for` keys
        discovery on; ``name`` is what the model sees.
        """
        return self.package.rpartition(".")[2]

    @property
    def manual_destination(self) -> str:
        """Directory the packaged manual installs to, under ``capabilities/``.

        Always the public ``name``: the library is a flat model-facing
        namespace, so a retained implementation directory must not leak into it.
        """
        return self.name

    # -- packaged skill / manual ------------------------------------------

    @property
    def skill_frontmatter(self) -> dict[str, str]:
        """Parsed packaged ``SKILL.md`` frontmatter (the manual's catalog entry)."""
        return dict(self._skill_frontmatter)

    @property
    def skill_text(self) -> str:
        """The packaged ``SKILL.md`` verbatim — frontmatter included.

        This, not :attr:`skill_body`, is what ``manual`` serves when it falls
        back to the package, because it is byte-for-byte what
        ``Agent._install_intrinsic_manuals`` copies into the agent's library and
        therefore byte-for-byte what the installed copy would have answered.
        """
        return self._skill_text

    @property
    def skill_body(self) -> str:
        """The packaged ``SKILL.md`` markdown body, frontmatter stripped.

        The descriptor's own view of the manual's prose — used to prove at
        construction that the packaged skill is not an empty shell. The
        ``manual`` action serves :attr:`skill_text`, not this.
        """
        return self._skill_body

    @property
    def skill_path(self) -> str:
        """Absolute resolved path of the packaged ``manual/SKILL.md``."""
        return self._skill_path

    def manual_input_schema(self) -> dict[str, Any]:
        """The reserved ``manual`` child's strict-empty ``input`` schema.

        Deep-copied from the one shared literal in
        :mod:`lingtai.tools.tool_family.manual`, never re-declared here, so a
        plugin-composed family advertises byte-identical ``manual`` input to
        every hand-composed one.
        """
        return copy.deepcopy(MANUAL_INPUT_SCHEMA)

    def installed_manual_path(self, agent: Any) -> str:
        """Where the host installs this plugin's manual for *agent*."""
        return str(
            agent._working_dir
            / ".library"
            / "intrinsic"
            / "capabilities"
            / self.manual_destination
            / SKILL_FILENAME
        )

    def manual_payload(self, agent: Any) -> dict[str, Any]:
        """The ``action='manual'`` result: full body, host-local path, provenance.

        The canonical ManualTool shape (``tool_family/manual.py``): the full
        markdown at ``content[0].text`` and the model-visible ``manual_path`` at
        ``structuredContent.manual_path``, returned verbatim by
        :meth:`ToolFamily.handle` with no second envelope.

        Host boundary first: the installed library copy is read through the
        unchanged :func:`lingtai.tools._manual.load_installed_manual`, so the
        path the model sees stays host-local and the agent's own library remains
        the thing it is pointed at. Package ownership second: that library copy
        is a verbatim copy of *this* package's skill —
        ``Agent._install_intrinsic_manuals`` wipes and rewrites
        ``.library/intrinsic/`` from the packaged bundle on every boot and
        refresh — so when it is missing or empty the packaged skill answers
        instead of an empty body. ``manual_source`` says which one answered and
        ``installed_manual_path`` keeps the host fact visible either way.
        """
        installed = self._load_installed(agent)
        installed_path = installed.get("manual_path", "")
        body = installed.get("manual") or ""
        if body.strip():
            result: dict[str, Any] = {
                "status": installed.get("status", "ok"),
                "content": [{"type": "text", "text": body}],
                "structuredContent": {
                    "manual_path": installed_path,
                    "skill": self.skill_name,
                    "manual_source": MANUAL_SOURCE_INSTALLED,
                    "installed_manual_path": installed_path,
                },
            }
            if "error" in installed:
                result["error"] = installed["error"]
            return result
        return {
            "status": "ok",
            "content": [{"type": "text", "text": self._skill_text}],
            "structuredContent": {
                "manual_path": self._skill_path,
                "skill": self.skill_name,
                "manual_source": MANUAL_SOURCE_PACKAGED,
                "installed_manual_path": installed_path,
            },
            "warning": (
                f"installed {self.skill_name} missing or empty"
                + (f" at {installed_path}" if installed_path else "")
                + f"; served the packaged skill from {self._skill_path}. "
                "The library is rewritten from this package on the next boot or "
                "system(action='refresh')."
            ),
        }

    def _load_installed(self, agent: Any) -> Mapping[str, Any]:
        """Read the host-installed copy, tolerating a schema-only (agentless) family."""
        if agent is None or not hasattr(agent, "_working_dir"):
            return {"status": "degraded", "manual": "", "manual_path": ""}
        try:
            return load_installed_manual(agent, self.manual_destination)
        except OSError as exc:  # unreadable library — packaged skill still answers
            return {
                "status": "degraded",
                "manual": "",
                "manual_path": self.installed_manual_path(agent),
                "error": str(exc),
            }

    def manual_child(self, agent: Any) -> ChildTool:
        """The plugin-owned reserved ``manual`` child.

        Its handler closes over this descriptor, so ``manual`` never routes
        through the package's business manager, performs no target operation,
        and cannot be rebound to other material.
        """
        return ChildTool(
            name=MANUAL_ACTION,
            input_schema=self.manual_input_schema(),
            handler=lambda _input: self.manual_payload(agent),
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
        schemas[MANUAL_ACTION] = self.manual_input_schema()
        return schemas

    def build_family(self, declared: Sequence[ChildTool], agent: Any = None) -> ToolFamily:
        """Compose this plugin's one public family, ``manual`` always appended."""
        children = list(declared)
        self._check_declared_names([child.name for child in children])
        return ToolFamily(self.name, [*children, self.manual_child(agent)])

    def _check_declared_names(self, declared: "Sequence[str] | Any") -> None:
        names = list(declared)
        if not names:
            raise KernelToolPluginError(
                f"KernelToolPlugin {self.name!r} must declare at least one action"
            )
        if MANUAL_ACTION in names:
            raise KernelToolPluginError(
                f"KernelToolPlugin {self.name!r} must not declare the reserved "
                f"{MANUAL_ACTION!r} action; it is appended from the packaged "
                f"{MANUAL_DIRNAME}/{SKILL_FILENAME}"
            )
        if len(set(names)) != len(names):
            raise KernelToolPluginError(
                f"KernelToolPlugin {self.name!r} declared a duplicate action"
            )

    # -- shipped mount record ----------------------------------------------

    def capability_declaration(self) -> dict[str, Any]:
        """This package's capability record — the mount facts the host must match.

        The same facts the host's own seams already hold, gathered in one place
        the package owns: ``module`` is what
        :data:`lingtai.tools.registry.BUILTIN_TOOLS` maps ``name`` to,
        ``default_kwargs`` is this capability's
        :data:`lingtai.tools.registry.CORE_DEFAULTS` entry, and
        ``manual_source``/``manual_destination`` are the copy
        ``Agent._install_intrinsic_manuals`` performs.

        Returning it here registers, imports, or mounts nothing: the registry
        tables and the installer remain the runtime sources the host reads, and
        this descriptor is what those must agree with — the same
        declaration-agrees-with-the-shipped-file discipline
        ``CuratedMcpPlugin.mcp_declaration()`` keeps with ``mcp_catalog.json``.
        """
        return {
            "name": self.name,
            "summary": self.summary,
            "kind": "capability",
            "module": self.package,
            "source": KERNEL_SOURCE,
            "skill": self.skill_name,
            "manual_source": f"{self.implementation_dir}/{MANUAL_DIRNAME}",
            "manual_destination": self.manual_destination,
            "default_kwargs": dict(self.default_kwargs),
        }


# ---------------------------------------------------------------------------
# Discovery seam — how the host asks a package where its manual belongs
# ---------------------------------------------------------------------------
#
# Deliberately the *only* runtime-facing function in this module, and
# deliberately narrow. ``Agent._install_intrinsic_manuals`` walks
# ``lingtai/tools/`` and needs one fact per directory: the public name its
# ``manual/`` bundle installs under. Before this seam that mapping was a literal
# ``if entry.name == "bash"`` in the installer — a package's own naming fact
# stated somewhere the package could not see. Now the package states it, in its
# descriptor, and the installer asks.
#
# Discovery is one guarded, cached import of ``<pkg>.plugin`` for packages that
# ship one; nothing else about the package is imported for this purpose, no
# capability is activated, and a package without a descriptor is not penalized.

_REGISTRY: dict[str, KernelToolPlugin] = {}
_NO_PLUGIN: set[str] = set()

#: Retained implementation directories that have no descriptor yet. ``web_search``
#: keeps its historical ``web`` destination here until that package is converted;
#: every other directory installs under its own name.
_LEGACY_MANUAL_DESTINATIONS: dict[str, str] = {"web_search": "web"}


def register_tool_plugin(plugin: KernelToolPlugin) -> KernelToolPlugin:
    """Register *plugin* under its implementation directory; return it.

    Called once, explicitly, by the descriptor's own ``plugin.py`` at import.
    Re-registering the same descriptor (a module reimported under test) is fine;
    registering a *different* descriptor for the same directory is a packaging
    defect and fails loudly.
    """
    if not isinstance(plugin, KernelToolPlugin):
        raise KernelToolPluginError("register_tool_plugin expects a KernelToolPlugin")
    key = plugin.implementation_dir
    existing = _REGISTRY.get(key)
    if existing is not None and existing != plugin:
        raise KernelToolPluginError(
            f"conflicting KernelToolPlugin registrations for package {key!r}: "
            f"{existing.name!r} and {plugin.name!r}"
        )
    _REGISTRY[key] = plugin
    _NO_PLUGIN.discard(key)
    return plugin


def registered_tool_plugins() -> dict[str, KernelToolPlugin]:
    """Snapshot of descriptors registered so far, keyed by implementation dir."""
    return dict(_REGISTRY)


def tool_plugin_for(implementation_dir: str) -> "KernelToolPlugin | None":
    """Return the descriptor a tool package ships, importing it once if needed.

    ``implementation_dir`` is the directory name under ``lingtai/tools/`` (e.g.
    ``"bash"``), not the public capability name. Returns ``None`` — cached — for
    a package that ships no ``plugin.py``, so walking the whole tools tree costs
    one :func:`importlib.util.find_spec` miss per unconverted package.
    """
    if implementation_dir in _REGISTRY:
        return _REGISTRY[implementation_dir]
    if implementation_dir in _NO_PLUGIN or implementation_dir.startswith("_"):
        return None
    module_path = f"{__package__}.{implementation_dir}.plugin"
    try:
        spec = importlib.util.find_spec(module_path)
    except (ImportError, AttributeError, ValueError):
        spec = None
    if spec is None:
        _NO_PLUGIN.add(implementation_dir)
        return None
    importlib.import_module(module_path)  # registers itself as an import effect
    plugin = _REGISTRY.get(implementation_dir)
    if plugin is None:
        _NO_PLUGIN.add(implementation_dir)
    return plugin


def manual_destination_for(implementation_dir: str) -> str:
    """The ``capabilities/<name>/`` directory a package's ``manual/`` installs to.

    Descriptor first, then the retained legacy alias table, then the directory's
    own name. This is the mount fact ``Agent._install_intrinsic_manuals``
    consumes; it maps a *retained implementation* directory onto the one
    model-facing name exactly once.
    """
    plugin = tool_plugin_for(implementation_dir)
    if plugin is not None:
        return plugin.manual_destination
    return _LEGACY_MANUAL_DESTINATIONS.get(implementation_dir, implementation_dir)
