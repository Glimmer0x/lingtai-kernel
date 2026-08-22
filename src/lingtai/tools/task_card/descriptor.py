"""Static model-facing descriptor for the intrinsic ``task_card`` family.

This is deliberately package-local and consumed by the existing Task Card
controller.  It names the one public root, its closed action inventory, and the
manual binding without registering, activating, or hosting the capability.
Threads, renderer subprocess execution, artifact writes, notifications, and
channel projections remain in their existing owners.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TaskCardToolDescriptor:
    """Model-facing facts shared by Task Card schema and registration paths."""

    name: str
    action_names: tuple[str, ...]
    manual_skill_name: str
    description: str
    action_description: str

    def decorate_schema(self, schema: dict[str, Any]) -> dict[str, Any]:
        """Add Task Card's action guidance to its freshly composed LTP schema."""
        schema["properties"]["action"]["description"] = self.action_description
        return schema


DESCRIPTOR = TaskCardToolDescriptor(
    name="task_card",
    action_names=("start", "inspect", "retry", "stop", "remove", "manual"),
    manual_skill_name="task_card",
    description=(
        "Manage the intrinsic declarative Task Card artifact. Provide a Python "
        "renderer under your working directory whose stdout is the full Task Card "
        "body to write into taskcard/taskcard.md. The capability writes taskcard/"
        "taskcard.md atomically, writes taskcard/status as exact active/inactive, "
        "keeps at most one active watch per agent, and leaves projection to "
        "channel-specific readers. Use it proactively for meaningful long-running, "
        "multi-step, or parallel work so a human can follow progress; skip it for "
        "quick single-step work, ritual updates, or a body you cannot keep truthful "
        "and current. Restart a new watch when one expires mid-task. Use stop to "
        "pause a watch while preserving its last body, and remove once the work is "
        "completed, cancelled, or abandoned so the artifact cannot mislead a consumer "
        "as stale. Actions: start, inspect, retry, stop, remove, manual."
    ),
    action_description=(
        "Declarative Task Card action. start keeps one renderer watch writing the "
        "agent-local taskcard/status and taskcard/taskcard.md files; inspect, retry, "
        "and stop read or control that one artifact; remove is the terminal "
        "lifecycle cleanup; manual explains the full contract."
    ),
)
