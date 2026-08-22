"""Package-local model-facing descriptor for the canonical ``system`` root.

The Host still owns mandatory-intrinsic registration, installed-manual
installation, and all lifecycle/authentication behavior.  This descriptor owns
only the data that makes the ``system`` package's existing model-facing family
self-describing: its public identity, installed-manual skill name, and ordered
strict action-input metadata.  ``__init__`` consumes it to compose the schema,
register children, and select the existing post-dispatch manual adapter.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .schema import ACTION_ENUM_DESCRIPTION, ACTION_ORDER, INPUT_SCHEMAS, get_description


@dataclass(frozen=True, slots=True)
class SystemActionMetadata:
    """One canonical action branch owned by the ``system`` package."""

    name: str
    input_schema: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class SystemToolDescriptor:
    """The package-local model-facing identity and action metadata for ``system``."""

    name: str
    manual_skill_name: str
    actions: tuple[SystemActionMetadata, ...]
    action_enum_description: str
    description: str

    @property
    def action_names(self) -> tuple[str, ...]:
        """Return the canonical action order used by every model schema branch."""
        return tuple(action.name for action in self.actions)


SYSTEM_TOOL_DESCRIPTOR = SystemToolDescriptor(
    name="system",
    # This is the installed intrinsic-skill destination read by the existing
    # shared loader, not a package-relative manual path and not a Host registry
    # declaration.  The Host retains installation/lifecycle ownership.
    manual_skill_name="system-manual",
    actions=tuple(
        SystemActionMetadata(name=action, input_schema=INPUT_SCHEMAS[action])
        for action in ACTION_ORDER
    ),
    action_enum_description=ACTION_ENUM_DESCRIPTION,
    description=get_description(),
)
