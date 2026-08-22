"""Intrinsic-tool plugin packaging: one package owns its skill, actions, and mount.

A built-in tool is not just a module ``registry.INTRINSICS`` happens to name. It
is a *plugin-style package*: the same folder ships the tool code, the bundled
``manual/SKILL.md`` the agent library installs, and the declaration the host
registry publishes for it. This module is the small shared piece that binds
those three together for one package, so a tool cannot drift into declaring its
module in one place, its manual in another, and a public action list that
silently disagrees with both.

It deliberately is **not** a plugin runtime. Nothing here discovers packages,
imports them by name at scan time, spawns them, activates them, or reads
configuration: registration, boot order, execution policy, permissions, and
namespace decisions all remain the host's. ``lingtai.tools.registry`` still owns
the ``INTRINSICS`` mapping the kernel wires, ``lingtai.agent`` still owns the
``.library/intrinsic/capabilities/`` install, and
``lingtai.services.plugin_registry`` still owns external Agent Plugins v1.0.0
directories. An :class:`IntrinsicToolPlugin` is a declarative descriptor plus
composition helpers that its own package calls explicitly.

Two hard promises it enforces:

*Manual as an owned skill.* The packaged ``manual/SKILL.md`` is loaded and its
frontmatter ``name`` checked at construction, so a package that renames, moves,
or loses its own manual fails loudly at import rather than shipping a tool whose
``manual`` action silently degrades for every agent. The *installed* per-agent
copy stays the runtime source the ``manual`` action reads — this descriptor is
what that copy must have been installed from.

*The reserved ``manual`` action* (``tools/CONTRACT.md`` "Every LingTai-owned
family MUST offer a ``manual`` action"): a package declares only its *own*
actions, and this module appends ``manual`` itself, bound to the package's own
installed skill directory. A package that tries to declare, re-schema, or
re-handle ``manual`` raises :class:`IntrinsicToolPluginError` at import time.
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

from ._manual import installed_manual_path
from .tool_family import RESERVED_MANUAL_NAME, ChildTool, ToolFamily
from .tool_family.manual import MANUAL_INPUT_SCHEMA, build_manual_child

__all__ = [
    "MANUAL_ACTION",
    "PACKAGED_MANUAL_DIRNAME",
    "SKILL_FILENAME",
    "IntrinsicToolPlugin",
    "IntrinsicToolPluginError",
    "manual_input_schema",
]

#: The reserved action name. Owned by ``lingtai.tools.tool_family``; re-exported
#: here so a tool package never spells the literal itself.
MANUAL_ACTION = RESERVED_MANUAL_NAME

#: The package-relative directory ``Agent._install_intrinsic_manuals`` copies
#: into ``.library/intrinsic/capabilities/<mount name>/``. A tool package owns
#: its manual by shipping this directory, not by pointing at a bundle elsewhere.
PACKAGED_MANUAL_DIRNAME = "manual"

#: The skill file inside :data:`PACKAGED_MANUAL_DIRNAME`.
SKILL_FILENAME = "SKILL.md"


class IntrinsicToolPluginError(ValueError):
    """Raised for an intrinsic-tool packaging defect (bad descriptor or shape)."""


def manual_input_schema() -> dict[str, Any]:
    """A fresh copy of the one strict-empty ``manual`` input every family shares.

    The literal is owned by ``tool_family.manual``; this returns a deep copy so
    a family that mutates its composed schema cannot reach into the shared one.
    """
    return copy.deepcopy(MANUAL_INPUT_SCHEMA)


def _schema_only_manual_handler(_input: Mapping[str, Any]) -> dict[str, Any]:
    """Handler for a manual child built without an agent — never dispatches."""
    raise AssertionError(
        "a schema-only manual child never dispatches; build the family with "
        "agent=<the calling agent> to get the dispatching manual child"
    )


@dataclass(frozen=True)
class IntrinsicToolPlugin:
    """One built-in tool package's identity, owned skill, and host declaration.

    ``name`` is the public model-facing tool name, the ``registry.INTRINSICS``
    key, and the ``ToolFamily`` name; ``package`` is the Python package that
    ships both the tool module and the ``manual/SKILL.md`` the agent library
    installs. The two are required to agree (``package`` must end in ``name``)
    because ``Agent._install_intrinsic_manuals`` derives the installed
    capability directory from the *package directory name*: a descriptor whose
    module and public name disagree would advertise a ``manual`` action reading
    some other tool's installed skill.

    ``skill_name`` is the packaged skill's frontmatter ``name`` — the catalog
    identity agents cite ("read ``notification-manual``"), which is deliberately
    independent of the mount directory, exactly as the already-packaged tool
    manuals (``avatar-manual`` → ``capabilities/avatar/``) work today.
    """

    name: str
    package: str
    summary: str
    skill_name: str

    # Loaded from the package's own manual/SKILL.md at construction. Excluded
    # from init/repr/eq: derived material, not declared identity. The body is
    # deliberately *not* retained — the runtime ``manual`` action serves the
    # per-agent installed copy, and holding a second in-memory copy of a
    # document nothing serves would invite reading the wrong one.
    _skill_frontmatter: dict[str, str] = field(init=False, repr=False, compare=False)
    _skill_path: str = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        for attribute in ("name", "package", "summary", "skill_name"):
            value = getattr(self, attribute)
            if not isinstance(value, str) or not value.strip():
                raise IntrinsicToolPluginError(
                    f"IntrinsicToolPlugin {attribute!r} must be a non-empty string"
                )
        if self.package.rpartition(".")[2] != self.name:
            raise IntrinsicToolPluginError(
                f"IntrinsicToolPlugin package {self.package!r} must be the "
                f"{self.name!r} module so its manual mounts under its own name"
            )
        resource = resources.files(self.package).joinpath(
            PACKAGED_MANUAL_DIRNAME, SKILL_FILENAME
        )
        try:
            text = resource.read_text(encoding="utf-8")
        except (FileNotFoundError, OSError) as exc:
            raise IntrinsicToolPluginError(
                f"IntrinsicToolPlugin {self.name!r} does not ship its own "
                f"{PACKAGED_MANUAL_DIRNAME}/{SKILL_FILENAME}: {exc}"
            ) from exc
        frontmatter, body = split_frontmatter(text)
        if frontmatter.get("name") != self.skill_name:
            raise IntrinsicToolPluginError(
                f"IntrinsicToolPlugin {self.name!r} packaged "
                f"{PACKAGED_MANUAL_DIRNAME}/{SKILL_FILENAME} declares name "
                f"{frontmatter.get('name')!r}, expected {self.skill_name!r}"
            )
        if not body.strip():
            raise IntrinsicToolPluginError(
                f"IntrinsicToolPlugin {self.name!r} packaged "
                f"{PACKAGED_MANUAL_DIRNAME}/{SKILL_FILENAME} has an empty body"
            )
        object.__setattr__(self, "_skill_frontmatter", frontmatter)
        object.__setattr__(self, "_skill_path", str(resource))

    # -- packaged skill / installed manual ---------------------------------

    @property
    def skill_frontmatter(self) -> dict[str, str]:
        """Parsed packaged ``SKILL.md`` frontmatter (the skill's catalog entry)."""
        return self._skill_frontmatter

    @property
    def packaged_skill_path(self) -> str:
        """Absolute resolved path of the package's own ``manual/SKILL.md``."""
        return self._skill_path

    def read_packaged_skill(self) -> str:
        """Read the packaged ``SKILL.md`` text — the *install source*.

        Not what ``action='manual'`` returns: that is the per-agent installed
        copy under :meth:`installed_manual_path`, which an agent's library may
        legitimately lack (degraded) without this package being defective.
        """
        return Path(self._skill_path).read_text(encoding="utf-8")

    @property
    def mount_name(self) -> str:
        """The ``.library/intrinsic/capabilities/`` directory this manual mounts at.

        ``Agent._install_intrinsic_manuals`` names the destination after the
        package directory, and ``__post_init__`` pins that directory to
        :attr:`name`, so the mount name is the public tool name.
        """
        return self.name

    def installed_manual_path(self, working_dir: Path) -> Path:
        """The installed ``SKILL.md`` the reserved ``manual`` action reads.

        Delegates to the one shared loader path helper so this descriptor and
        the loader can never disagree about where the manual lives.
        """
        return installed_manual_path(working_dir, self.mount_name)

    # -- family composition -------------------------------------------------

    def manual_child(self, agent: Any | None = None) -> ChildTool:
        """The plugin-owned reserved ``manual`` child.

        With an *agent*, the dispatching child reads that agent's installed
        skill at :meth:`installed_manual_path`, so ``manual`` never routes
        through the tool's own business handlers and cannot be rebound to other
        material. With ``agent=None`` the child carries the identical name,
        title, and strict-empty input but refuses to dispatch — the shape an
        intrinsic needs to compose its module-level schema before any agent
        exists.
        """
        if agent is None:
            return ChildTool(
                MANUAL_ACTION,
                manual_input_schema(),
                _schema_only_manual_handler,
                title=f"{MANUAL_ACTION} input",
            )
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
        schemas[MANUAL_ACTION] = manual_input_schema()
        return schemas

    def build_family(
        self, declared: Sequence[ChildTool], *, agent: Any | None = None
    ) -> ToolFamily:
        """Compose this plugin's one public family, manual always appended."""
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
                f"{PACKAGED_MANUAL_DIRNAME}/{SKILL_FILENAME}"
            )
        if len(set(names)) != len(names):
            raise IntrinsicToolPluginError(
                f"IntrinsicToolPlugin {self.name!r} declared a duplicate action"
            )

    # -- shipped host declarations -----------------------------------------

    def intrinsic_declaration(self) -> dict[str, Any]:
        """This package's mandatory-intrinsic record, in registry record shape.

        The exact ``{"module": <module>}`` value ``registry.INTRINSICS`` maps
        this tool's name to. Returning it here registers and mounts nothing:
        ``lingtai.tools.registry`` remains the runtime source the kernel reads,
        and this descriptor is what that entry must agree with.
        """
        return {"module": importlib.import_module(self.package)}

    def tool_manifest(self, actions: Sequence[str]) -> dict[str, Any]:
        """This package's public tool identity: name, summary, action list.

        The same three-field shape the curated MCP servers advertise on their
        ``lingtai://manifest`` resource, for a tool whose transport is the
        in-process intrinsic protocol rather than stdio.
        """
        return {
            "name": self.name,
            "description": self.summary,
            "actions": list(actions),
        }
