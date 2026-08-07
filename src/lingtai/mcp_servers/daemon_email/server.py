"""LingTai daemon-email MCP server.

Exposes the exact same LTP v2 ``email`` tool family a live agent uses
(``lingtai.tools.email`` — ``action``/``input``/``reasoning`` envelope,
composed by ``ToolFamily``) to daemon runs, over MCP instead of the
in-process intrinsic layer daemons never wire. The schema, description, and
dispatch logic are the real ``lingtai.tools.email`` module, unmodified — this
server only supplies the ``agent``-shaped object that module expects
(``DaemonEmailAgentShim``), bound to the parent agent's working directory.

Because that shim resolves to the *parent's* own mailbox (same address, same
``working_dir/mailbox/`` the parent's live ``EmailManager`` reads and
writes), a daemon started from a parent, the parent itself, and any sibling
daemon started from that same parent are all reachable at the identical
mail address — the parent's working-directory name. Daemon-to-daemon email
between siblings of the same parent, and daemon-to-parent email, both work
through the unmodified filesystem delivery mechanism
(``PosixFilesystemMailAdapter`` — handshake against ``.agent.json`` +
``.agent.heartbeat``, then an atomic write into the recipient's
``mailbox/inbox/``); no new transport was introduced.

Env vars:
    LINGTAI_AGENT_DIR — the parent agent's working directory. Injected by
        the daemon subsystem (``DaemonManager._daemon_email_mcp_registration``)
        for every daemon task that explicitly requests ``tools: ["email"]``;
        falls back to the process cwd only when run standalone/for tests.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

import mcp.types as types
from mcp.server import Server, ServerRequestContext
from mcp.server.stdio import stdio_server

from lingtai.tools import email as email_tool

from .._results import json_tool_result as _tool_result
from .._results import unknown_tool_error as _unknown_tool
from .agent_shim import DaemonEmailAgentShim

log = logging.getLogger("lingtai.mcp_servers.daemon_email")

_TOOL_NAME = "email"

_SERVER_INSTRUCTIONS = (
    "lingtai-daemon-email: the same `email` tool a live LingTai agent has, "
    "exposed to this daemon run over MCP. Operates on the parent agent's own "
    "mailbox, so send/check/read/reply/search/contacts reach and are reached "
    "by the parent and any sibling daemon the parent has spawned."
)


def _working_dir() -> Path:
    raw = os.environ.get("LINGTAI_AGENT_DIR")
    return Path(raw) if raw else Path.cwd()


def build_agent() -> DaemonEmailAgentShim:
    agent = DaemonEmailAgentShim(_working_dir())
    email_tool.boot(agent)
    return agent


def build_server(agent: DaemonEmailAgentShim) -> Server:
    async def _list_tools(
        _ctx: ServerRequestContext,
        _params: types.PaginatedRequestParams | None,
    ) -> types.ListToolsResult:
        return types.ListToolsResult(
            tools=[
                types.Tool(
                    name=_TOOL_NAME,
                    description=email_tool.get_description(),
                    input_schema=email_tool.get_schema(),
                ),
            ],
        )

    async def _call_tool(
        _ctx: ServerRequestContext,
        params: types.CallToolRequestParams,
    ) -> types.CallToolResult:
        if params.name != _TOOL_NAME:
            raise _unknown_tool(params.name)
        try:
            result = email_tool.handle(agent, dict(params.arguments or {}))
        except Exception as e:
            result = {
                "status": "error",
                "error": str(e),
                "error_type": type(e).__name__,
            }
        return _tool_result(result)

    return Server(
        "lingtai-daemon-email",
        instructions=_SERVER_INSTRUCTIONS,
        on_list_tools=_list_tools,
        on_call_tool=_call_tool,
    )


async def serve() -> None:
    agent = build_agent()
    server = build_server(agent)
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )
