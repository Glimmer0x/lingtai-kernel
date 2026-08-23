"""Family-agnostic seams for declared host-plugin tests.

This helper intentionally exercises only the generic declaration/host boundary.
Family-specific setup, runtime handlers, and manual paths belong in each
candidate's own vertical slice and must not be imported here.
"""

from typing import Any

from lingtai.adapters.tool_plugin_host import agent_host_ports
from lingtai.kernel.tool_plugin import ToolPluginDeclaration, ToolPluginHost


def dispatch_declared_tool(
    declaration: ToolPluginDeclaration, agent: Any, args: dict[str, Any]
) -> Any:
    """Bind one declaration against the agent's least-privilege host ports."""

    host = ToolPluginHost.grant(declaration, agent_host_ports(agent, declaration.name))
    return declaration.bind(host).handler(args)
