"""Declarative package-local descriptor for the model-facing ``mcp`` root.

This is deliberately not an MCP runtime or registry.  It owns only the static
model-facing identity that the ``mcp`` package itself can state safely: public
name/action order, strict action-input declarations, signpost descriptions, and
the reserved package-owned manual child.  The host continues to own capability
discovery, registry validation and writes, activation, transports, credentials,
inbox notifications, and collision decisions.

``mcp.__init__`` explicitly consumes this descriptor when it composes the
schema-only and agent-bound ToolFamilies, renders both descriptions, checks
unknown actions, and dispatches the bundled manual.  Nothing discovers this
module dynamically or treats its presence as activation.
"""
from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ..tool_family import RESERVED_MANUAL_NAME, ChildTool, ToolFamily
from ..tool_family.manual import MANUAL_INPUT_SCHEMA
from .manual import build_manual_child

__all__ = [
    "MCP_ACTIONS",
    "MCP_DECLARED_ACTIONS",
    "MCP_INPUT_SCHEMAS",
    "MCP_PLUGIN",
    "McpToolPlugin",
    "McpToolPluginError",
]


class McpToolPluginError(ValueError):
    """Raised for an MCP package descriptor defect before it can ship."""


@dataclass(frozen=True)
class McpToolPlugin:
    """MCP root's local model-facing identity and family composition helpers.

    ``declared`` actions belong to this package; the reserved ``manual`` action
    is appended from :mod:`lingtai.tools.mcp.manual` and is never supplied by a
    registry or agent manager.  The descriptor never carries server definitions
    or configuration, so composing it cannot register or activate anything.
    """

    name: str
    package: str
    description: str
    action_description: str

    def __post_init__(self) -> None:
        for field_name in ("name", "package", "description", "action_description"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise McpToolPluginError(
                    f"McpToolPlugin {field_name!r} must be a non-empty string"
                )
        if self.package.rpartition(".")[2] != self.name:
            raise McpToolPluginError(
                f"McpToolPlugin package {self.package!r} must be the {self.name!r} module"
            )

    def actions(self, declared: Sequence[str]) -> tuple[str, ...]:
        """Return package-declared actions followed by the reserved manual action."""
        self._check_declared_names(declared)
        return (*declared, RESERVED_MANUAL_NAME)

    def action_input_schemas(
        self, declared: Mapping[str, Mapping[str, Any]]
    ) -> dict[str, dict[str, Any]]:
        """Return the declared schemas plus the canonical package manual schema."""
        self._check_declared_names(tuple(declared))
        schemas = {name: copy.deepcopy(dict(schema)) for name, schema in declared.items()}
        schemas[RESERVED_MANUAL_NAME] = copy.deepcopy(MANUAL_INPUT_SCHEMA)
        return schemas

    def build_family(self, declared: Sequence[ChildTool]) -> ToolFamily:
        """Compose MCP's public family with its package-owned manual appended."""
        self._check_declared_names([child.name for child in declared])
        return ToolFamily(self.name, [*declared, build_manual_child()])

    def build_schema(self, family: ToolFamily) -> dict[str, Any]:
        """Render a family schema with this package's stable action signpost."""
        schema = family.build_schema()
        schema["properties"]["action"]["description"] = self.action_description
        return schema

    def _check_declared_names(self, declared: Sequence[str]) -> None:
        names = list(declared)
        if not names:
            raise McpToolPluginError(
                f"McpToolPlugin {self.name!r} must declare at least one action"
            )
        if RESERVED_MANUAL_NAME in names:
            raise McpToolPluginError(
                f"McpToolPlugin {self.name!r} must not declare reserved "
                f"{RESERVED_MANUAL_NAME!r}; it is supplied by the package manual"
            )
        if len(set(names)) != len(names):
            raise McpToolPluginError(
                f"McpToolPlugin {self.name!r} declared a duplicate action"
            )


MCP_PLUGIN = McpToolPlugin(
    name="mcp",
    package="lingtai.tools.mcp",
    description=(
        "SIGNPOST ONLY: this tool does not register, activate, configure, or "
        "troubleshoot MCP servers by itself. `info` only re-reads the registry and "
        "returns registry health; `manual` returns the mcp-manual body. "
        "Your per-agent MCP server registry. The <registered_mcp> catalog in your "
        "system prompt lists every MCP server currently registered. Before using "
        "this tool (registering, deregistering, updating, or troubleshooting MCP "
        "servers), read the `mcp-manual` skill — call `manual` to fetch its body "
        "(registration contract, file paths, schema), and call `info` for the current "
        "registry health snapshot; no exceptions. To register, deregister, or update MCPs, edit "
        "mcp_registry.jsonl directly with write/edit and call "
        "system(action=\"refresh\")."
    ),
    action_description=(
        "info: signpost-only action; re-reads the registry and returns "
        "a runtime health snapshot (registry contents, problems, registry path) "
        "without the manual body. manual: return only the mcp-manual skill body. "
        "Neither action mutates MCP configuration."
    ),
)

#: MCP's package-declared model-facing action(s), in stable enum order.
MCP_DECLARED_ACTIONS: tuple[str, ...] = ("info",)

#: Complete public action order. ``manual`` is package-owned and appended.
MCP_ACTIONS: tuple[str, ...] = MCP_PLUGIN.actions(MCP_DECLARED_ACTIONS)

#: One authoritative input-schema listing for both the schema-only and the
#: agent-bound family.  ``info`` happens to be strict-empty; ``manual`` is added
#: by the descriptor from the generic canonical literal.
MCP_INPUT_SCHEMAS = MCP_PLUGIN.action_input_schemas({"info": MANUAL_INPUT_SCHEMA})
