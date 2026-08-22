"""Package-local composition descriptor for the ``notification`` root.

The mandatory-intrinsic registry continues to import ``lingtai.tools.notification``
directly; it does not gain a second activation path.  This descriptor keeps the
model-facing root's identity, action schema ownership, and installed manual
projection beside the action implementation so the package can be inspected or
extracted without relying on registry or Agent changes.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

from ..tool_family import ChildTool, ToolFamily
from ..tool_family.manual import build_manual_child
from .schema import ACTION_ORDER, INPUT_SCHEMAS


ActionHandler = Callable[[Mapping[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class NotificationToolDescriptor:
    """The one model-facing notification family owned by this package.

    ``action_order`` and ``input_schemas`` are the canonical strict action
    declarations from :mod:`.schema`.  Both schema projection and dispatch
    construction consume those same objects, while ``manual_skill_name`` names
    the package's ``manual/`` installation destination.  The existing Agent
    installer already copies every ``lingtai.tools.<package>/manual/`` tree to
    that destination; no global registration or lifecycle behavior changes.
    """

    name: str
    action_order: tuple[str, ...]
    input_schemas: Mapping[str, Mapping[str, Any]]
    manual_skill_name: str

    def build_schema_family(self) -> ToolFamily:
        """Build the schema-only family from the exact dispatched schemas."""

        def _unused(_input: Mapping[str, Any]) -> dict[str, Any]:
            raise AssertionError("the notification schema-only family never dispatches")

        return ToolFamily(
            self.name,
            [
                ChildTool(action, self.input_schemas[action], _unused, title=f"{action} input")
                for action in self.action_order
            ],
        )

    def build_dispatch_family(
        self, handlers: Mapping[str, ActionHandler], agent: Any
    ) -> ToolFamily:
        """Bind all operational children and the one package-owned manual child.

        Passing a complete operational mapping is deliberate: a descriptor
        cannot silently advertise an action that dispatch does not bind.  The
        shared manual child is the real family child and receives this
        descriptor's installed destination, so manual schema, dispatch, and
        package-local ``manual/`` projection remain one composition.
        """
        operational_actions = tuple(action for action in self.action_order if action != "manual")
        if set(handlers) != set(operational_actions):
            raise ValueError(
                f"{self.name} handlers must match operational actions "
                f"{operational_actions!r}, got {tuple(handlers)!r}"
            )

        children: list[ChildTool] = []
        for action in self.action_order:
            if action == "manual":
                children.append(build_manual_child(agent, self.manual_skill_name))
            else:
                children.append(
                    ChildTool(
                        action,
                        self.input_schemas[action],
                        handlers[action],
                        title=f"{action} input",
                    )
                )
        return ToolFamily(self.name, children)


NOTIFICATION_TOOL = NotificationToolDescriptor(
    name="notification",
    action_order=ACTION_ORDER,
    input_schemas=INPUT_SCHEMAS,
    # Agent._install_intrinsic_manuals already maps <tool>/manual/ to this
    # exact flat capability name.  The ToolFamily manual child reads the same
    # installed destination; this is not an unused packaging hint.
    manual_skill_name="notification",
)
