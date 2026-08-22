"""Package-owned descriptor for the one public ``web`` tool root.

This module is deliberately a local composition aid, not a second capability
registry.  The host still decides whether to register ``web``, while this
package owns the stable public root metadata and turns its two strict action
schemas plus reserved manual action into the generic ``ToolFamily`` used for
both model schema composition and per-Agent dispatch.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

from ..tool_family import ChildTool, ToolFamily
from ..tool_family.manual import MANUAL_INPUT_SCHEMA, build_manual_child

WebHandler = Callable[[Mapping[str, Any]], dict[str, Any]]


@dataclass(frozen=True, slots=True)
class WebActionDescriptor:
    """One strict non-manual action owned by the public ``web`` root."""

    name: str
    input_schema: Mapping[str, Any]
    title: str


@dataclass(frozen=True, slots=True)
class WebToolDescriptor:
    """Stable local metadata and family builders for canonical ``web``.

    The descriptor intentionally owns only public-root metadata, strict action
    schemas, and the installed manual destination.  It never registers a
    capability, selects a search provider, constructs a browser transport, or
    reads settings: those remain at the existing host/composition and action
    boundaries in :mod:`lingtai.tools.web_search`.
    """

    name: str
    description: str
    manual_skill_name: str
    actions: tuple[WebActionDescriptor, ...]

    @property
    def action_names(self) -> tuple[str, ...]:
        """The fixed public action order, including the reserved manual child."""
        return (*tuple(action.name for action in self.actions), "manual")

    def build_schema_family(self) -> ToolFamily:
        """Build the schema-only family from this descriptor's exact actions.

        The manual child deliberately uses the generic owner's canonical strict
        empty schema.  It has a no-op handler because this family is used only
        by ``get_schema``; a per-Agent family below owns actual dispatch.
        """
        def unused(_input: Mapping[str, Any]) -> dict[str, Any]:
            raise AssertionError("the schema-only web ToolFamily never dispatches")

        return ToolFamily(
            self.name,
            [
                *(
                    ChildTool(action.name, action.input_schema, unused, title=action.title)
                    for action in self.actions
                ),
                ChildTool("manual", MANUAL_INPUT_SCHEMA, unused, title="manual input"),
            ],
        )

    def build_dispatch_family(
        self, agent: Any, handlers: Mapping[str, WebHandler],
    ) -> ToolFamily:
        """Bind the descriptor's actions and direct generic ManualTool child.

        Rejecting a mismatched handler map at construction preserves the one
        descriptor-to-schema-to-dispatch source of truth.  The manual child is
        registered directly from ``build_manual_child`` so generic dispatch
        returns its canonical result verbatim; the web manager remains solely
        responsible for its existing post-dispatch public-shape adaptation.
        """
        action_names = tuple(action.name for action in self.actions)
        if set(handlers) != set(action_names):
            raise ValueError("web dispatch handlers must match the descriptor's non-manual actions")
        return ToolFamily(
            self.name,
            [
                *(
                    ChildTool(action.name, action.input_schema, handlers[action.name], title=action.title)
                    for action in self.actions
                ),
                build_manual_child(agent, self.manual_skill_name),
            ],
        )
