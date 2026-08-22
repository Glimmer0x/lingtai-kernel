"""Package-local model-root descriptor for the ``vision`` family.

This module owns only the public action inventory, each action's strict input
schema, and the mapping from the family-owned ``manual`` action to vision's
installed manual.  It deliberately owns no provider selection, credential
resolution, connectivity, capability registration, or presentation adaptation;
those remain in :mod:`lingtai.tools.vision`'s host-facing manager/setup layer.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

from ..tool_family import ChildTool, ToolFamily
from ..tool_family.manual import MANUAL_INPUT_SCHEMA, build_manual_child


Handler = Callable[[Mapping[str, Any]], dict[str, Any]]


def _unreachable(_input: Mapping[str, Any]) -> dict[str, Any]:
    """Guard the schema-only family, which must never dispatch."""
    raise AssertionError("the schema-only vision descriptor family never dispatches")


@dataclass(frozen=True, slots=True)
class VisionActionDescriptor:
    """One vision-owned action's canonical schema and model-facing title."""

    name: str
    input_schema: Mapping[str, Any]
    title: str


@dataclass(frozen=True, slots=True)
class VisionToolDescriptor:
    """The package-local seam for vision's one model-facing root.

    ``build_family()`` is the only place that turns the descriptor into generic
    ``ChildTool`` instances.  Both the schema-only family and the manager-bound
    dispatcher therefore use this same fixed action registry.  When an agent is
    supplied, the reserved ``manual`` child is the generic builder's actual,
    unwrapped child for this descriptor's ``manual_skill_name``; the caller may
    adapt its result only after generic dispatch returns.
    """

    name: str
    manual_skill_name: str
    actions: tuple[VisionActionDescriptor, ...]

    @property
    def action_names(self) -> tuple[str, ...]:
        """Return the one ordered action inventory for schema and dispatch."""
        return tuple(action.name for action in self.actions)

    def build_family(
        self,
        *,
        agent: Any | None = None,
        handlers: Mapping[str, Handler] | None = None,
    ) -> ToolFamily:
        """Build a schema-only or manager-bound family from this descriptor.

        Supplying ``handlers`` binds exactly the non-manual action names the
        descriptor owns.  The reserved ``manual`` action cannot be replaced by
        a caller-supplied handler: with an agent it is built directly by
        ``build_manual_child``; without one it remains unreachable in the
        schema-only family.  This prevents a second registry or a manual wrapper
        from drifting away from the strict model-facing schema.
        """
        if handlers is None:
            bound_handlers: dict[str, Handler] = {}
        else:
            bound_handlers = dict(handlers)
            expected = set(self.action_names) - {"manual"}
            supplied = set(bound_handlers)
            if supplied != expected:
                missing = ", ".join(sorted(expected - supplied)) or "none"
                unknown = ", ".join(sorted(supplied - expected)) or "none"
                raise ValueError(
                    "vision descriptor handlers must bind exactly its non-manual "
                    f"actions (missing: {missing}; unknown: {unknown})"
                )

        children: list[ChildTool] = []
        for action in self.actions:
            if action.name == "manual" and agent is not None:
                # Register the generic ManualTool child directly and unwrapped.
                # Its name/schema are checked against this local declaration so
                # a future generic change cannot silently disconnect vision's
                # advertised strict empty branch from its dispatched handler.
                manual_child = build_manual_child(agent, self.manual_skill_name)
                if (
                    manual_child.name != action.name
                    or manual_child.input_schema != action.input_schema
                    or manual_child.branch_title() != action.title
                ):
                    raise ValueError("vision manual child no longer matches its descriptor")
                children.append(manual_child)
                continue
            children.append(
                ChildTool(
                    action.name,
                    action.input_schema,
                    bound_handlers.get(action.name, _unreachable),
                    title=action.title,
                )
            )
        return ToolFamily(self.name, children)


_ANALYZE_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "image_path": {
            "type": "string",
            "description": "Path to the image file",
        },
        "question": {
            # Strict OpenAI object branches express an optional field as a
            # required nullable property. Null means absent, and the analyze
            # handler then applies the same default prompt it always has.
            "type": ["string", "null"],
            "description": (
                "Question about the image, or null for the default "
                "\"Describe what you see in this image.\""
            ),
        },
        "preset": {
            "type": ["string", "null"],
            "description": (
                "Optional preset name/path whose vision service should be "
                "borrowed for this call (e.g. \"codex-pool\" for gpt-5.6 "
                "vision). Must be a path listed in manifest.preset.allowed. "
                "Null/absent uses the default route (active provider or the "
                "configured vision capability)."
            ),
        },
    },
    "required": ["image_path", "question"],
    "additionalProperties": False,
}

_CHECK_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "preset": {
            "type": ["string", "null"],
            "description": (
                "Optional preset name/path whose vision service should be "
                "checked (e.g. \"codex-pool\" for gpt-5.6 vision). Must be a "
                "path listed in manifest.preset.allowed. Null/absent checks "
                "the default route (active provider or the configured vision "
                "capability). The check resolves the service identity without "
                "sending an image request."
            ),
        },
    },
    "required": ["preset"],
    "additionalProperties": False,
}

_LIST_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {},
    "required": [],
    "additionalProperties": False,
}


VISION_TOOL_DESCRIPTOR = VisionToolDescriptor(
    name="vision",
    manual_skill_name="vision",
    actions=(
        VisionActionDescriptor("analyze", _ANALYZE_INPUT_SCHEMA, "analyze input"),
        VisionActionDescriptor("check", _CHECK_INPUT_SCHEMA, "check input"),
        VisionActionDescriptor("list", _LIST_INPUT_SCHEMA, "list input"),
        VisionActionDescriptor("manual", MANUAL_INPUT_SCHEMA, "manual input"),
    ),
)


__all__ = ["VISION_TOOL_DESCRIPTOR", "VisionActionDescriptor", "VisionToolDescriptor"]
