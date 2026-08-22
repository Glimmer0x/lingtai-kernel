"""Tool-plugin packaging: one tool package owns its declaration, skill, and family.

The tools-layer twin of :mod:`lingtai.mcp_servers._plugin`. A curated MCP is not
just a module the catalog happens to launch, and a built-in tool is not just a
module the registry happens to import: it is a *plugin-style package*. The same
folder ships the handler code, the bundled ``manual/SKILL.md`` the agent reads,
and the capability declaration the built-in registry publishes for it. This
module is the small shared piece that binds those three together for one tool
package, so a tool cannot drift into declaring its module in one place, its
manual in another, and a public action list that silently disagrees with both.

It deliberately is **not** a plugin runtime, and — the point that matters most
here — it is **not** the Agent Plugins runtime. Two different things are called
"plugin" in this kernel and they must never be confused:

- An **Agent Plugin** (agent-plugins.org v1.0.0) is a third-party *directory* on
  disk carrying a ``plugin.json``. ``lingtai.services.plugin_registry`` discovers,
  validates, and registers those; records it writes are stamped
  ``source="plugin:<name>"``; the model-facing ``plugin`` tool renders that
  catalog. Nothing in this module participates in that path.
- A **tool plugin** — :class:`ToolPlugin` below — is a kernel-shipped Python
  package under ``lingtai.tools``. It is compiled into the wheel, declared in
  ``lingtai.tools.registry``, and mounted by the host. It carries no
  ``plugin.json``, is never scanned by ``read_plugins``, and never produces a
  ``plugin:`` source stamp.

Keeping that line sharp is what makes packaging the ``plugin`` *tool* itself as
a tool plugin safe rather than recursive. If the two notions shared machinery,
the tool that reports Agent Plugins would be an Agent Plugin, boot would have to
mount the reporter before it could report, and uninstalling "plugin" would mean
pruning the kernel's own capability. :meth:`ToolPlugin.__post_init__` therefore
*rejects* a package that ships a ``plugin.json`` at import time, rather than
trusting the boundary to stay uncrossed by convention.

Nothing here discovers capabilities on the host's behalf, imports them by name
at registry-import time, registers them, or reads configuration: activation,
execution policy, audit, lifecycle, and namespace decisions all remain the
host's. ``lingtai.tools.registry`` still owns ``BUILTIN_TOOLS``/``CORE_DEFAULTS``
and ``setup_capability``; ``Agent._install_intrinsic_manuals`` still owns the
copy into ``.library/intrinsic/``. A :class:`ToolPlugin` is a declarative
descriptor plus composition helpers that its own package calls explicitly, and
one lazy lookup (:func:`declared_manual_destinations`) the host may consult to
learn where a package says its manual mounts.

The one hard promise it enforces is the reserved ``manual`` action
(``tools/CONTRACT.md`` "Dispatch and actions"): a package declares only its
*own* actions, and this module appends ``manual`` itself, bound to the skill the
package ships. A package that tries to declare, re-schema, or re-handle
``manual`` raises :class:`ToolPluginError` at import time rather than shipping a
family whose manual is missing or points somewhere other than its packaged
skill.
"""
from __future__ import annotations

import copy
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from importlib import import_module, resources
from pathlib import Path
from typing import Any

from ._catalog import parse_frontmatter
from .tool_family import RESERVED_MANUAL_NAME, ChildTool, ToolFamily
from .tool_family.manual import MANUAL_INPUT_SCHEMA, build_manual_child

log = logging.getLogger(__name__)

__all__ = [
    "MANUAL_ACTION",
    "MANUAL_DIRNAME",
    "SKILL_FILENAME",
    "TOOL_PLUGIN_ATTRIBUTE",
    "TOOL_PLUGIN_MODULE",
    "ToolPlugin",
    "ToolPluginError",
    "declared_manual_destinations",
    "iter_tool_plugins",
    "strict_empty_input_schema",
]

#: The reserved action name. Owned by ``lingtai.tools.tool_family``; re-exported
#: here so a tool package never spells the literal itself.
MANUAL_ACTION = RESERVED_MANUAL_NAME

#: A tool package ships its skill as ``<package>/manual/SKILL.md``. The directory
#: is what ``Agent._install_intrinsic_manuals`` copies; the file is what the
#: skills catalog parses and what ``action="manual"`` ultimately returns.
MANUAL_DIRNAME = "manual"
SKILL_FILENAME = "SKILL.md"

#: The submodule a tool package puts its descriptor in, and the attribute the
#: descriptor is bound to. Discovery looks for exactly this pair — a package
#: without it is simply not a tool plugin, which is the normal case today.
TOOL_PLUGIN_MODULE = "plugin"
TOOL_PLUGIN_ATTRIBUTE = "TOOL_PLUGIN"

#: The Agent Plugins v1.0.0 manifest filename. Named here only to *forbid* it:
#: a kernel-shipped tool package carrying one would be claiming to be a
#: third-party Agent Plugin directory, which is the recursion this module exists
#: to prevent. Kept as a literal rather than imported from
#: ``lingtai.services.plugin_registry`` — ``lingtai.tools`` may reach ``lingtai``
#: services only lazily inside handlers, never at module top.
_AGENT_PLUGIN_MANIFEST_FILENAME = "plugin.json"

_TOOLS_PACKAGE = "lingtai.tools"

#: Upper bound on the skill description woven into the schema's ``manual``
#: action line. The line is always-on prompt weight; the full frontmatter — and
#: the whole document behind it — stays one ``action="manual"`` call away.
_MAX_MANUAL_DESCRIPTION_LEN = 240


class ToolPluginError(ValueError):
    """Raised for a tool-plugin packaging defect (bad descriptor or shape)."""


def _clip(description: str) -> str:
    """Clip a skill description to the schema budget, on a word boundary."""
    text = " ".join(description.split())
    if len(text) <= _MAX_MANUAL_DESCRIPTION_LEN:
        return text
    head = text[:_MAX_MANUAL_DESCRIPTION_LEN].rsplit(" ", 1)[0].rstrip(" ,;:—-")
    return f"{head}…"


def strict_empty_input_schema() -> dict[str, Any]:
    """The canonical closed, argument-free ``input`` schema for an action.

    A deep copy of the one owned :data:`~lingtai.tools.tool_family.manual.MANUAL_INPUT_SCHEMA`
    literal rather than a second spelling of it, so a tool plugin's actions and
    the generic ``manual`` child can never advertise different empty shapes; the
    copy keeps one family's child from mutating another's nested ``properties``.
    """
    return copy.deepcopy(MANUAL_INPUT_SCHEMA)


@dataclass(frozen=True)
class ToolPlugin:
    """One tool package's identity, packaged skill, and capability declaration.

    ``name`` is the public tool name and the capability name the registry keys
    on; ``package`` is the Python package that ships both the handler module and
    the ``manual/SKILL.md`` the ``manual`` action returns. ``package`` must live
    under ``lingtai.tools`` because :meth:`capability_declaration` publishes it
    as this capability's import path — a descriptor pointing outside the tools
    package would advertise a module the built-in registry must not import.

    ``manual_destination`` is the ``.library/intrinsic/capabilities/<name>/``
    directory the package's ``manual/`` bundle mounts into. It is declared, not
    inferred from the directory name, because the implementation package and the
    public name are allowed to differ (``bash`` implements ``shell``,
    ``web_search`` implements ``web``) and a guessed destination is how an
    installed manual silently ends up under the wrong capability.

    The bundled skill is loaded once at construction and its frontmatter ``name``
    is checked against ``skill_name``, so a package that renames or loses its
    manual fails loudly at import instead of serving an empty or foreign
    ``manual``.
    """

    name: str
    package: str
    summary: str
    skill_name: str
    manual_destination: str
    #: The ``CORE_DEFAULTS`` kwargs this capability boots with on every agent, or
    #: ``None`` for a capability that is opt-in. ``{}`` (default-on, no kwargs)
    #: and ``None`` (not default-on) are different declarations, so the type is
    #: deliberately nullable rather than defaulting to an empty mapping.
    default_kwargs: Mapping[str, Any] | None = None

    # Loaded from the package's bundled manual/SKILL.md at construction.
    # Excluded from init/repr/eq: derived material, not declared identity.
    _skill_frontmatter: dict[str, str] = field(init=False, repr=False, compare=False)
    _skill_text: str = field(init=False, repr=False, compare=False)
    _skill_path: str = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        for attribute in ("name", "package", "summary", "skill_name", "manual_destination"):
            value = getattr(self, attribute)
            if not isinstance(value, str) or not value.strip():
                raise ToolPluginError(
                    f"ToolPlugin {attribute!r} must be a non-empty string"
                )
        if not self.package.startswith(f"{_TOOLS_PACKAGE}."):
            raise ToolPluginError(
                f"ToolPlugin package {self.package!r} must live under "
                f"{_TOOLS_PACKAGE!r} so its declared module is a built-in tool"
            )
        if self.default_kwargs is not None and not isinstance(self.default_kwargs, Mapping):
            raise ToolPluginError(
                f"ToolPlugin {self.name!r} default_kwargs must be a mapping or None"
            )

        package_root = Path(str(resources.files(self.package)))
        # The anti-recursion gate. A kernel-shipped tool package that also
        # carried an Agent Plugins v1.0.0 manifest would be discoverable by
        # ``services.plugin_registry.read_plugins`` as a third-party plugin —
        # so the ``plugin`` tool would list itself, and a declared tools
        # directory would "register" the kernel's own capabilities. Fail at
        # import rather than let that shape ship.
        if (package_root / _AGENT_PLUGIN_MANIFEST_FILENAME).exists():
            raise ToolPluginError(
                f"ToolPlugin {self.name!r} package ships a "
                f"{_AGENT_PLUGIN_MANIFEST_FILENAME}: a built-in tool package is not an "
                "Agent Plugins v1.0.0 directory and must never be discoverable as one"
            )

        skill_file = package_root / MANUAL_DIRNAME / SKILL_FILENAME
        try:
            text = skill_file.read_text(encoding="utf-8")
        except OSError as e:
            raise ToolPluginError(
                f"ToolPlugin {self.name!r} cannot read its packaged "
                f"{MANUAL_DIRNAME}/{SKILL_FILENAME}: {e}"
            ) from e
        frontmatter = parse_frontmatter(text)
        if frontmatter.get("name") != self.skill_name:
            raise ToolPluginError(
                f"ToolPlugin {self.name!r} bundled {MANUAL_DIRNAME}/{SKILL_FILENAME} "
                f"declares name {frontmatter.get('name')!r}, expected {self.skill_name!r}"
            )
        if not text.strip():
            raise ToolPluginError(
                f"ToolPlugin {self.name!r} bundled {MANUAL_DIRNAME}/{SKILL_FILENAME} is empty"
            )
        object.__setattr__(self, "_skill_frontmatter", frontmatter)
        object.__setattr__(self, "_skill_text", text)
        object.__setattr__(self, "_skill_path", str(skill_file))

    # -- packaged skill / manual -------------------------------------------

    @property
    def skill_frontmatter(self) -> dict[str, str]:
        """Parsed ``SKILL.md`` frontmatter (the manual's catalog entry)."""
        return dict(self._skill_frontmatter)

    @property
    def skill_text(self) -> str:
        """The packaged ``SKILL.md`` source text, frontmatter included.

        This is the *source* document the host installs, not the ``manual``
        action's answer. ``manual`` deliberately serves the installed per-agent
        copy (see :meth:`manual_child`).
        """
        return self._skill_text

    @property
    def skill_path(self) -> str:
        """Absolute resolved path of the packaged ``SKILL.md`` inside the wheel."""
        return self._skill_path

    def manual_action_description(self) -> str:
        """The schema's ``manual`` catalog line, built from the packaged skill.

        The frontmatter ``name`` + ``description`` are the catalog entry; the
        body stays behind ``action="manual"`` (progressive disclosure). Building
        the line here is what keeps a renamed skill from leaving a stale name
        advertised in the tool schema.

        The description is clipped to :data:`_MAX_MANUAL_DESCRIPTION_LEN` for the
        same reason ``plugin_registry`` bounds a manifest summary: this line ships
        in the always-on tool schema on every turn, and a skill whose frontmatter
        is a multi-paragraph router — as a capability manual's usually is — would
        otherwise spend the whole progressive-disclosure saving it exists to make.
        """
        description = _clip(self._skill_frontmatter.get("description", ""))
        return (
            f"manual: progressive-disclosure usage manual (skill "
            f"'{self.skill_name}') — call this (no other args) to pull the full "
            f"installed {SKILL_FILENAME}. {description}"
        ).strip()

    def manual_child(self, agent: Any) -> ChildTool:
        """The plugin-owned reserved ``manual`` child for this package.

        Bound to :func:`~lingtai.tools.tool_family.manual.build_manual_child` at
        this descriptor's own :attr:`manual_destination`, so the child answers
        from the per-agent installed copy — the host-local ``manual_path`` the
        ManualTool contract requires — while *which* skill that is stays the
        package's declaration rather than a literal repeated at the call site.

        The packaged source and the installed copy cannot diverge in identity:
        the installed copy is a verbatim copy of this package's ``manual/``
        bundle, and construction already proved that bundle carries
        :attr:`skill_name`.
        """
        return build_manual_child(agent, self.manual_destination)

    def schema_only_manual_child(self) -> ChildTool:
        """The reserved ``manual`` child for a family built before an agent exists.

        Same name, title, and strict-empty input as :meth:`manual_child`, with a
        handler that raises if dispatched. A module-level schema-only family and
        the dispatching one therefore declare identical children — the property
        that lets import-time construction prove the registry has no duplicate
        or reserved-name collision.
        """
        return ChildTool(
            MANUAL_ACTION,
            strict_empty_input_schema(),
            _never_dispatched,
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
        schemas[MANUAL_ACTION] = strict_empty_input_schema()
        return schemas

    def build_family(
        self, declared: Sequence[ChildTool], *, agent: Any | None = None
    ) -> ToolFamily:
        """Compose this plugin's one public family, ``manual`` always appended.

        With an ``agent`` the manual child dispatches; with ``None`` the
        schema-only twin is used. Either way the child list — and therefore the
        composed schema — is identical.
        """
        self._check_declared_names([child.name for child in declared])
        manual = self.manual_child(agent) if agent is not None else self.schema_only_manual_child()
        return ToolFamily(self.name, [*declared, manual])

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
                f"{MANUAL_DIRNAME}/{SKILL_FILENAME}"
            )
        if len(set(names)) != len(names):
            raise ToolPluginError(
                f"ToolPlugin {self.name!r} declared a duplicate action"
            )

    # -- shipped capability declaration ------------------------------------

    def capability_declaration(self) -> dict[str, Any]:
        """This package's built-in capability record, in registry shape.

        The same facts ``lingtai.tools.registry`` publishes: the capability
        ``name``, the ``module`` ``setup_capability`` imports, whether it is
        default-on and with which kwargs, and where its manual mounts. Returning
        it here does not register or activate anything — ``BUILTIN_TOOLS`` and
        ``CORE_DEFAULTS`` remain the runtime source the host reads (the registry
        must stay importable without importing every tool), and this descriptor
        is what those entries must agree with.
        """
        declaration: dict[str, Any] = {
            "name": self.name,
            "module": self.package,
            "summary": self.summary,
            "manual_destination": self.manual_destination,
            "default_on": self.default_kwargs is not None,
        }
        if self.default_kwargs is not None:
            declaration["default_kwargs"] = dict(self.default_kwargs)
        return declaration

    def manual_mount(self) -> tuple[str, str]:
        """``(package directory name, installed destination name)``.

        The one fact :func:`declared_manual_destinations` hands the host so the
        install step copies this package's ``manual/`` bundle where the package
        says it belongs.
        """
        return self.package.rpartition(".")[2], self.manual_destination


def _never_dispatched(_input: Mapping[str, Any]) -> dict[str, Any]:
    """Handler for a schema-only child; a dispatched call is a wiring bug."""
    raise AssertionError("the schema-only ToolFamily never dispatches")


# ---------------------------------------------------------------------------
# Discovery — filesystem scan, lazy import, never at registry-import time
# ---------------------------------------------------------------------------

def iter_tool_plugins() -> list[ToolPlugin]:
    """Return every declared tool plugin, in stable package-directory order.

    Scans the ``lingtai.tools`` package directory for ``<pkg>/plugin.py`` and
    imports only those packages. This is a *tools-layer* scan over the kernel's
    own wheel — it is not, and must never be routed through,
    ``services.plugin_registry.read_plugins``, which scans operator-configured
    directories for third-party Agent Plugins.

    Two import rules make the scan safe to call from boot:

    - It is never called at ``lingtai.tools.registry`` import time. The registry
      resolves capability modules lazily inside ``setup_capability`` precisely so
      that importing it does not import every tool, and this must not undo that.
    - A package that declares a descriptor thereby promises its ``__init__`` is
      import-cheap (no ``lingtai`` service imports at module top), because being
      discovered means being imported.

    A package whose descriptor fails to import is logged and skipped: a broken
    descriptor must not take boot down, it must lose its declaration.
    """
    try:
        tools_root = Path(str(resources.files(_TOOLS_PACKAGE)))
    except (ModuleNotFoundError, TypeError):  # pragma: no cover - defensive
        return []

    found: list[ToolPlugin] = []
    for entry in sorted(tools_root.iterdir()):
        if not entry.is_dir() or entry.name.startswith("_"):
            continue
        if not (entry / f"{TOOL_PLUGIN_MODULE}.py").is_file():
            continue
        module_path = f"{_TOOLS_PACKAGE}.{entry.name}.{TOOL_PLUGIN_MODULE}"
        try:
            descriptor = getattr(
                import_module(module_path), TOOL_PLUGIN_ATTRIBUTE, None
            )
        except Exception as e:
            log.warning("tool plugin descriptor %s failed to import: %s", module_path, e)
            continue
        if isinstance(descriptor, ToolPlugin):
            found.append(descriptor)
    return found


def declared_manual_destinations() -> dict[str, str]:
    """Map ``package directory name → installed manual destination``.

    What ``Agent._install_intrinsic_manuals`` consults so a tool plugin's manual
    lands where the *package* declares, instead of where the installer guesses
    from the directory name. Packages without a descriptor are absent, and the
    installer keeps its existing behavior for them.
    """
    return dict(plugin.manual_mount() for plugin in iter_tool_plugins())
