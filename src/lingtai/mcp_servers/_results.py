"""Typed MCP result builders shared by the curated LingTai MCP servers.

Official SDK v2 removed the low-level ``Server``'s automatic return-value
wrapping: a handler now returns the complete result object. Every curated
server answers a tool call with one JSON-serialized text block and every
resource read with one text block, so those two shapes live here once rather
than being rebuilt in seven files.

The provider payload convention is unchanged and has two spellings in the
existing managers: an explicit ``{"status": "error", ...}`` envelope, and a
bare ``{"error": "..."}`` dict. Both mean the same thing, so both must set the
protocol error bit. A provider-level failure is a recoverable tool error the
model is meant to read, so it stays a ``CallToolResult`` with ``is_error=True``
rather than becoming a JSON-RPC protocol error.

A *lookup* failure is the opposite case and is not a tool result at all: the
2026-07-28 schema classifies an unknown tool name or an unknown resource URI as
``InvalidParamsError`` (``-32602``), a caller-fixable parameter error. The two
raisers below build that error so the bundled lookup branches cannot drift
apart.
"""
from __future__ import annotations

import json
from typing import Any

import mcp.types as types
from mcp.shared.exceptions import MCPError


def unknown_tool_error(name: str) -> MCPError:
    """Build the protocol error for a tool name this server does not serve.

    Raise (do not return) the result: a lookup miss is a JSON-RPC error, not a
    ``CallToolResult(is_error=True)``. Only an explicit ``MCPError`` keeps its
    chosen code through the v2 dispatcher; a generic exception would be
    flattened to ``INTERNAL_ERROR`` and read as a server fault rather than a
    caller-fixable one.
    """
    return MCPError(
        code=types.INVALID_PARAMS,
        message=f"Unknown tool: {name}",
        data={"requested": name},
    )


def unknown_resource_error(uri: str) -> MCPError:
    """Build the protocol error for a resource URI this server does not serve."""
    return MCPError(
        code=types.INVALID_PARAMS,
        message=f"Unknown resource: {uri}",
        data={"uri": uri},
    )


def payload_is_error(payload: dict[str, Any]) -> bool:
    """Report whether a provider payload describes a failure.

    Recognizes every manager/family convention in this package. Getting this
    wrong is silent: a failure that does not set ``is_error`` reaches the model
    as a success.
    """
    # ``error`` is the legacy manager spelling; ``failed`` is the LTP-v2
    # ToolFamily spelling introduced with the native Telegram/Task Card
    # families (#1081), which reject with {"status": "failed", "error_code": ...}.
    if payload.get("status") in {"error", "failed"}:
        return True
    # Several managers return a bare {"error": ...} with no status field.
    return "error" in payload and payload.get("status") is None


def json_tool_result(payload: dict[str, Any]) -> types.CallToolResult:
    """Build the canonical curated-server tool result.

    The payload is emitted twice on purpose: as the JSON text block the model
    reads, and as ``structured_content`` for application code. ``is_error``
    tracks the provider's own outcome, preserving the pre-migration behavior
    where an error payload was still a readable tool result.
    """
    return types.CallToolResult(
        content=[
            types.TextContent(
                type="text", text=json.dumps(payload, ensure_ascii=False),
            ),
        ],
        structured_content=payload,
        is_error=payload_is_error(payload),
    )


def text_resource_result(uri: str, text: str, mime_type: str) -> types.ReadResourceResult:
    """Build a single-text-block ``resources/read`` result."""
    return types.ReadResourceResult(
        contents=[
            types.TextResourceContents(uri=uri, text=text, mime_type=mime_type),
        ],
    )
