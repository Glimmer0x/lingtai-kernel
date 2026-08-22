"""Intrinsic plugin packaging: one package owns its skill, family, and mount record.

An intrinsic tool is not just a module ``registry.INTRINSICS`` happens to name.
It is a *plugin-style package*: the same folder ships the handlers, states which
kernel-shipped ``SKILL.md`` is its manual, and declares the mount record the
registry publishes for it. This module is the small shared piece that binds
those three together for one package, so an intrinsic cannot drift into
declaring its actions in one place, its manual in another, and a registry
identity that silently disagrees with both.

It is the ``lingtai.tools`` twin of :mod:`lingtai.mcp_servers._plugin`, which
does the same job for curated MCP packages. The two are deliberately separate
implementations of the same *shape* rather than one shared base: a curated MCP
is launched out-of-process from ``mcp_catalog.json`` and answers ``manual``
from a skill bundled in its own wheel folder, while an intrinsic is imported
in-process and answers ``manual`` from the copy the boot installer wrote into
the agent's ``.library/intrinsic/capabilities/``. Forcing one class over both
would have to fake one of those two runtimes.

Like its MCP twin, this is **not** a plugin runtime. Nothing here activates,
gates, sandboxes, or lifecycle-manages anything, and it introduces no second
registry: ``lingtai.tools.registry`` still owns which intrinsics are mandatory,
``BaseAgent._wire_intrinsics`` still owns binding them to the tool surface,
``Agent._install_intrinsic_manuals`` still owns copying manuals onto disk, and
``lingtai.services.plugin_registry`` still owns external Agent Plugins v1.0.0
directories. What this module adds is discovery and a checked mount: the
registry asks a module for its descriptor (:func:`plugin_of`) and builds the
intrinsic record from it (:func:`mount_intrinsics`) instead of restating the
package's identity by hand.

The two hard promises it enforces:

* **The reserved ``manual`` action** (``tools/CONTRACT.md`` "Every LingTai-owned
  family MUST offer a ``manual`` action"): a package declares only its *own*
  actions and this module appends ``manual`` itself, bound to the package's
  declared skill. A package that tries to declare, re-schema, or re-handle
  ``manual`` raises :class:`IntrinsicPluginError` at import time.
* **The manual is the package's own skill.** The descriptor resolves the
  kernel-shipped source of its manual at construction and checks the
  frontmatter ``name``, so a package that renames, moves, or empties its manual
  fails loudly at import instead of shipping a family whose ``manual`` silently
  degrades to an empty body on every agent.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from importlib import import_module
from importlib.util import find_spec
from pathlib import Path
from types import ModuleType
from typing import Any, Mapping, Sequence

from lingtai.kernel._frontmatter import split_frontmatter

from .tool_family import RESERVED_MANUAL_NAME, ChildTool, ToolFamily
from .tool_family.manual import MANUAL_INPUT_SCHEMA, build_manual_child

__all__ = [
    "INTRINSIC_SKILLS_PACKAGE",
    "INTRINSIC_SOURCE",
    "MANUAL_ACTION",
    "PACKAGE_MANUAL_DIR",
    "PLUGIN_ATTRIBUTE",
    "SKILL_FILENAME",
    "IntrinsicPlugin",
    "IntrinsicPluginError",
    "load_declared_module",
    "mount_intrinsics",
    "plugin_of",
]

#: ``source`` stamped on every intrinsic mount record — the value that tells a
#: kernel-shipped mandatory intrinsic apart from a ``plugin:<name>``-sourced or
#: capability-configured tool.
INTRINSIC_SOURCE = "lingtai-intrinsic"

#: The reserved action name. Owned by ``lingtai.tools.tool_family``; re-exported
#: here so an intrinsic package never spells the literal itself.
MANUAL_ACTION = RESERVED_MANUAL_NAME

#: The standard skill filename every manual bundle ships.
SKILL_FILENAME = "SKILL.md"

#: The subdirectory ``Agent._install_intrinsic_manuals``'s ``install_from`` pass
#: looks for inside a tool package (``<pkg>/manual/`` → ``capabilities/<pkg>``).
PACKAGE_MANUAL_DIR = "manual"

#: The package holding the standalone skill bundles ``install_skills_from``
#: copies verbatim (``<bundle>/`` → ``capabilities/<bundle>``). An intrinsic
#: whose manual is a shared router rather than a per-tool guide ships it here.
INTRINSIC_SKILLS_PACKAGE = "lingtai.intrinsic_skills"


class IntrinsicPluginError(ValueError):
    """Raised for an intrinsic packaging defect (bad descriptor or shape)."""


@dataclass(frozen=True)
class IntrinsicPlugin:
    """One intrinsic package's identity, owned manual skill, and mount record.

    ``name`` is the registry key and the public family name; ``package`` is the
    Python package that ships the handlers. The two are required to agree
    (``package`` must end in ``name``) because :meth:`intrinsic_declaration`
    publishes ``package`` as this plugin's module — a descriptor whose module
    and registry name disagree would advertise a mount for something else.

    ``skill_package``/``skill_dir`` name the *shipped source* of this plugin's
    manual: either the package's own ``manual/`` folder, or a standalone bundle
    under ``lingtai.intrinsic_skills``. Both are what
    ``Agent._install_intrinsic_manuals`` copies into
    ``.library/intrinsic/capabilities/`` at boot, so :attr:`install_name` — the
    capability directory ``manual`` reads back at runtime — is *derived* from
    the same two fields rather than restated, and cannot drift from the
    installer's own two passes. Pass ``install_name`` explicitly only for a
    package the installer deliberately renames on the way in.

    The shipped skill is loaded once at construction and its frontmatter
    ``name`` is checked against ``skill_name``, so a package that renames or
    loses its manual fails at import rather than degrading to an empty
    ``manual`` on every agent.
    """

    name: str
    package: str
    summary: str
    homepage: str
    skill_name: str
    skill_package: str | None = None
    skill_dir: str | None = None
    install_name: str | None = None

    # Loaded from the shipped skill bundle at construction. Excluded from
    # init/repr/eq: they are derived material, not part of the descriptor's
    # declared identity.
    _skill_frontmatter: dict[str, str] = field(init=False, repr=False, compare=False)
    _skill_body: str = field(init=False, repr=False, compare=False)
    _skill_path: str = field(init=False, repr=False, compare=False)
    _install_name: str = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        for attribute in ("name", "package", "summary", "homepage", "skill_name"):
            value = getattr(self, attribute)
            if not isinstance(value, str) or not value.strip():
                raise IntrinsicPluginError(
                    f"IntrinsicPlugin {attribute!r} must be a non-empty string"
                )
        if self.package.rpartition(".")[2] != self.name:
            raise IntrinsicPluginError(
                f"IntrinsicPlugin package {self.package!r} must be the "
                f"{self.name!r} module so its declared mount is its own module"
            )

        skill_package = self.skill_package or self.package
        skill_dir = self.skill_dir or PACKAGE_MANUAL_DIR
        frontmatter, body, path = _load_shipped_skill(skill_package, skill_dir)
        if frontmatter.get("name") != self.skill_name:
            raise IntrinsicPluginError(
                f"IntrinsicPlugin {self.name!r} shipped {skill_dir}/{SKILL_FILENAME} "
                f"declares name {frontmatter.get('name')!r}, expected {self.skill_name!r}"
            )
        if not body.strip():
            raise IntrinsicPluginError(
                f"IntrinsicPlugin {self.name!r} shipped {skill_dir}/{SKILL_FILENAME} "
                "has an empty body"
            )

        object.__setattr__(self, "_skill_frontmatter", frontmatter)
        object.__setattr__(self, "_skill_body", body)
        object.__setattr__(self, "_skill_path", path)
        object.__setattr__(
            self,
            "_install_name",
            self.install_name or _derive_install_name(self.name, skill_package, skill_dir, self.package),
        )

    # -- owned manual skill -------------------------------------------------

    @property
    def skill_frontmatter(self) -> dict[str, str]:
        """Parsed frontmatter of the shipped ``SKILL.md`` behind ``manual``."""
        return self._skill_frontmatter

    @property
    def skill_body(self) -> str:
        """The shipped ``SKILL.md`` markdown body the installer copies."""
        return self._skill_body

    @property
    def skill_source_path(self) -> str:
        """Absolute resolved path of the shipped (pre-install) ``SKILL.md``."""
        return self._skill_path

    @property
    def installed_capability(self) -> str:
        """The ``.library/intrinsic/capabilities/<dir>`` ``manual`` reads back.

        Derived from the shipped-skill location so it matches whichever of
        ``Agent._install_intrinsic_manuals``'s two passes will install this
        plugin's bundle. This is the value handed to ``load_installed_manual``,
        not the family name and not the frontmatter ``name``.
        """
        return self._install_name

    def manual_child(self, agent: Any) -> ChildTool:
        """The plugin-owned reserved ``manual`` child, bound to *agent*.

        Delegates to the shared ``tool_family.manual.build_manual_child`` so the
        runtime result shape, the strict-empty input, and the missing-manual
        degraded payload are exactly the generic contract's — this descriptor
        adds ownership of *which* skill, not a second manual implementation.
        Because the child closes over :attr:`installed_capability`, ``manual``
        never routes through the package's action handlers and cannot be
        rebound to other material.
        """
        return build_manual_child(agent, self._install_name)

    # -- family composition -------------------------------------------------

    def actions(self, declared: Sequence[str]) -> tuple[str, ...]:
        """Declared actions plus the reserved ``manual``, in that order."""
        self._check_declared_names(declared)
        return tuple(declared) + (MANUAL_ACTION,)

    def action_input_schemas(
        self, declared: Mapping[str, dict[str, Any]]
    ) -> dict[str, dict[str, Any]]:
        """Declared ``input`` schemas plus the reserved ``manual`` schema.

        The declared schema objects are carried through by reference, not
        copied: a family's per-action schema literals are the same objects its
        children are built from, and duplicating them here would create a
        second set that could drift. ``manual`` references the one
        ``tool_family``-owned :data:`MANUAL_INPUT_SCHEMA` literal for the same
        reason.
        """
        self._check_declared_names(declared.keys())
        schemas: dict[str, dict[str, Any]] = dict(declared)
        schemas[MANUAL_ACTION] = MANUAL_INPUT_SCHEMA
        return schemas

    def compose_children(
        self, agent: Any, declared: Sequence[ChildTool]
    ) -> list[ChildTool]:
        """This plugin's complete child list — declared, then reserved ``manual``.

        The one place the "+ manual" rule is applied, so a package that wants
        the child list and a package that wants the family cannot end up with
        two different answers. ``agent`` may be ``None`` for a schema-only
        list whose children are never dispatched — only their schemas are read.
        """
        self._check_declared_names([child.name for child in declared])
        return [*declared, self.manual_child(agent)]

    def build_family(self, agent: Any, declared: Sequence[ChildTool]) -> ToolFamily:
        """Compose this plugin's one public family, ``manual`` always appended."""
        return ToolFamily(self.name, self.compose_children(agent, declared))

    def _check_declared_names(self, declared: Any) -> None:
        names = list(declared)
        if not names:
            raise IntrinsicPluginError(
                f"IntrinsicPlugin {self.name!r} must declare at least one action"
            )
        if MANUAL_ACTION in names:
            raise IntrinsicPluginError(
                f"IntrinsicPlugin {self.name!r} must not declare the reserved "
                f"{MANUAL_ACTION!r} action; it is appended from the plugin's own "
                f"{self.skill_name!r} skill"
            )
        if len(set(names)) != len(names):
            raise IntrinsicPluginError(
                f"IntrinsicPlugin {self.name!r} declared a duplicate action"
            )

    # -- shipped mount declaration -----------------------------------------

    def intrinsic_declaration(self) -> dict[str, Any]:
        """This package's mount record, in registry-record shape.

        The declarative half of what ``registry.INTRINSICS`` publishes for this
        plugin. Returning it here activates nothing: :func:`mount_intrinsics`
        is what turns it into the ``{"module": <module>}`` entry ``BaseAgent``
        consumes, and the registry's own mapping stays the mandatory-include
        mechanism.
        """
        return {
            "name": self.name,
            "summary": self.summary,
            "mount": "intrinsic",
            "module": self.package,
            "source": INTRINSIC_SOURCE,
            "homepage": self.homepage,
            "manual_skill": self.skill_name,
            "manual_capability": self._install_name,
        }


def _package_directory(package: str) -> Path:
    """Locate a package's own directory *without importing it*.

    ``importlib.resources.files`` would import the package, and an intrinsic's
    manual bundle may live in ``lingtai.intrinsic_skills`` — a high-level
    ``lingtai`` submodule that importing ``lingtai.tools`` must not eagerly
    pull (``tools/__init__.py`` "Import DAG", pinned by
    ``tests/test_kernel_isolation.py::test_import_lingtai_tools_does_not_pull_high_level_lingtai``).
    ``find_spec`` resolves the location from the already-imported parent
    package's search path without executing the module itself.

    Resolving to a real directory rather than to a ``Traversable`` matches what
    ``Agent._install_intrinsic_manuals`` already does with these same bundles
    (``Path(pkg.__file__).parent`` + ``shutil.copytree``), so the descriptor
    reads exactly the tree the installer will copy.
    """
    try:
        spec = find_spec(package)
    except (ImportError, ValueError) as exc:  # unimportable parent
        raise IntrinsicPluginError(f"skill package {package!r} is unresolvable: {exc}") from exc
    locations = getattr(spec, "submodule_search_locations", None) if spec else None
    if not locations:
        raise IntrinsicPluginError(
            f"skill package {package!r} is not an importable package directory"
        )
    return Path(next(iter(locations)))


def _load_shipped_skill(
    skill_package: str, skill_dir: str
) -> tuple[dict[str, str], str, str]:
    """Load a shipped skill bundle's ``SKILL.md`` → (frontmatter, body, path)."""
    path = _package_directory(skill_package) / skill_dir / SKILL_FILENAME
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise IntrinsicPluginError(
            f"shipped skill {skill_package}/{skill_dir}/{SKILL_FILENAME} is unreadable: {exc}"
        ) from exc
    frontmatter, body = split_frontmatter(text)
    return frontmatter, body, str(path)


def _derive_install_name(
    name: str, skill_package: str, skill_dir: str, package: str
) -> str:
    """Where ``Agent._install_intrinsic_manuals`` will put this plugin's bundle.

    Mirrors the installer's two passes exactly: a package-owned ``manual/``
    folder installs under the *tool* name, while a standalone
    ``lingtai.intrinsic_skills`` bundle is copied verbatim under its own
    directory name.
    """
    if skill_package == package and skill_dir == PACKAGE_MANUAL_DIR:
        return name
    return skill_dir


# ---------------------------------------------------------------------------
# Discovery and mount
# ---------------------------------------------------------------------------

#: The attribute an intrinsic package exposes to advertise its descriptor.
PLUGIN_ATTRIBUTE = "PLUGIN"


def plugin_of(module: ModuleType) -> IntrinsicPlugin | None:
    """Return *module*'s declared plugin descriptor, or ``None`` if it ships none.

    Discovery is opt-in and duck-typed on one well-known attribute rather than
    on package scanning: an intrinsic that has not been packaged yet simply has
    no ``PLUGIN`` and keeps its hand-written registry entry, so this can be
    adopted one package at a time. A ``PLUGIN`` of the wrong type is a defect,
    not an opt-out, and raises.
    """
    plugin = getattr(module, PLUGIN_ATTRIBUTE, None)
    if plugin is None:
        return None
    if not isinstance(plugin, IntrinsicPlugin):
        raise IntrinsicPluginError(
            f"{module.__name__}.{PLUGIN_ATTRIBUTE} must be an IntrinsicPlugin, "
            f"got {type(plugin).__name__}"
        )
    return plugin


def mount_intrinsics(
    modules: Mapping[str, ModuleType]
) -> dict[str, dict[str, Any]]:
    """Build the ``INTRINSICS`` mapping, checking every packaged plugin's identity.

    The registry passes the modules it has decided are mandatory; this returns
    the ``{name: {"module": <module>}}`` records ``BaseAgent._wire_intrinsics``
    consumes — the *same* record shape as before, so nothing downstream changes.
    What it adds is the check that used to be impossible: for every module that
    ships a descriptor, the registry key, the descriptor's ``name``, and the
    descriptor's ``package`` must all agree, so a packaged intrinsic cannot be
    mounted under a name it does not claim.

    Membership stays the host's: this function mounts exactly what it is given
    and discovers nothing on its own.
    """
    records: dict[str, dict[str, Any]] = {}
    for name, module in modules.items():
        plugin = plugin_of(module)
        if plugin is not None:
            if plugin.name != name:
                raise IntrinsicPluginError(
                    f"intrinsic {name!r} is mounted from {module.__name__}, whose "
                    f"plugin declares name {plugin.name!r}"
                )
            if plugin.package != module.__name__:
                raise IntrinsicPluginError(
                    f"intrinsic {name!r} plugin declares package "
                    f"{plugin.package!r} but was mounted from {module.__name__!r}"
                )
        records[name] = {"module": module}
    return records


def load_declared_module(plugin: IntrinsicPlugin) -> ModuleType:
    """Import the module a descriptor declares.

    Used by tests and diagnostics that hold a descriptor and need to reach the
    package it names. The registry never needs this — it already holds the
    imported modules — which is why mounting does not import by name.
    """
    return import_module(plugin.package)
