"""Intrinsic-tool plugin packaging: one package owns its skill, its registration, and its family shape.

A LingTai-owned tool is not just a module ``registry.INTRINSICS`` happens to
point at. It is a *plugin-style package*: the same folder ships the tool code,
the bundled ``manual/SKILL.md`` the agent reads, and the two runtime records the
host materializes for it — the intrinsic-registry entry that mounts the family,
and the manual-mount entry that installs the packaged skill into
``.library/intrinsic/capabilities/``. This module is the small shared piece that
binds those together for one package, so a tool cannot drift into registering
its module in one place, shipping its manual somewhere else, and advertising a
public action list that silently disagrees with both.

It is the in-process twin of ``lingtai.mcp_servers._plugin.CuratedMcpPlugin``,
which does the same job for a curated stdio MCP. The difference is only what a
runtime record *is*: a curated MCP declares a launcher the catalog publishes; an
intrinsic tool declares a module the intrinsic registry mounts and a skill
bundle the manual installer copies.

It deliberately is **not** a plugin runtime. Nothing here registers a tool,
boots an agent, writes a file, or decides activation. ``lingtai.tools.registry``
still owns :data:`~lingtai.tools.registry.INTRINSICS` and capability setup, and
``Agent._install_intrinsic_manuals`` still owns the wipe/copy/ordering of
``.library/intrinsic/`` — including the decision to install a capability's
manual whether or not the agent enabled it. :func:`discover_intrinsic_plugins`
lets the host *ask* a package where its skill wants to land instead of carrying
a hardcoded directory-name mapping for it; the host remains the only thing that
touches the filesystem, and a package that ships no ``plugin.py`` is untouched.

The one hard promise it enforces is the reserved ``manual`` action
(``tools/CONTRACT.md`` "Every LingTai-owned family MUST offer a ``manual``
action"): a package declares only its *own* actions, and this module appends
``manual`` itself, bound to the package's own installed skill. A package that
tries to declare, re-schema, or re-handle ``manual`` raises
:class:`IntrinsicToolPluginError` at import time rather than shipping a family
whose manual is missing or points somewhere other than its packaged skill.
"""
from __future__ import annotations

import copy
import importlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any

from lingtai.kernel._frontmatter import split_frontmatter

from .tool_family import RESERVED_MANUAL_NAME, ChildTool, ToolFamily
from .tool_family.manual import MANUAL_INPUT_SCHEMA, build_manual_child

__all__ = [
    "CAPABILITIES_SUBDIR",
    "INTRINSIC_SOURCE",
    "MANUAL_ACTION",
    "MANUAL_DIRNAME",
    "PLUGIN_MODULE",
    "SKILL_FILENAME",
    "IntrinsicToolPlugin",
    "IntrinsicToolPluginError",
    "discover_intrinsic_plugins",
    "intrinsic_manual_mounts",
    "strict_empty_input_schema",
]

#: ``source`` stamped on every intrinsic mount record — the value that tells a
#: kernel-shipped intrinsic tool apart from a ``plugin:<name>``-sourced external
#: Agent Plugin (``services/plugin_registry.py``) or a hand-registered one.
INTRINSIC_SOURCE = "lingtai-intrinsic"

#: The reserved action name. Owned by ``lingtai.tools.tool_family``; re-exported
#: here so a plugin package never spells the literal itself.
MANUAL_ACTION = RESERVED_MANUAL_NAME

#: The bundled-skill directory inside a plugin package, and the file in it. This
#: is the existing per-tool manual layout ``Agent._install_intrinsic_manuals``
#: already scans for (``email/manual/SKILL.md``, ``daemon/manual/SKILL.md``, …);
#: the descriptor names it rather than inventing a second convention.
MANUAL_DIRNAME = "manual"
SKILL_FILENAME = "SKILL.md"

#: Where the host installs skill bundles under ``.library/intrinsic/``. Stated
#: here only so :meth:`IntrinsicToolPlugin.manual_mount_declaration` can express
#: a mount as one comparable string; the host still joins it to a real path.
CAPABILITIES_SUBDIR = "capabilities"

#: The submodule a package ships to declare itself a plugin. Discovery looks for
#: exactly this name and imports nothing else.
PLUGIN_MODULE = "plugin"


class IntrinsicToolPluginError(ValueError):
    """Raised for an intrinsic-tool packaging defect (bad descriptor or shape)."""


def strict_empty_input_schema() -> dict[str, Any]:
    """The canonical closed, argument-free ``input`` schema for an action.

    A copy of ``tool_family.manual.MANUAL_INPUT_SCHEMA`` — the one owned
    definition — so a plugin's composed ``manual`` branch is byte-identical to
    the child that dispatches it.
    """
    return copy.deepcopy(MANUAL_INPUT_SCHEMA)


@dataclass(frozen=True)
class IntrinsicToolPlugin:
    """One intrinsic tool package's identity, packaged skill, and runtime records.

    ``name`` is the public family root, the intrinsic-registry key, and the
    model-facing tool name; ``package`` is the Python package that ships both
    the tool module and the ``manual/SKILL.md`` its ``manual`` action serves.
    The two are required to agree (``package`` must end in ``name``) because
    :meth:`intrinsic_declaration` publishes that very module as what the
    registry mounts under ``name`` — a descriptor whose module and registry name
    disagree would advertise somebody else's tool.

    ``mount_name`` is the directory the packaged skill installs into under
    ``.library/intrinsic/capabilities/``. It is declared rather than derived
    because the installed directory name is a *model-visible* fact — it is the
    ``manual_path`` every ``manual`` result reports and the skill-catalog entry
    the agent browses — so a package renaming its Python module must not
    silently move its manual out from under the agent. It defaults to ``name``,
    which is what a package with nothing to say should use.

    The bundled skill is loaded once at construction and its frontmatter
    ``name`` is checked against ``skill_name``, so a package that renames or
    loses its manual fails loudly at import instead of shipping a family whose
    ``manual`` action installs and serves nothing.
    """

    name: str
    package: str
    summary: str
    skill_name: str
    mount_name: str = ""

    # Loaded from the package's bundled manual/SKILL.md at construction.
    # Excluded from init/repr/eq: derived material, not declared identity.
    _skill_frontmatter: dict[str, str] = field(init=False, repr=False, compare=False)
    _skill_body: str = field(init=False, repr=False, compare=False)
    _skill_text: str = field(init=False, repr=False, compare=False)
    _skill_path: str = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        for attribute in ("name", "package", "summary", "skill_name"):
            value = getattr(self, attribute)
            if not isinstance(value, str) or not value.strip():
                raise IntrinsicToolPluginError(
                    f"IntrinsicToolPlugin {attribute!r} must be a non-empty string"
                )
        if not isinstance(self.mount_name, str) or (
            self.mount_name and not self.mount_name.strip()
        ):
            raise IntrinsicToolPluginError(
                "IntrinsicToolPlugin 'mount_name' must be a non-empty string when given"
            )
        if not self.mount_name:
            object.__setattr__(self, "mount_name", self.name)
        if "/" in self.mount_name or self.mount_name in (".", ".."):
            raise IntrinsicToolPluginError(
                f"IntrinsicToolPlugin {self.name!r} mount_name {self.mount_name!r} "
                "must be one directory name under the installed capability catalog"
            )
        if self.package.rpartition(".")[2] != self.name:
            raise IntrinsicToolPluginError(
                f"IntrinsicToolPlugin package {self.package!r} must be the "
                f"{self.name!r} module so its declared registration is its own module"
            )
        frontmatter, body, text, path = _load_packaged_skill(self.package)
        if frontmatter.get("name") != self.skill_name:
            raise IntrinsicToolPluginError(
                f"IntrinsicToolPlugin {self.name!r} bundled "
                f"{MANUAL_DIRNAME}/{SKILL_FILENAME} declares name "
                f"{frontmatter.get('name')!r}, expected {self.skill_name!r}"
            )
        if not body.strip():
            raise IntrinsicToolPluginError(
                f"IntrinsicToolPlugin {self.name!r} bundled "
                f"{MANUAL_DIRNAME}/{SKILL_FILENAME} has an empty body"
            )
        object.__setattr__(self, "_skill_frontmatter", frontmatter)
        object.__setattr__(self, "_skill_body", body)
        object.__setattr__(self, "_skill_text", text)
        object.__setattr__(self, "_skill_path", path)

    # -- packaged skill -----------------------------------------------------

    @property
    def skill_frontmatter(self) -> dict[str, str]:
        """Parsed ``SKILL.md`` frontmatter (the manual's skill-catalog entry)."""
        return dict(self._skill_frontmatter)

    @property
    def skill_body(self) -> str:
        """The packaged ``SKILL.md`` markdown body, frontmatter stripped."""
        return self._skill_body

    @property
    def skill_text(self) -> str:
        """The packaged ``SKILL.md`` verbatim — the exact bytes the host installs.

        This is what ``manual`` ultimately serves: the installer copies this
        file unchanged, and the reserved child reads the installed copy back.
        """
        return self._skill_text

    @property
    def skill_path(self) -> str:
        """Absolute resolved path of the packaged (not installed) ``SKILL.md``."""
        return self._skill_path

    # -- family composition -------------------------------------------------

    def manual_child(self, agent: Any) -> ChildTool:
        """The plugin-owned reserved ``manual`` child, bound to this package's skill.

        Built from the shared :func:`~lingtai.tools.tool_family.manual.build_manual_child`
        against this plugin's own :attr:`mount_name`, so ``manual`` reads the
        installed copy of *this* package's skill and cannot be rebound to other
        material by the tool's own child registry.

        Reading the installed copy rather than the packaged one is the host
        boundary, kept deliberately: the agent's ``.library/`` is the agent's
        view of its own capabilities, an operator-visible file whose absence is
        reported truthfully as ``status='degraded'`` instead of being papered
        over by an in-wheel read.
        """
        return build_manual_child(agent, self.mount_name)

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

    def build_family(self, agent: Any, declared: Sequence[ChildTool]) -> ToolFamily:
        """Compose this plugin's one public family, ``manual`` always appended.

        ``agent`` may be ``None`` for a schema-only family whose children are
        never dispatched — only their schemas are read.
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
                f"{MANUAL_DIRNAME}/{SKILL_FILENAME}"
            )
        if len(set(names)) != len(names):
            raise IntrinsicToolPluginError(
                f"IntrinsicToolPlugin {self.name!r} declared a duplicate action"
            )

    # -- shipped runtime records -------------------------------------------

    def intrinsic_declaration(self) -> dict[str, Any]:
        """This package's intrinsic-registry record, in ``INTRINSICS`` shape.

        The same ``{"module": <module>}`` value ``lingtai.tools.registry``
        publishes and ``BaseAgent._wire_intrinsics`` iterates. Returning it here
        registers and mounts nothing: ``registry.INTRINSICS`` remains the
        runtime mapping the kernel is handed, and this descriptor is what that
        entry must agree with.

        The module is imported lazily, on call — a plugin descriptor is
        constructed *by* its own package's import, so resolving it eagerly would
        close an import cycle on the package that owns it.
        """
        return {"module": importlib.import_module(self.package)}

    def manual_mount_declaration(self) -> dict[str, Any]:
        """This package's manual-mount record: which skill lands where, from where.

        The record ``Agent._install_intrinsic_manuals`` materializes for this
        package on every boot and refresh. ``bundle`` is the packaged source
        directory relative to ``lingtai/tools/``; ``mount`` is the destination
        relative to ``.library/intrinsic/``. Returning it here copies nothing:
        the installer remains the only writer, and this is what its result must
        agree with.
        """
        return {
            "name": self.name,
            "summary": self.summary,
            "source": INTRINSIC_SOURCE,
            "package": self.package,
            "bundle": f"{self.name}/{MANUAL_DIRNAME}",
            "skill": self.skill_name,
            "mount": f"{CAPABILITIES_SUBDIR}/{self.mount_name}",
        }


def _load_packaged_skill(package: str) -> tuple[dict[str, str], str, str, str]:
    """Load a plugin package's bundled manual → (frontmatter, body, text, path)."""
    resource = resources.files(package).joinpath(MANUAL_DIRNAME, SKILL_FILENAME)
    try:
        text = resource.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError) as exc:
        raise IntrinsicToolPluginError(
            f"IntrinsicToolPlugin package {package!r} ships no "
            f"{MANUAL_DIRNAME}/{SKILL_FILENAME}"
        ) from exc
    frontmatter, body = split_frontmatter(text)
    return frontmatter, body, text, str(resource)


def discover_intrinsic_plugins() -> dict[str, IntrinsicToolPlugin]:
    """Find every ``lingtai.tools`` package that declares itself a plugin.

    Returns ``{package directory name: descriptor}`` for each subpackage
    shipping a :data:`PLUGIN_MODULE` submodule that defines exactly one
    :class:`IntrinsicToolPlugin`. This is *discovery only* — the caller decides
    what, if anything, to do with a descriptor; nothing here mounts, installs,
    registers, or activates.

    Only ``lingtai.tools.<pkg>.plugin`` is imported, never every tool package:
    a package without a ``plugin.py`` is listed by the directory scan and then
    skipped untouched, preserving ``registry.py``'s rule that importing the
    registry must not eagerly import every tool.

    A broken descriptor raises rather than being skipped. These are
    kernel-shipped packages, so a ``plugin.py`` that imports but declares no
    descriptor — or two — is a packaging defect that must fail at the seam
    instead of silently un-mounting a manual an agent expects to read.
    """
    package_root = Path(__file__).resolve().parent
    found: dict[str, IntrinsicToolPlugin] = {}
    for entry in sorted(package_root.iterdir()):
        if not entry.is_dir() or entry.name.startswith("_"):
            continue
        if not (entry / f"{PLUGIN_MODULE}.py").is_file():
            continue
        module = importlib.import_module(f"{__package__}.{entry.name}.{PLUGIN_MODULE}")
        descriptors = [
            value
            for key, value in vars(module).items()
            if not key.startswith("_") and isinstance(value, IntrinsicToolPlugin)
        ]
        unique = {id(descriptor): descriptor for descriptor in descriptors}
        if len(unique) != 1:
            raise IntrinsicToolPluginError(
                f"{module.__name__} must define exactly one IntrinsicToolPlugin, "
                f"found {len(unique)}"
            )
        found[entry.name] = next(iter(unique.values()))
    return found


def intrinsic_manual_mounts() -> dict[str, str]:
    """``package directory name -> declared installed-skill directory name``.

    The one thing ``Agent._install_intrinsic_manuals`` asks the tools package
    for: where each plugin wants its bundled ``manual/`` installed under
    ``.library/intrinsic/capabilities/``. A package that ships no ``plugin.py``
    is absent here and keeps the host's directory-name default.
    """
    return {
        directory: plugin.mount_name
        for directory, plugin in discover_intrinsic_plugins().items()
    }
