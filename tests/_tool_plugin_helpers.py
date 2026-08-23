"""Generic test seam for dispatching an already-declared official tool."""
from __future__ import annotations

from typing import Any

from lingtai.adapters.tool_plugin_host import agent_host_ports
from lingtai.kernel.tool_plugin import ToolPluginDeclaration, ToolPluginHost


def dispatch_declared_tool(
    declaration: ToolPluginDeclaration,
    agent: Any,
    args: dict[str, Any],
) -> dict[str, Any]:
    """Dispatch through the production host adapter and declaration binder.

    This helper is intentionally family-agnostic: callers choose the declared
    family and the live/stub agent supplies its real host ports. It does not
    duplicate a tool handler or construct Notification-specific callbacks.
    """
    host = ToolPluginHost.grant(declaration, agent_host_ports(agent, declaration.name))
    return declaration.bind(host).handler(args)
