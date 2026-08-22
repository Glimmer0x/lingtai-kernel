"""Local-tool plugin packaging: one package owns its skill, declaration, and family shape.

A built-in capability is not just a module the registry happens to import. It
is a *plugin-style package*: the same folder ships the handler code, the
bundled ``manual/SKILL.md`` the agent library installs and the reserved
``manual`` action serves, and the mount record the built-in registry publishes
for it. This module is the small shared piece that binds those three together
for one package, so a capability cannot drift into declaring its module in one
place, its manual in another, and a public action list that silently disagrees
with both.

It is the model-facing twin of ``lingtai.mcp_servers._plugin`` — the curated-MCP
packaging descriptor Telegram is wired through — with the one difference that
matters at this layer: a curated MCP declares a *launcher* (``python -m
<package>``) into ``mcp_catalog.json``, while a local tool declares a *mount*
(capability name → module, default configuration, installed manual
destination) into ``lingtai.tools.registry``.

It deliberately is **not** a plugin runtime. Nothing here discovers packages,
imports them by name, registers them, boots them, or reads configuration:
activation, capability resolution, karma, lifecycle, and namespace decisions
all remain the host's. ``lingtai.tools.registry`` still owns ``BUILTIN_TOOLS`` /
``CORE_DEFAULTS`` and ``setup_capability``; ``Agent._install_intrinsic_manuals``
still owns the ``.library/intrinsic/capabilities/`` install; and
``lingtai.services.plugin_registry`` still owns external Agent Plugins v1.0.0
directories. A :class:`LocalToolPlugin` is a declarative descriptor plus a few
composition helpers that its own package calls explicitly, and the registry's
literal entries stay the runtime source the host reads — this descriptor is
what those entries must agree with.

Two hard promises are enforced here.

*The packaged skill is the plugin's own.* ``manual/SKILL.md`` is loaded and its
frontmatter ``name`` checked at construction, so a package that renames, empties,
or loses its manual fails loudly at import instead of shipping a capability
whose manual is missing.

*The reserved ``manual`` action is the plugin's, not the package's*
(``tools/CONTRACT.md`` "Every LingTai-owned family MUST offer a ``manual``
action"): a package declares only its *own* actions and this module appends
``manual`` itself, bound to the packaged skill. A package that tries to declare,
re-schema, or re-handle ``manual`` raises :class:`LocalToolPluginError` rather
than shipping a family whose manual is missing or points somewhere other than
its packaged bundle.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from types import MappingProxyType
from typing import Any

from lingtai.kernel._frontmatter import split_frontmatter

from .tool_family import RESERVED_MANUAL_NAME, ChildTool, ToolFamily
from .tool_family.manual import (
    MANUAL_CHILD_TITLE,
    MANUAL_INPUT_SCHEMA,
    build_manual_child,
    to_manual_result,
)

__all__ = [
    "INTRINSIC_SOURCE",
    "MANUAL_ACTION",
    "MANUAL_BUNDLE_DIRNAME",
    "SKILL_FILENAME",
    "LocalToolPlugin",
    "LocalToolPluginError",
    "strict_empty_input_schema",
]

#: ``source`` stamped on every mount record this module emits — the value that
#: tells a kernel-shipped built-in capability apart from a ``plugin:<name>``
#: Agent-Plugins-sourced or hand-registered one.
INTRINSIC_SOURCE = "lingtai-intrinsic"

#: The reserved action name. Owned by ``lingtai.tools.tool_family``; re-exported
#: here so a plugin package never spells the literal itself.
MANUAL_ACTION = RESERVED_MANUAL_NAME

#: The per-package manual bundle directory ``Agent._install_intrinsic_manuals``
#: copies into ``.library/intrinsic/capabilities/<manual_skill>/``.
MANUAL_BUNDLE_DIRNAME = "manual"

#: The bundle's main document, both in the package and once installed.
SKILL_FILENAME = "SKILL.md"


class LocalToolPluginError(ValueError):
    """Raised for a local-tool packaging defect (bad descriptor or shape)."""


def strict_empty_input_schema() -> dict[str, Any]:
    """The canonical closed, argument-free ``input`` schema for an action.

    This is ``tool_family.manual.MANUAL_INPUT_SCHEMA``'s exact spelling —
    including its explicit ``required: []`` — copied per call so one family's
    child can never mutate another's. Families already compare composed
    schemas byte-for-byte, so the reserved action must reuse the one owned
    definition rather than re-spelling an equivalent literal.
    """
    return {
        "type": dict(MANUAL_INPUT_SCHEMA)["type"],
        "properties": {},
        "required": list(MANUAL_INPUT_SCHEMA["required"]),
        "additionalProperties": MANUAL_INPUT_SCHEMA["additionalProperties"],
    }


@dataclass(frozen=True)
class LocalToolPlugin:
    """One local tool package's identity, packaged skill, and mount record.

    ``name`` is the public capability name, the model-facing family root, and
    the key ``registry.BUILTIN_TOOLS`` / ``CORE_DEFAULTS`` publish. ``package``
    is the Python package that ships both the handler module and the
    ``manual/SKILL.md`` bundle behind the ``manual`` action.

    The two are required to agree (``package`` must end in ``module_name``,
    which defaults to ``name``) because :meth:`tool_declaration` publishes
    ``package`` as this capability's mount target — a descriptor whose module
    and capability name disagree would advertise a mount for something else.
    ``module_name`` exists for the retained-implementation packages whose folder
    is deliberately not their public name (``bash`` → ``shell``, ``web_search``
    → ``web``); ``task_card``, the one package wired through this module today,
    leaves it at the default.

    ``manual_skill`` is the destination directory name under
    ``.library/intrinsic/capabilities/`` that ``Agent._install_intrinsic_manuals``
    copies this package's ``manual/`` bundle into, and therefore the name the
    reserved ``manual`` action reads back at runtime. ``skill_name`` is the
    frontmatter ``name`` of the packaged document; the two differ freely (the
    installed *directory* is the capability, the frontmatter is the skill's own
    catalog identity) and both are pinned so neither can drift silently.
    """

    name: str
    package: str
    summary: str
    manual_skill: str
    skill_name: str
    module_name: str | None = None
    #: The ``CORE_DEFAULTS`` kwargs this capability boots with, or ``None`` for
    #: a capability that is registrable but not part of the always-on floor.
    default_configuration: Mapping[str, Any] | None = None

    # Loaded from the package's bundled manual/SKILL.md at construction.
    # Excluded from init/repr/eq: derived material, not declared identity.
    _skill_frontmatter: Mapping[str, str] = field(init=False, repr=False, compare=False)
    _skill_body: str = field(init=False, repr=False, compare=False)
    _skill_path: str = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        for attribute in ("name", "package", "summary", "manual_skill", "skill_name"):
            value = getattr(self, attribute)
            if not isinstance(value, str) or not value.strip():
                raise LocalToolPluginError(
                    f"LocalToolPlugin {attribute!r} must be a non-empty string"
                )
        if self.module_name is not None and (
            not isinstance(self.module_name, str) or not self.module_name.strip()
        ):
            raise LocalToolPluginError(
                "LocalToolPlugin 'module_name' must be a non-empty string or None"
            )
        expected_module = self.module_name or self.name
        if self.package.rpartition(".")[2] != expected_module:
            raise LocalToolPluginError(
                f"LocalToolPlugin package {self.package!r} must be the "
                f"{expected_module!r} module so its declared mount is its own module"
            )
        if self.default_configuration is not None and not isinstance(
            self.default_configuration, Mapping
        ):
            raise LocalToolPluginError(
                "LocalToolPlugin 'default_configuration' must be a mapping or None"
            )

        frontmatter, body, path = self._load_packaged_skill()
        if frontmatter.get("name") != self.skill_name:
            raise LocalToolPluginError(
                f"LocalToolPlugin {self.name!r} bundled "
                f"{MANUAL_BUNDLE_DIRNAME}/{SKILL_FILENAME} declares name "
                f"{frontmatter.get('name')!r}, expected {self.skill_name!r}"
            )
        if not body.strip():
            raise LocalToolPluginError(
                f"LocalToolPlugin {self.name!r} bundled "
                f"{MANUAL_BUNDLE_DIRNAME}/{SKILL_FILENAME} has an empty body"
            )
        object.__setattr__(self, "_skill_frontmatter", MappingProxyType(dict(frontmatter)))
        object.__setattr__(self, "_skill_body", body)
        object.__setattr__(self, "_skill_path", path)

    def _load_packaged_skill(self) -> tuple[dict[str, str], str, str]:
        resource = resources.files(self.package).joinpath(
            MANUAL_BUNDLE_DIRNAME, SKILL_FILENAME
        )
        try:
            text = resource.read_text(encoding="utf-8")
        except (FileNotFoundError, OSError) as exc:
            raise LocalToolPluginError(
                f"LocalToolPlugin {self.name!r} has no packaged "
                f"{MANUAL_BUNDLE_DIRNAME}/{SKILL_FILENAME} in {self.package!r}: {exc}"
            ) from exc
        frontmatter, body = split_frontmatter(text)
        return frontmatter, body, str(resource)

    # -- packaged skill / manual -------------------------------------------

    @property
    def skill_frontmatter(self) -> Mapping[str, str]:
        """Parsed packaged ``SKILL.md`` frontmatter (the manual's catalog entry)."""
        return self._skill_frontmatter

    @property
    def skill_body(self) -> str:
        """The full packaged ``SKILL.md`` markdown body behind ``action='manual'``."""
        return self._skill_body

    @property
    def skill_path(self) -> str:
        """Absolute resolved path of the packaged ``manual/SKILL.md``."""
        return self._skill_path

    def manual_bundle_path(self) -> str:
        """The packaged ``manual/`` directory the agent library installs from.

        This is the source side of the install contract: whatever
        ``Agent._install_intrinsic_manuals`` copies to
        :meth:`installed_manual_path` comes from here.
        """
        return str(resources.files(self.package).joinpath(MANUAL_BUNDLE_DIRNAME))

    def installed_manual_path(self, working_dir: Any) -> Path:
        """Where this plugin's manual lands in one agent's intrinsic library.

        The destination side of the install contract, and the exact path the
        reserved ``manual`` child reads. Owning both ends here is what keeps
        the installed capability directory name from drifting away from the
        name the action looks up.
        """
        return (
            Path(working_dir)
            / ".library"
            / "intrinsic"
            / "capabilities"
            / self.manual_skill
            / SKILL_FILENAME
        )

    def manual_action_description(self) -> str:
        """The schema's ``manual`` catalog line, built from the packaged skill."""
        name = self._skill_frontmatter.get("name", self.skill_name)
        description = " ".join(
            str(self._skill_frontmatter.get("description", "")).split()
        )
        return (
            f"manual: progressive-disclosure usage manual (skill '{name}') — "
            "call this (no other args) to pull the full bundled SKILL.md. "
            f"{description}"
        ).strip()

    def packaged_manual_result(self) -> dict[str, Any]:
        """The ``action='manual'`` result served straight from the package."""
        return to_manual_result(
            {
                "status": "ok",
                "manual": self._skill_body,
                "manual_path": self._skill_path,
            }
        )

    def manual_child(self, agent: Any) -> ChildTool:
        """The plugin-owned reserved ``manual`` child.

        Resolution order is installed-then-packaged, and both ends belong to
        this descriptor. The agent-local copy under
        :meth:`installed_manual_path` wins because it is the *installed
        projection of this same bundle* and a host may legitimately curate it.
        When that copy is absent — a failed initializer, a capability read
        about before it was installed — the child falls back to the packaged
        document instead of returning the pre-plugin empty/degraded manual: a
        plugin owns its skill, so its manual is always answerable.

        The child never routes through the package's business manager, so no
        manager change can drop or rebind it.
        """
        installed = build_manual_child(agent, self.manual_skill) if agent is not None else None
        packaged = self.packaged_manual_result()

        def handler(input_: Mapping[str, Any]) -> dict[str, Any]:
            if installed is not None:
                result = installed.handler(input_)
                if result.get("status") == "ok":
                    return result
            return dict(packaged)

        return ChildTool(
            name=MANUAL_ACTION,
            input_schema=strict_empty_input_schema(),
            handler=handler,
            title=MANUAL_CHILD_TITLE,
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
        self, declared: Sequence[ChildTool], *, agent: Any = None
    ) -> ToolFamily:
        """Compose this plugin's one public family, ``manual`` always appended.

        ``agent`` is the live agent whose installed library the manual child
        reads. A schema-only composition (no agent yet) still gets a real
        ``manual`` child: it answers from the packaged skill, so the composed
        schema is identical either way.
        """
        self._check_declared_names([child.name for child in declared])
        return ToolFamily(self.name, [*declared, self.manual_child(agent)])

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
                f"{MANUAL_BUNDLE_DIRNAME}/{SKILL_FILENAME}"
            )
        if len(set(names)) != len(names):
            raise LocalToolPluginError(
                f"LocalToolPlugin {self.name!r} declared a duplicate action"
            )

    # -- shipped mount declaration ------------------------------------------

    def tool_declaration(self) -> dict[str, Any]:
        """This package's built-in mount record, in registry record shape.

        The same facts ``lingtai.tools.registry`` publishes for one capability
        — the ``BUILTIN_TOOLS`` module target, the ``CORE_DEFAULTS`` kwargs (or
        ``None`` for an opt-in capability), and the installed-manual
        destination ``Agent._install_intrinsic_manuals`` writes. Returning it
        here does not register, boot, or activate anything: the registry's own
        entries remain the runtime source the host reads, and this descriptor
        is what those entries must agree with.
        """
        return {
            "name": self.name,
            "module": self.package,
            "summary": self.summary,
            "source": INTRINSIC_SOURCE,
            "manual_skill": self.manual_skill,
            "default_configuration": (
                None
                if self.default_configuration is None
                else dict(self.default_configuration)
            ),
        }
