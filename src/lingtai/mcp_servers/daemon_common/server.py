"""LingTai daemon common MCP server.

The model-visible contract is the ``finish`` tool, in the LTP v2
``action``/``input``/``reasoning`` envelope every curated LingTai MCP tool
uses (``tools/CONTRACT.md``) rather than bare MCP params. The JSON file it
writes is an internal daemon transport and is validated again by the daemon
runner before any backend is allowed to mark a run done.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import mcp.types as types
from mcp.server import Server, ServerRequestContext
from mcp.server.stdio import stdio_server

from lingtai.kernel._fsutil import atomic_write_json

from .._results import json_tool_result as _tool_result
from .._results import unknown_tool_error as _unknown_tool

STATUSES = {"done", "failed", "incomplete"}

_ACTIONS = ("finish",)

_FINISH_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {
            "type": "string",
            "enum": sorted(STATUSES),
            "description": "Terminal daemon status: done, failed, or incomplete.",
        },
        "summary": {
            "type": "string",
            "description": "Short result summary for the parent agent.",
        },
        "reason": {
            "type": "string",
            "description": "Required when status is failed or incomplete.",
        },
        "artifacts": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Optional run-dir-relative or absolute artifact paths.",
        },
    },
    "required": ["status"],
    "additionalProperties": False,
}

FINISH_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": list(_ACTIONS),
            "description": "Required operation. Only 'finish' exists today.",
        },
        "input": {
            "description": "Strict action-specific input; re-validated at dispatch.",
            **_FINISH_INPUT_SCHEMA,
        },
        "reasoning": {
            "type": "string",
            "description": "Brief explanation of why you are calling this tool (recorded in your diary).",
        },
    },
    "required": ["action", "input", "reasoning"],
    "additionalProperties": False,
}

DESCRIPTION = (
    "Finish this LingTai daemon run. Call exactly once before your final answer: "
    "finish(action='finish', input={'status': ...}, reasoning='...'). "
    "Use status='done' only when the task is complete; use status='failed' or "
    "status='incomplete' when blocked, unvalidated, or unable to finish."
)


def _completion_path() -> Path:
    raw = os.environ.get("LINGTAI_DAEMON_COMPLETION_FILE")
    if not raw:
        raise RuntimeError("missing LINGTAI_DAEMON_COMPLETION_FILE")
    return Path(raw)


def _validate_finish(arguments: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(arguments, dict):
        raise ValueError("finish arguments must be an object")
    action = arguments.get("action")
    if action not in _ACTIONS:
        raise ValueError(f"action must be one of: {', '.join(_ACTIONS)}")
    input_ = arguments.get("input")
    if not isinstance(input_, dict):
        raise ValueError("input must be an object")
    # A real MCP wire call carries ``reasoning`` verbatim. A same-process
    # dispatch (``execution_host.py``'s local ``finish`` shortcut for the
    # LingTai backend) goes through ``kernel.tool_executor``, which extracts
    # and logs ``reasoning`` before re-adding it as ``_reasoning`` — the same
    # dual-spelling tolerance ``ToolFamily``'s generic envelope validator
    # uses (``tool_family/__init__.py`` ``_ROOT_FIELDS``).
    reasoning = arguments.get("reasoning", arguments.get("_reasoning"))
    if not isinstance(reasoning, str) or not reasoning.strip():
        raise ValueError("reasoning is required")
    if set(arguments) - {"action", "input", "reasoning", "_reasoning"}:
        raise ValueError("unsupported finish argument")

    status = input_.get("status")
    if status not in STATUSES:
        raise ValueError("status must be one of: done, failed, incomplete")
    summary = input_.get("summary")
    reason = input_.get("reason")
    artifacts = input_.get("artifacts")
    if summary is not None and not isinstance(summary, str):
        raise ValueError("summary must be a string")
    if reason is not None and not isinstance(reason, str):
        raise ValueError("reason must be a string")
    if artifacts is not None and (
        not isinstance(artifacts, list)
        or not all(isinstance(item, str) for item in artifacts)
    ):
        raise ValueError("artifacts must be an array of strings")
    if status in {"failed", "incomplete"} and not (reason and reason.strip()):
        raise ValueError("reason is required for failed or incomplete status")
    payload = {
        "schema": "lingtai.daemon_completion.v1",
        "status": status,
        "run_id": os.environ.get("LINGTAI_DAEMON_RUN_ID"),
    }
    if summary is not None:
        payload["summary"] = summary
    if reason is not None:
        payload["reason"] = reason
    if artifacts is not None:
        payload["artifacts"] = artifacts
    return payload


def build_server() -> Server:
    async def _list_tools(
        _ctx: ServerRequestContext,
        _params: types.PaginatedRequestParams | None,
    ) -> types.ListToolsResult:
        return types.ListToolsResult(
            tools=[
                types.Tool(
                    name="finish",
                    description=DESCRIPTION,
                    input_schema=FINISH_SCHEMA,
                ),
            ],
        )

    async def _call_tool(
        _ctx: ServerRequestContext,
        params: types.CallToolRequestParams,
    ) -> types.CallToolResult:
        if params.name != "finish":
            # A lookup miss is a caller-fixable parameter error (-32602), not a
            # tool failure the model should try to recover from.
            raise _unknown_tool(params.name)
        try:
            payload = _validate_finish(params.arguments or {})
            path = _completion_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_json(path, payload, ensure_ascii=False, indent=2)
            result = {
                "status": "ok",
                "completion_status": payload["status"],
                "message": "daemon completion recorded",
            }
        except Exception as e:
            result = {
                "status": "error",
                "error": str(e),
                "error_type": type(e).__name__,
            }
        return _tool_result(result)

    server: Server = Server(
        "lingtai-daemon-common",
        instructions=(
            "Use the `finish` tool to explicitly complete the daemon run. "
            "Do not rely on final text alone."
        ),
        on_list_tools=_list_tools,
        on_call_tool=_call_tool,
    )
    return server


async def serve() -> None:
    server = build_server()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )
