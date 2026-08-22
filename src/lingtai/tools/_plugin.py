"""Built-in tool plugin packaging: one package owns its skill, declaration, and family shape.

A built-in tool is not just a module the capability registry happens to import.
It is a *plugin-style package*: the same folder ships the tool code, the bundled
``manual/SKILL.md`` the agent library installs, and the capability declaration
``lingtai.tools.registry`` publishes for it. This module is the small shared
piece that binds those three together for one package, so a built-in tool cannot
drift into declaring its module in one place, its manual in another, and a
public action list that silently disagrees with both.

It is the in-process twin of ``lingtai.mcp_servers._plugin`` (the curated-MCP
packaging descriptor, reference slice ``mcp_servers/telegram/plugin.py``), and
it makes the same deliberate omission: it is **not** a plugin runtime. Nothing
here discovers packages, imports them by name, spawns them, registers them, or
reads configuration. Activation, execution policy, privilege, lifecycle, and
namespace decisions all remain the host's: ``lingtai.tools.registry`` still owns
``BUILTIN_TOOLS``/``CORE_DEFAULTS`` and ``setup_capability()``, ``BaseAgent``
still owns ``add_tool()`` and boot order, ``Agent._install_intrinsic_manuals``
still owns the ``.library`` install, and ``lingtai.services.plugin_registry``
still owns external Agent Plugins v1.0.0 directories (an unrelated, third-party
surface — do not confuse ``lingtai.tools._plugin`` with ``lingtai.tools.plugin``,
which is the read-only *catalog tool* for those external plugins). A
:class:`BuiltinToolPlugin` is a declarative descriptor plus composition helpers
that its own package calls explicitly.

The one hard promise it enforces is the reserved ``manual`` action
(``tools/CONTRACT.md`` "Every LingTai-owned family MUST offer a ``manual``
action"): a package declares only its *own* actions, and this module appends
``manual`` itself, answered — like every other LingTai family's ``manual`` —
from the host-local copy the host installed for *this* agent, through the one
shared :func:`lingtai.tools._manual.load_installed_manual`. The packaged
``manual/SKILL.md`` is that copy's source, not the document the agent reads,
so it is what :meth:`BuiltinToolPlugin.validate_packaged_skill` checks and
what the host installs — never what the action reports. A package that tries
to declare, re-schema, or re-handle ``manual`` raises
:class:`BuiltinToolPluginError` at import time rather than shipping a family
whose manual is missing or points somewhere other than its own skill.

Deliberate divergence from the curated-MCP twin: that descriptor loads and
validates its ``SKILL.md`` eagerly at construction and raises on a missing or
foreign manual. A curated MCP that fails that way loses one subprocess. A
built-in tool is imported in-process by an agent that may boot it as a core
default, so an unreadable packaged file must never take agent boot down —
:meth:`BuiltinToolPlugin.load_manual` therefore reads the packaged skill on
demand and *degrades truthfully* (``status="degraded"`` plus a naming
``error``, never a foreign body), while
:meth:`BuiltinToolPlugin.validate_packaged_skill` raises the same defect
loudly for packaging tests and doctor-style checks. Descriptor-shape defects,
which need no filesystem, still fail at import.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from importlib import resources
from typing import Any, Callable

from lingtai.kernel._frontmatter import split_frontmatter

from ._manual import load_installed_manual
from .tool_family import RESERVED_MANUAL_NAME, ChildTool, ToolFamily
from .tool_family.manual import MANUAL_INPUT_SCHEMA

__all__ = [
    "BUILTIN_SOURCE",
    "INSTALLED_MANUAL_ROOT",
    "MANUAL_ACTION",
    "MANUAL_RESOURCE",
    "BuiltinToolPlugin",
    "BuiltinToolPluginError",
]

#: ``source`` stamped on every built-in capability declaration — the value that
#: tells a kernel-shipped built-in tool apart from an external
#: ``plugin:<name>``-sourced or hand-registered capability.
BUILTIN_SOURCE = "lingtai-builtin"

#: The reserved action name. Owned by ``lingtai.tools.tool_family``; re-exported
#: here so a built-in package never spells the literal itself.
MANUAL_ACTION = RESERVED_MANUAL_NAME

#: The packaged manual resource every built-in tool ships, relative to its own
#: package root. ``Agent._install_intrinsic_manuals`` copies this ``manual/``
#: directory verbatim into :data:`INSTALLED_MANUAL_ROOT`; the packaged original
#: is the source of truth for that installed copy, and the ``manual`` action
#: serves the installed copy — the document the agent itself can read.
MANUAL_RESOURCE = "manual/SKILL.md"

#: Where the host installs that packaged manual inside an agent working dir.
#: Stated by the descriptor and *performed* by the host — this module writes
#: nothing.
INSTALLED_MANUAL_ROOT = ".library/intrinsic/capabilities"


class BuiltinToolPluginError(ValueError):
    """Raised for a built-in tool packaging defect (bad descriptor or skill)."""


@dataclass(frozen=True)
class BuiltinToolPlugin:
    """One built-in tool package's identity, packaged skill, and capability declaration.

    ``name`` is the public capability name, the model-facing tool name, and the
    ``.library`` install destination; ``package`` is the Python package that
    ships both the tool module and the ``manual/SKILL.md`` the ``manual`` action
    returns. The two are required to agree (``package`` must end in ``name``,
    or in ``module_name`` for a retained implementation directory whose public
    name differs, as ``bash``→``shell`` and ``web_search``→``web`` do) because
    :meth:`capability_declaration` publishes ``package`` as this capability's
    import path — a descriptor whose module and capability name disagree would
    advertise somebody else's implementation.

    ``default_kwargs`` is the always-on boot configuration the host's
    ``CORE_DEFAULTS`` carries for this capability, or ``{}`` for an opt-in one.
    Stating it here does not enable anything: the registry mapping remains the
    runtime source the host reads, and this descriptor is what that entry must
    agree with (proven by test, not by generating the registry at runtime).
    """

    name: str
    package: str
    summary: str
    skill_name: str
    module_name: str = ""
    default_kwargs: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for attribute in ("name", "package", "summary", "skill_name"):
            value = getattr(self, attribute)
            if not isinstance(value, str) or not value.strip():
                raise BuiltinToolPluginError(
                    f"BuiltinToolPlugin {attribute!r} must be a non-empty string"
                )
        if not isinstance(self.module_name, str):
            raise BuiltinToolPluginError(
                "BuiltinToolPlugin 'module_name' must be a string"
            )
        if not isinstance(self.default_kwargs, Mapping):
            raise BuiltinToolPluginError(
                "BuiltinToolPlugin 'default_kwargs' must be a mapping"
            )
        if not self.package.startswith("lingtai.tools."):
            raise BuiltinToolPluginError(
                f"BuiltinToolPlugin package {self.package!r} must live under "
                "'lingtai.tools.' — this descriptor packages a built-in tool, "
                "not an external Agent Plugin"
            )
        if self.package.rpartition(".")[2] != self.module:
            raise BuiltinToolPluginError(
                f"BuiltinToolPlugin package {self.package!r} must be the "
                f"{self.module!r} module so its declared capability imports its "
                "own implementation"
            )

    @property
    def module(self) -> str:
        """The implementation directory name (``module_name`` or ``name``)."""
        return self.module_name or self.name

    # -- packaged skill / manual -------------------------------------------

    def manual_resource(self) -> Any:
        """The packaged ``manual/SKILL.md`` traversable, unread."""
        return resources.files(self.package).joinpath(MANUAL_RESOURCE)

    def load_manual(self) -> dict[str, Any]:
        """Read and validate the *packaged* skill → the flat loader result shape.

        The packaging-side read: the source ``Agent._install_intrinsic_manuals``
        copies from, not the host-local document the ``manual`` action serves
        (:meth:`manual_payload`). Returns ``{status, manual, manual_path}`` —
        the same three keys ``lingtai.tools._manual.load_installed_manual``
        returns — plus ``error`` when degraded. ``manual`` is the *whole*
        ``SKILL.md`` text, frontmatter included, because that is the document
        the skill catalog and the model both read.

        Read on demand rather than cached at construction: a built-in tool is
        imported in-process during agent boot, and a packaging fault must
        degrade this one action rather than fail the import. A manual that is
        present but is not this plugin's declared skill is refused, not served:
        the body comes back empty with an ``error`` naming the mismatch.
        """
        resource = self.manual_resource()
        try:
            text = resource.read_text(encoding="utf-8")
        except (FileNotFoundError, ModuleNotFoundError, AttributeError, OSError):
            return self._degraded(str(resource), f"{self.name} manual missing")

        path = str(resource)
        frontmatter, body = split_frontmatter(text)
        declared = frontmatter.get("name", "")
        if declared != self.skill_name:
            return self._degraded(
                path,
                f"{self.name} manual declares skill {declared!r}, expected "
                f"{self.skill_name!r}",
            )
        if not body.strip():
            return self._degraded(path, f"{self.name} manual has an empty body")
        return {"status": "ok", "manual": text, "manual_path": path}

    @staticmethod
    def _degraded(path: str, error: str) -> dict[str, Any]:
        return {"status": "degraded", "manual": "", "manual_path": path, "error": error}

    def manual_payload(self, agent: Any) -> dict[str, Any]:
        """The ``action='manual'`` result: this agent's installed skill, named by its action.

        *agent* is the host this capability is mounted on. The manual reported
        is the host-local copy at :meth:`installed_manual_path` inside that
        agent's working dir — the document the agent can actually open, and the
        one every other LingTai family's ``manual`` reports via the shared
        ``load_installed_manual``. Reporting the packaged source path instead
        would hand the model a path outside its own working dir, and one that
        does not exist at all in an installed distribution.

        A missing installed copy degrades truthfully (the loader's own
        ``status``/``error``); it is never silently backfilled from the
        packaged source, because that would hide a failed install.
        """
        loaded = load_installed_manual(agent, self.name)
        payload: dict[str, Any] = {
            "status": loaded["status"],
            "action": MANUAL_ACTION,
            "manual": loaded["manual"],
            "manual_path": loaded["manual_path"],
        }
        if "error" in loaded:
            payload["error"] = loaded["error"]
        return payload

    def manual_child(self, agent: Any) -> ChildTool:
        """The plugin-owned reserved ``manual`` child, bound to one host.

        Its handler closes over this descriptor and *agent*, so ``manual``
        never routes through the package's manager and cannot be rebound to
        other material by anything the manager does. *agent* may be ``None``
        for a module-level schema-only family that never dispatches, matching
        ``tool_family.manual.build_manual_child``'s own contract.
        """
        return ChildTool(
            MANUAL_ACTION,
            MANUAL_INPUT_SCHEMA,
            lambda _input: self.manual_payload(agent),
            title=f"{MANUAL_ACTION} input",
        )

    def validate_packaged_skill(self) -> None:
        """Raise if the packaged manual is missing, empty, or a foreign skill.

        The loud form of :meth:`load_manual`'s degraded result, for packaging
        tests and doctor-style checks that want a packaging defect to fail
        rather than be reported at runtime.
        """
        loaded = self.load_manual()
        if loaded["status"] != "ok":
            raise BuiltinToolPluginError(
                f"BuiltinToolPlugin {self.name!r}: {loaded.get('error', 'unusable manual')}"
            )

    def installed_manual_path(self) -> str:
        """Agent-relative path the host installs this packaged skill to.

        ``Agent._install_intrinsic_manuals`` copies ``<package>/manual/`` into
        ``.library/intrinsic/capabilities/<name>/`` on every boot, keyed by the
        *public* name — which is why a retained implementation directory must
        declare ``module_name`` instead of renaming this destination. This is
        the manual the ``manual`` action reads and reports.
        """
        return f"{INSTALLED_MANUAL_ROOT}/{self.name}/SKILL.md"

    # -- family composition -------------------------------------------------

    def actions(self, declared: Sequence[str]) -> tuple[str, ...]:
        """Declared actions plus the reserved ``manual``, in that order."""
        self._check_declared_names(declared)
        return tuple(declared) + (MANUAL_ACTION,)

    def child_specs(
        self, declared: Sequence[tuple[str, dict[str, Any]]]
    ) -> tuple[tuple[str, dict[str, Any]], ...]:
        """Declared ``(action, input schema)`` specs plus the reserved ``manual``.

        The appended ``manual`` spec is the one shared
        :data:`~lingtai.tools.tool_family.manual.MANUAL_INPUT_SCHEMA` object, not
        a copy, so a family that declares this schema and the child that
        dispatches it cannot drift apart.
        """
        self._check_declared_names([name for name, _schema in declared])
        return tuple(declared) + ((MANUAL_ACTION, MANUAL_INPUT_SCHEMA),)

    def build_family(self, declared: Sequence[ChildTool], agent: Any) -> ToolFamily:
        """Compose this plugin's one public family, ``manual`` always appended.

        *agent* is the host whose installed manual the appended child serves;
        it may be ``None`` for a schema-only family that never dispatches.
        """
        self._check_declared_names([child.name for child in declared])
        return ToolFamily(self.name, [*declared, self.manual_child(agent)])

    def _check_declared_names(self, declared: Sequence[str] | Any) -> None:
        names = list(declared)
        if not names:
            raise BuiltinToolPluginError(
                f"BuiltinToolPlugin {self.name!r} must declare at least one action"
            )
        if MANUAL_ACTION in names:
            raise BuiltinToolPluginError(
                f"BuiltinToolPlugin {self.name!r} must not declare the reserved "
                f"{MANUAL_ACTION!r} action; it is appended from the packaged "
                f"{MANUAL_RESOURCE}"
            )
        if len(set(names)) != len(names):
            raise BuiltinToolPluginError(
                f"BuiltinToolPlugin {self.name!r} declared a duplicate action"
            )

    # -- shipped capability declaration / mount -----------------------------

    def capability_declaration(self) -> dict[str, Any]:
        """This package's built-in capability record, in registry-entry shape.

        The same facts ``lingtai.tools.registry`` publishes: the capability name
        (``BUILTIN_TOOLS`` key), the module it imports (``BUILTIN_TOOLS`` value),
        and the always-on boot kwargs (``CORE_DEFAULTS`` value, ``{}`` when the
        capability is opt-in). Returning it here registers and activates
        nothing: the registry mapping remains the runtime source the host reads
        and lazily imports, and this descriptor is what that entry must agree
        with.
        """
        return {
            "name": self.name,
            "module": self.package,
            "default_kwargs": dict(self.default_kwargs),
            "source": BUILTIN_SOURCE,
            "summary": self.summary,
            "manual_skill": self.skill_name,
            "installed_manual_path": self.installed_manual_path(),
        }

    def tool_registration(
        self,
        *,
        schema: Mapping[str, Any],
        description: str,
        handler: Callable[..., Any],
    ) -> dict[str, Any]:
        """The ``BaseAgent.add_tool`` keyword arguments for this plugin's one tool.

        Composition only — the package's own ``setup()`` still performs the
        call, so tool registration stays exactly where the host's capability
        boot put it. What is registered (public name, glossary package) comes
        from the descriptor instead of being restated at the call site.
        """
        return {
            "schema": dict(schema),
            "handler": handler,
            "description": description,
            "glossary_package": self.package,
        }
