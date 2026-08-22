"""Built-in tool plugin packaging: one package owns its skill, manifest, and family shape.

A built-in tool is not just a directory the registry happens to import. It is a
*plugin-style package*: the same folder ships the tool code, the bundled
``manual/`` skill the reserved ``manual`` action serves, and the ``plugin.json``
manifest the host reads at runtime to discover and mount it. This module is the
small shared piece that binds those three together for one package, so a
built-in tool cannot drift into declaring its module in one place, its manual in
another, and a public action list that silently disagrees with both.

It is the ``lingtai.tools`` sibling of :mod:`lingtai.mcp_servers._plugin`
(``CuratedMcpPlugin``), which does the same job for a curated MCP package. The
two differ only where the surfaces genuinely differ:

* a curated MCP publishes a *launcher* (``python -m <package>``) into
  ``mcp_catalog.json``; a built-in tool publishes a *module* into
  ``registry.BUILTIN_TOOLS`` and a *manual mount* into
  ``.library/intrinsic/capabilities/<name>/``;
* a curated MCP's ``manual`` answers straight from the packaged ``SKILL.md``
  over the wire; a built-in tool's ``manual`` answers from the copy the host
  mounted into the agent's own working directory, because that host-local
  ``manual_path`` is part of the tool's model-facing result (``#1058``). The
  packaged bundle is still the one owned source — the mount is a copy of it,
  at the destination *this descriptor* declares.

Unlike ``services/plugin_registry.py`` (external Agent Plugins v1.0.0
directories), nothing here is user-installable, sandboxed, or activated by
configuration: these are kernel-shipped packages, and discovery is bounded to
the ``lingtai.tools`` package directory. What discovery *does* own is real: the
manual mount destination and bundle name, and the module a capability resolves
to. Execution policy, capability admission, defaults, and kwargs all remain the
host's (``lingtai.tools.registry``, ``lingtai.agent``).

The one hard promise this module enforces is the reserved ``manual`` action
(``tools/CONTRACT.md`` "Every LingTai-owned family MUST offer a ``manual``
action"): a package declares only its *own* actions, and this module appends
``manual`` itself, bound to the package's own mounted skill. A package that
tries to declare, re-schema, or re-handle ``manual`` raises
:class:`ToolPluginError` at import time rather than shipping a family whose
manual is missing or points somewhere other than its packaged skill.
"""
from __future__ import annotations

import copy
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from importlib import import_module
from pathlib import Path
from typing import Any

from lingtai.kernel._frontmatter import split_frontmatter

from .tool_family import RESERVED_MANUAL_NAME, ChildTool, ToolFamily
from .tool_family.manual import MANUAL_INPUT_SCHEMA, build_manual_child

__all__ = [
    "BUILTIN_SOURCE",
    "MANIFEST_FILENAME",
    "MANUAL_ACTION",
    "MANUAL_BUNDLE_DIRNAME",
    "SKILL_FILENAME",
    "TOOL_PLUGIN_SCHEMA",
    "TOOLS_PACKAGE",
    "ToolPlugin",
    "ToolPluginError",
    "discover_manifests",
    "manifest_module",
    "read_manifest",
    "tools_package_root",
    "validate_manifest",
]

#: ``source`` stamped on every built-in tool manifest — the value that tells a
#: kernel-shipped tool plugin apart from an external ``plugin:<name>`` Agent
#: Plugin registered by ``lingtai.services.plugin_registry``.
BUILTIN_SOURCE = "lingtai-builtin"

#: Manifest schema identifier. Compared as an opaque version string; never
#: fetched, and deliberately not the agent-plugins.org URL — an external Agent
#: Plugin and a kernel-shipped tool plugin are different objects with different
#: trust boundaries, and must never be mistaken for one another.
TOOL_PLUGIN_SCHEMA = "lingtai.tool.plugin.v1"

#: The file a tool package ships so the host can discover and mount it without
#: importing Python. Read by :func:`read_manifest` / :func:`discover_manifests`.
MANIFEST_FILENAME = "plugin.json"

#: The packaged skill bundle every built-in tool manual ships in, and the
#: directory ``Agent._install_intrinsic_manuals`` copies to the agent's library.
MANUAL_BUNDLE_DIRNAME = "manual"

#: The bundle's catalog file — its YAML frontmatter names the owned skill.
SKILL_FILENAME = "SKILL.md"

#: The reserved action name. Owned by ``lingtai.tools.tool_family``; re-exported
#: here so a tool package never spells the literal itself.
MANUAL_ACTION = RESERVED_MANUAL_NAME

#: The one package tool plugins may live in. Discovery never leaves it.
TOOLS_PACKAGE = "lingtai.tools"


class ToolPluginError(ValueError):
    """Raised for a built-in tool packaging defect (bad descriptor or shape)."""


def _package_root(package: str) -> Path:
    """Filesystem root of an importable package, safe during its own import.

    ``importlib.resources.files()`` is the usual spelling, but a package's own
    ``plugin.py`` is imported *from* that package's ``__init__``, so the module
    is still mid-execution when the descriptor is constructed. ``__file__`` is
    bound before the body runs, so this reads correctly at that moment;
    ``resources.files()`` on a half-initialized module is not contracted to.
    The host's manual installer already resolves tool packages this way
    (``Agent._install_intrinsic_manuals``), so both ends agree on one notion of
    "where this package lives".
    """
    module = sys.modules.get(package) or import_module(package)
    package_file = getattr(module, "__file__", None)
    if not package_file:
        raise ToolPluginError(f"tool plugin package {package!r} has no filesystem location")
    return Path(package_file).parent


@dataclass(frozen=True)
class ToolPlugin:
    """One built-in tool package's identity, owned skill, and public actions.

    ``name`` is the public capability/tool name and the family name;
    ``package`` is the ``lingtai.tools`` subpackage that ships both the tool
    code and the ``manual/`` skill the ``manual`` action serves. Unlike a
    curated MCP — whose package must *be* its registry name because it declares
    ``python -m <package>`` as its launcher — a tool package's directory may
    differ from its public name (``web_search`` implements ``web``): the
    retained implementation directory is exactly the thing the host must be
    told about rather than guess, which is why ``install_as`` is declared here
    and published in :meth:`tool_declaration` instead of living in a host-side
    table.

    ``declared_actions`` lists the package's *own* actions; the reserved
    ``manual`` is appended by :attr:`actions` and can never be declared here.

    The packaged skill is read and its frontmatter ``name`` checked against
    ``skill_name`` at construction, so a package that renames or loses its
    manual fails loudly at import instead of mounting an empty or foreign one.
    """

    name: str
    package: str
    summary: str
    homepage: str
    skill_name: str
    declared_actions: tuple[str, ...]

    # Derived from the packaged bundle at construction. Excluded from
    # init/repr/eq: they are derived material, not declared identity.
    _skill_frontmatter: dict[str, str] = field(init=False, repr=False, compare=False)
    _skill_path: str = field(init=False, repr=False, compare=False)
    _manual_dir: str = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        for attribute in ("name", "package", "summary", "homepage", "skill_name"):
            value = getattr(self, attribute)
            if not isinstance(value, str) or not value.strip():
                raise ToolPluginError(
                    f"ToolPlugin {attribute!r} must be a non-empty string"
                )
        parent, _, leaf = self.package.rpartition(".")
        if parent != TOOLS_PACKAGE or not leaf:
            raise ToolPluginError(
                f"ToolPlugin package {self.package!r} must be an immediate "
                f"{TOOLS_PACKAGE} subpackage so its declared module is the one "
                "the registry mounts and the host installs the manual from"
            )
        object.__setattr__(self, "declared_actions", tuple(self.declared_actions))
        self._check_declared_names(self.declared_actions)

        manual_dir = _package_root(self.package) / MANUAL_BUNDLE_DIRNAME
        skill_file = manual_dir / SKILL_FILENAME
        try:
            text = skill_file.read_text(encoding="utf-8")
        except OSError as exc:
            raise ToolPluginError(
                f"ToolPlugin {self.name!r} bundled "
                f"{MANUAL_BUNDLE_DIRNAME}/{SKILL_FILENAME} is unreadable: {exc}"
            ) from exc
        frontmatter, body = split_frontmatter(text)
        if frontmatter.get("name") != self.skill_name:
            raise ToolPluginError(
                f"ToolPlugin {self.name!r} bundled {SKILL_FILENAME} declares name "
                f"{frontmatter.get('name')!r}, expected {self.skill_name!r}"
            )
        if not body.strip():
            raise ToolPluginError(
                f"ToolPlugin {self.name!r} bundled {SKILL_FILENAME} has an empty body"
            )
        object.__setattr__(self, "_skill_frontmatter", dict(frontmatter))
        object.__setattr__(self, "_skill_path", str(skill_file))
        object.__setattr__(self, "_manual_dir", str(manual_dir))

    # -- packaged skill / mounted manual -----------------------------------

    @property
    def skill_frontmatter(self) -> dict[str, str]:
        """Parsed packaged ``SKILL.md`` frontmatter (the manual's catalog entry)."""
        return dict(self._skill_frontmatter)

    @property
    def skill_path(self) -> str:
        """Absolute path of the *packaged* ``SKILL.md`` (not the mounted copy)."""
        return self._skill_path

    @property
    def manual_bundle_dir(self) -> str:
        """Absolute path of the packaged ``manual/`` bundle the host mounts."""
        return self._manual_dir

    def read_skill_body(self) -> str:
        """Read the packaged skill body on demand.

        Deliberately not cached in the descriptor: the body the model reads is
        the *mounted* copy under the agent's ``.library/``, and holding a second
        13 KB copy per process for every tool plugin would buy nothing. The
        packaged body is verification material — construction already proved it
        exists and is non-empty.
        """
        return split_frontmatter(Path(self._skill_path).read_text(encoding="utf-8"))[1]

    def manual_child(self, agent: Any) -> ChildTool:
        """The plugin-owned reserved ``manual`` child, bound to *agent*'s mount.

        Sourced from the mounted copy of *this* plugin's own bundle, at the
        destination this descriptor declares (:attr:`install_as`) — so ``manual``
        cannot be rebound to another package's material or to a name the host
        happens to have hardcoded.
        """
        return build_manual_child(agent, self.install_as)

    def unbound_manual_child(self) -> ChildTool:
        """A never-dispatching ``manual`` child for module-level schema-only use.

        A tool package composes its model-facing schema at import time, before
        any agent exists. The schema this child contributes is the same owned
        :data:`MANUAL_INPUT_SCHEMA` the bound child validates against, so the
        schema and the child that dispatches it cannot drift.
        """

        def _never(_input: Mapping[str, Any]) -> dict[str, Any]:
            raise ToolPluginError(
                f"ToolPlugin {self.name!r} schema-only {MANUAL_ACTION!r} child "
                "never dispatches; bind one with manual_child(agent)"
            )

        return ChildTool(
            MANUAL_ACTION,
            # Deep copy for the same reason ``build_manual_child`` does one: a
            # shallow copy would share the nested ``properties`` map across
            # every family that composes one.
            copy.deepcopy(MANUAL_INPUT_SCHEMA),
            _never,
            title=f"{MANUAL_ACTION} input",
        )

    # -- family composition -------------------------------------------------

    @property
    def install_as(self) -> str:
        """Where the host mounts this plugin's manual bundle, under the library.

        The public name — never the retained implementation directory. This is
        the fact ``Agent._install_intrinsic_manuals`` used to hardcode.
        """
        return self.name

    @property
    def actions(self) -> tuple[str, ...]:
        """Declared actions plus the reserved ``manual``, in that order."""
        return (*self.declared_actions, MANUAL_ACTION)

    def action_input_schemas(
        self, declared: Mapping[str, Mapping[str, Any]]
    ) -> dict[str, dict[str, Any]]:
        """Declared ``input`` schemas plus the reserved ``manual`` schema."""
        self._check_declared_names(declared.keys(), exact=True)
        schemas: dict[str, dict[str, Any]] = {
            action: dict(schema) for action, schema in declared.items()
        }
        schemas[MANUAL_ACTION] = copy.deepcopy(MANUAL_INPUT_SCHEMA)
        return schemas

    def build_family(
        self, declared: Sequence[ChildTool], *, agent: Any | None = None
    ) -> ToolFamily:
        """Compose this plugin's one public family, ``manual`` always appended.

        With *agent*, ``manual`` is bound to that agent's mounted skill; without
        one, the family is schema-only (the ``manual`` child never dispatches),
        which is what a package's import-time schema composition needs.
        """
        self._check_declared_names([child.name for child in declared], exact=True)
        manual = self.manual_child(agent) if agent is not None else self.unbound_manual_child()
        return ToolFamily(self.name, [*declared, manual])

    def _check_declared_names(
        self, declared: "Sequence[str] | Any", *, exact: bool = False
    ) -> None:
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
        for candidate in names:
            if not isinstance(candidate, str) or not candidate.strip():
                raise ToolPluginError(
                    f"ToolPlugin {self.name!r} action names must be non-empty strings"
                )
        if exact and tuple(names) != self.declared_actions:
            raise ToolPluginError(
                f"ToolPlugin {self.name!r} composes {tuple(names)!r}, but declares "
                f"{self.declared_actions!r}; the descriptor is the single source "
                "of truth for this tool's public actions"
            )

    # -- shipped manifest ---------------------------------------------------

    def tool_declaration(self) -> dict[str, Any]:
        """This package's ``plugin.json`` record, in manifest shape.

        The exact object the shipped ``plugin.json`` must contain. Returning it
        here does not register or activate anything: the shipped file remains
        the runtime source the host reads (it is discovered without importing
        any tool package), and this descriptor is what that file must agree
        with — proven by test, not by generating the file at runtime.
        """
        return {
            "schema": TOOL_PLUGIN_SCHEMA,
            "name": self.name,
            "summary": self.summary,
            "homepage": self.homepage,
            "source": BUILTIN_SOURCE,
            "module": self.package,
            "manual": {
                "skill": self.skill_name,
                "bundle": MANUAL_BUNDLE_DIRNAME,
                "install_as": self.install_as,
            },
            "actions": list(self.actions),
        }


# ---------------------------------------------------------------------------
# Runtime discovery / mount contract
# ---------------------------------------------------------------------------
#
# Read by the two hosts that actually mount something:
#
#   * ``Agent._install_intrinsic_manuals`` — copies ``<package>/<manual.bundle>``
#     to ``.library/intrinsic/capabilities/<manual.install_as>/``.
#   * ``lingtai.tools.registry.setup_capability`` — resolves a plugin-backed
#     capability to ``manifest["module"]`` and refuses to proceed when the
#     registry's own ``BUILTIN_TOOLS`` entry disagrees with it.
#
# Discovery is filesystem-only on purpose: it must not import a tool package,
# because ``import lingtai.tools.registry`` deliberately does not import every
# tool (``registry.py`` "Import discipline").


def tools_package_root() -> Path:
    """Filesystem root of the ``lingtai.tools`` package — discovery's only scope."""
    return _package_root(TOOLS_PACKAGE)


def validate_manifest(raw: object, *, directory_name: str) -> tuple[dict | None, str | None]:
    """Validate one decoded manifest → ``(manifest, None)`` or ``(None, error)``.

    Exactly one of the two is non-``None``. Nothing is defaulted or repaired: a
    manifest the host cannot fully trust is rejected with a reason, and the
    caller falls back to its pre-plugin behavior rather than mounting something
    half-understood.
    """
    if not isinstance(raw, dict):
        return None, f"{MANIFEST_FILENAME} must contain a JSON object"
    if raw.get("schema") != TOOL_PLUGIN_SCHEMA:
        return None, f"unsupported manifest schema {raw.get('schema')!r}"
    if raw.get("source") != BUILTIN_SOURCE:
        return None, f"unsupported manifest source {raw.get('source')!r}"
    for key in ("name", "summary", "homepage", "module"):
        value = raw.get(key)
        if not isinstance(value, str) or not value.strip():
            return None, f"manifest {key!r} must be a non-empty string"

    module = raw["module"]
    parent, _, leaf = module.rpartition(".")
    if parent != TOOLS_PACKAGE or leaf != directory_name:
        return None, (
            f"manifest module {module!r} does not name the {directory_name!r} "
            f"package it ships in"
        )

    manual = raw.get("manual")
    if not isinstance(manual, dict):
        return None, "manifest 'manual' must be an object"
    for key in ("skill", "bundle", "install_as"):
        value = manual.get(key)
        if not isinstance(value, str) or not value.strip():
            return None, f"manifest manual.{key} must be a non-empty string"
    if "/" in manual["bundle"] or manual["bundle"].startswith("."):
        # The bundle is a single directory name inside the package, never a
        # path: discovery must not become a way to mount material from outside
        # the declaring package.
        return None, f"manifest manual.bundle must be a plain directory name, got {manual['bundle']!r}"
    if "/" in manual["install_as"] or manual["install_as"].startswith("."):
        return None, (
            "manifest manual.install_as must be a plain capability name, got "
            f"{manual['install_as']!r}"
        )

    actions = raw.get("actions")
    if not isinstance(actions, list) or not actions:
        return None, "manifest 'actions' must be a non-empty array"
    if not all(isinstance(action, str) and action.strip() for action in actions):
        return None, "manifest 'actions' entries must be non-empty strings"
    if actions[-1] != MANUAL_ACTION or actions.count(MANUAL_ACTION) != 1:
        return None, (
            f"manifest 'actions' must end with exactly one reserved "
            f"{MANUAL_ACTION!r} action"
        )
    return dict(raw), None


def read_manifest(directory: Path) -> tuple[dict | None, str | None]:
    """Read and validate one package directory's ``plugin.json``.

    Returns ``(None, None)`` when the directory simply ships no manifest — not
    every built-in tool is a plugin package, and the absence of one is not a
    defect. ``(None, error)`` means a manifest is present but unusable.
    """
    path = directory / MANIFEST_FILENAME
    if not path.is_file():
        return None, None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return None, f"cannot read {MANIFEST_FILENAME}: {exc}"
    return validate_manifest(raw, directory_name=directory.name)


def discover_manifests(root: Path | None = None) -> tuple[dict[str, dict], list[dict[str, str]]]:
    """Scan ``lingtai.tools`` for tool plugin manifests.

    Returns ``(manifests, problems)`` where ``manifests`` maps each declaring
    package *directory name* to its validated manifest, and ``problems`` lists
    ``{"package", "reason"}`` for every directory whose manifest was present but
    unusable. Keyed by directory name because the host scans directories: it is
    exactly the fact it has, and the manifest is what maps it to a public name.
    """
    scan_root = tools_package_root() if root is None else root
    manifests: dict[str, dict] = {}
    problems: list[dict[str, str]] = []
    try:
        children = sorted(scan_root.iterdir())
    except OSError as exc:  # pragma: no cover - platform/filesystem dependent
        return manifests, [{"package": str(scan_root), "reason": f"cannot scan: {exc}"}]
    for child in children:
        if not child.is_dir() or child.name.startswith(("_", ".")):
            continue
        manifest, error = read_manifest(child)
        if error is not None:
            problems.append({"package": child.name, "reason": error})
            continue
        if manifest is not None:
            manifests[child.name] = manifest
    return manifests, problems


def manifest_module(manifests: Mapping[str, Mapping[str, Any]], name: str) -> str | None:
    """The module path a discovered plugin publishes for public *name*, if any."""
    for manifest in manifests.values():
        if manifest.get("name") == name:
            module = manifest.get("module")
            return module if isinstance(module, str) else None
    return None
