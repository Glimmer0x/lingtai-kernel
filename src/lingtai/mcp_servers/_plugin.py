"""Curated MCP plugin packaging: one package owns its skill, declaration, and family shape.

A curated MCP is not just a module the catalog happens to launch. It is a
*plugin-style package*: the same folder ships the server code, the bundled
``SKILL.md`` manual, and the stdio MCP declaration that the curated catalog
publishes for it. This module is the small shared piece that binds those three
together for one package, so a curated MCP cannot drift into declaring its
launcher in one place, its manual in another, and a public action list that
silently disagrees with both.

It deliberately is **not** a plugin runtime. Nothing here discovers packages,
imports them by name, spawns them, registers them, or reads configuration:
activation, execution policy, audit, lifecycle, and namespace/collision
decisions all remain the host's. ``lingtai.services.mcp_registry`` still owns
catalog loading and registry decompression, and ``lingtai.services.plugin_registry``
still owns external Agent Plugins v1.0.0 directories. A
:class:`CuratedMcpPlugin` is a declarative descriptor plus three composition
helpers that its own package calls explicitly.

The one hard promise it enforces is the reserved ``manual`` action
(``tools/CONTRACT.md`` "Every LingTai-owned family MUST offer a ``manual``
action"): a package declares only its *own* actions, and this module appends
``manual`` itself, sourced from the package's bundled ``SKILL.md``. A package
that tries to declare, re-schema, or re-handle ``manual`` raises
:class:`CuratedMcpPluginError` at import time rather than shipping a family
whose manual is missing or points somewhere other than its packaged skill.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from lingtai.kernel.tool_plugin.settings import (
    SettingOwner,
    ToolSettingsContract,
    settings_input_schema,
)
from lingtai.tools.tool_family import (
    RESERVED_MANUAL_NAME,
    RESERVED_SETTINGS_NAME,
    ChildTool,
    ToolFamily,
)

from . import _skill

__all__ = [
    "CURATED_SOURCE",
    "MANUAL_ACTION",
    "PYTHON_PLACEHOLDER",
    "CuratedMcpPlugin",
    "CuratedMcpPluginError",
    "strict_empty_input_schema",
]

#: ``source`` stamped on every curated catalog record — the value
#: ``mcp_registry``/``plugin_registry`` use to tell a kernel-shipped curated MCP
#: apart from a ``plugin:<name>``-sourced or hand-registered one.
CURATED_SOURCE = "lingtai-curated"

#: The reserved action name. Owned by ``lingtai.tools.tool_family``; re-exported
#: here so a curated package never spells the literal itself.
MANUAL_ACTION = RESERVED_MANUAL_NAME

#: Catalog placeholder that ``mcp_registry.decompress_addons`` substitutes with
#: the running interpreter when it materializes a record into the registry.
PYTHON_PLACEHOLDER = "{python}"


class CuratedMcpPluginError(ValueError):
    """Raised for a curated-MCP packaging defect (bad descriptor or shape)."""


def strict_empty_input_schema() -> dict[str, Any]:
    """The canonical closed, argument-free ``input`` schema for an action."""
    return {"type": "object", "properties": {}, "additionalProperties": False}


@dataclass(frozen=True)
class CuratedMcpPlugin:
    """One curated MCP package's identity, packaged skill, and MCP declaration.

    ``name`` is the registry/catalog name and the public family name;
    ``package`` is the Python package that ships both the server module and the
    ``SKILL.md`` the ``manual`` action returns. The two are required to agree
    (``package`` must end in ``name``) because :meth:`mcp_declaration` publishes
    ``python -m <package>`` as this plugin's launcher — a descriptor whose
    module and registry name disagree would advertise a launcher for something
    else.

    The bundled skill is loaded once at construction and its frontmatter
    ``name`` is checked against ``skill_name``, so a package that renames or
    loses its manual fails loudly at import instead of serving an empty or
    foreign ``manual``.
    """

    name: str
    package: str
    server_name: str
    summary: str
    homepage: str
    skill_name: str
    settings: ToolSettingsContract | None = None

    # Loaded from the package's bundled SKILL.md at construction. Excluded from
    # init/repr/eq: they are derived material, not part of the descriptor's
    # declared identity.
    _skill_frontmatter: dict[str, str] = field(init=False, repr=False, compare=False)
    _skill_body: str = field(init=False, repr=False, compare=False)
    _skill_path: str = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        for attribute in (
            "name", "package", "server_name", "summary", "homepage", "skill_name",
        ):
            value = getattr(self, attribute)
            if not isinstance(value, str) or not value.strip():
                raise CuratedMcpPluginError(
                    f"CuratedMcpPlugin {attribute!r} must be a non-empty string"
                )
        if self.package.rpartition(".")[2] != self.name:
            raise CuratedMcpPluginError(
                f"CuratedMcpPlugin package {self.package!r} must be the "
                f"{self.name!r} module so its declared launcher is its own module"
            )
        if self.settings is not None and not isinstance(self.settings, ToolSettingsContract):
            raise CuratedMcpPluginError(
                f"CuratedMcpPlugin {self.name!r} has invalid settings"
            )
        frontmatter, body, path = _skill.load_skill(self.package)
        if frontmatter.get("name") != self.skill_name:
            raise CuratedMcpPluginError(
                f"CuratedMcpPlugin {self.name!r} bundled {_skill.SKILL_FILENAME} "
                f"declares name {frontmatter.get('name')!r}, expected {self.skill_name!r}"
            )
        if not body.strip():
            raise CuratedMcpPluginError(
                f"CuratedMcpPlugin {self.name!r} bundled {_skill.SKILL_FILENAME} has an empty body"
            )
        object.__setattr__(self, "_skill_frontmatter", frontmatter)
        object.__setattr__(self, "_skill_body", body)
        object.__setattr__(self, "_skill_path", path)

    # -- packaged skill / manual ------------------------------------------

    @property
    def skill_frontmatter(self) -> dict[str, str]:
        """Parsed ``SKILL.md`` frontmatter (the manual's catalog entry)."""
        return self._skill_frontmatter

    @property
    def skill_body(self) -> str:
        """The full ``SKILL.md`` markdown body behind ``action='manual'``."""
        return self._skill_body

    @property
    def skill_path(self) -> str:
        """Absolute resolved path of the packaged ``SKILL.md``."""
        return self._skill_path

    def manual_action_description(self) -> str:
        """The schema's ``manual`` catalog line, built from the packaged skill."""
        return _skill.manual_action_description(self._skill_frontmatter, self.skill_name)

    def manual_payload(self) -> dict[str, Any]:
        """The ``action='manual'`` result: packaged skill body, metadata, path."""
        return _skill.manual_payload(
            self._skill_frontmatter, self._skill_body, self._skill_path, self.skill_name
        )

    def manual_child(self) -> ChildTool:
        """The plugin-owned reserved ``manual`` child.

        Its handler closes over this descriptor's packaged skill, so ``manual``
        never routes through the package's business manager and cannot be
        rebound to other material.
        """
        return ChildTool(
            MANUAL_ACTION,
            strict_empty_input_schema(),
            lambda _input: self.manual_payload(),
        )

    # -- family composition -------------------------------------------------

    def actions(self, declared: Sequence[str]) -> tuple[str, ...]:
        """Declared actions, optional ``settings``, then reserved ``manual``."""
        self._check_declared_names(declared)
        settings = (RESERVED_SETTINGS_NAME,) if self.settings is not None else ()
        return (*declared, *settings, MANUAL_ACTION)

    def action_input_schemas(
        self, declared: Mapping[str, Mapping[str, Any]]
    ) -> dict[str, dict[str, Any]]:
        """Declared schemas, optional ``settings``, then reserved ``manual``."""
        self._check_declared_names(declared.keys())
        schemas: dict[str, dict[str, Any]] = {
            action: dict(schema) for action, schema in declared.items()
        }
        if self.settings is not None:
            schemas[RESERVED_SETTINGS_NAME] = settings_input_schema()
        schemas[MANUAL_ACTION] = strict_empty_input_schema()
        return schemas

    def build_family(self, declared: Sequence[ChildTool], *,
                     settings_owner: SettingOwner | None = None) -> ToolFamily:
        """Compose one family with opted-in settings immediately before manual."""
        self._check_declared_names([child.name for child in declared])
        return ToolFamily(
            self.name, [*declared, self.manual_child()],
            settings_contract=self.settings, settings_owner=settings_owner,
        )

    def _check_declared_names(self, declared: "Sequence[str] | Any") -> None:
        names = list(declared)
        if not names and self.settings is None:
            raise CuratedMcpPluginError(
                f"CuratedMcpPlugin {self.name!r} must declare an action unless settings is enabled"
            )
        reserved = [name for name in (RESERVED_SETTINGS_NAME, MANUAL_ACTION) if name in names]
        if reserved:
            raise CuratedMcpPluginError(
                f"CuratedMcpPlugin {self.name!r} must not declare the reserved "
                f"{reserved[0]!r} action; reserved actions are composed generically"
            )
        if len(set(names)) != len(names):
            raise CuratedMcpPluginError(
                f"CuratedMcpPlugin {self.name!r} declared a duplicate action"
            )

    # -- shipped MCP declaration -------------------------------------------

    def mcp_declaration(self) -> dict[str, Any]:
        """This package's curated stdio MCP record, in catalog record shape.

        The same fields ``lingtai/mcp_catalog.json`` publishes and
        ``mcp_registry.validate_record`` accepts. Returning it here does not
        register or activate anything: the shipped catalog file remains the
        runtime source the host reads, and this descriptor is what that entry
        must agree with.
        """
        return {
            "name": self.name,
            "summary": self.summary,
            "transport": "stdio",
            "command": PYTHON_PLACEHOLDER,
            "args": ["-m", self.package],
            "source": CURATED_SOURCE,
            "homepage": self.homepage,
        }
