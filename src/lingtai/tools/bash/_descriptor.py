"""Package-local model-facing identity for the canonical :mod:`shell` tool.

The retained implementation package is named ``bash``, but this descriptor owns
only the public family facts that must agree at the package boundary: the model
name, its ordered action ports, and the installed-manual destination name.
``_tool_family`` consumes it when it composes the strict schema, dispatches
children, and builds the reserved manual child; ``setup`` consumes the same
public name when asking the host to register the tool.  It deliberately owns no
policy, command validation, process spawning, or Agent/global-registry logic.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ShellToolDescriptor:
    """Stable package-owned public facts for the ``shell`` family.

    ``manual_skill_name`` is intentionally explicit even though it currently
    equals ``public_name``: ``build_manual_child`` reads an installed intrinsic
    skill directory, not a Python package.  Keeping that destination alongside
    the family identity prevents the retained ``bash`` package name from leaking
    into the model-facing manual lookup.
    """

    public_name: str
    action_names: tuple[str, ...]
    manual_skill_name: str

    def __post_init__(self) -> None:
        if not self.public_name:
            raise ValueError("shell public_name must not be empty")
        if self.action_names != ("run", "poll", "cancel", "manual"):
            raise ValueError("shell action_names must preserve the canonical action order")
        if self.manual_skill_name != self.public_name:
            raise ValueError("shell manual_skill_name must match the public tool name")

    @property
    def unknown_action_message(self) -> str:
        """Return Shell's public fail-closed action diagnostic."""
        return f"action must be one of {', '.join(self.action_names[:-1])}, or {self.action_names[-1]}"


SHELL_TOOL = ShellToolDescriptor(
    public_name="shell",
    action_names=("run", "poll", "cancel", "manual"),
    manual_skill_name="shell",
)

__all__ = ["SHELL_TOOL", "ShellToolDescriptor"]
