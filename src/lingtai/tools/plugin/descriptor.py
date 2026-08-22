"""Package-local declaration of the model-facing ``plugin`` family.

This descriptor is deliberately declarative, not an Agent Plugin runtime.  It
owns only the stable public identity and the two-child family composition for
this package: ``info`` is package-owned, and the reserved ``manual`` child is
bound to this package's installed-manual destination.  The generic manual
builder still owns loading from the Host-installed intrinsic library; this
module must not read ``manual/SKILL.md`` directly and thereby bypass the Host's
skill/prompt lifecycle.

Nothing here discovers plugin directories, mounts skills, writes MCP records,
or activates servers.  Those boot-time, containment, registration, and
lifecycle concerns stay in their existing Host/service owners.  The descriptor
only makes the package's strict ``info``/``manual`` family impossible to drift
from its own manual binding.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from ..tool_family import RESERVED_MANUAL_NAME, ChildTool, ToolFamily
from ..tool_family.manual import MANUAL_INPUT_SCHEMA, build_manual_child

__all__ = ["PLUGIN_TOOL", "PluginToolDescriptor", "PluginToolDescriptorError"]


class PluginToolDescriptorError(ValueError):
    """Raised when this package's fixed public-family declaration is invalid."""


@dataclass(frozen=True, slots=True)
class PluginToolDescriptor:
    """The package-owned model-tool identity and strict family composition.

    ``manual_skill_name`` names the *Host-installed* intrinsic-manual
    destination, not a package file to load.  :meth:`manual_child` delegates
    the actual loading and truthful degraded result to
    :func:`build_manual_child`; that preserves the Host's installed skill and
    prompt lifecycle while keeping the package's binding to ``plugin`` local.
    """

    name: str
    info_action: str
    manual_skill_name: str

    def __post_init__(self) -> None:
        for attribute in ("name", "info_action", "manual_skill_name"):
            value = getattr(self, attribute)
            if not isinstance(value, str) or not value.strip():
                raise PluginToolDescriptorError(
                    f"PluginToolDescriptor {attribute!r} must be a non-empty string"
                )
        if self.info_action == RESERVED_MANUAL_NAME:
            raise PluginToolDescriptorError(
                "PluginToolDescriptor info_action must not use the reserved 'manual' action"
            )

    @property
    def actions(self) -> tuple[str, str]:
        """The complete public action inventory, with the reserved manual last."""
        return self.info_action, RESERVED_MANUAL_NAME

    def info_child(
        self, handler: Callable[[Mapping[str, Any]], dict[str, Any]]
    ) -> ChildTool:
        """Build this package's read-only ``info`` child.

        ``info`` has no action-specific arguments.  It shares the generic
        canonical strict-empty schema with the reserved manual child rather
        than restating a near-duplicate in this package.
        """
        return ChildTool(
            self.info_action,
            MANUAL_INPUT_SCHEMA,
            handler,
            title=f"{self.info_action} input",
        )

    def manual_child(self, agent: Any) -> ChildTool:
        """Build the reserved child bound to this package's installed manual.

        The returned child is registered directly by :meth:`build_family`,
        unwrapped, so ``ToolFamily.handle`` dispatches its canonical result
        before this package's outer presentation adapter flattens it.
        """
        return build_manual_child(agent, self.manual_skill_name)

    def build_family(
        self,
        agent: Any,
        info_handler: Callable[[Mapping[str, Any]], dict[str, Any]],
    ) -> ToolFamily:
        """Compose the one strict package family without any runtime activation."""
        return ToolFamily(self.name, [self.info_child(info_handler), self.manual_child(agent)])


PLUGIN_TOOL = PluginToolDescriptor(
    name="plugin",
    info_action="info",
    manual_skill_name="plugin",
)
