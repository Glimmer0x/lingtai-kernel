"""Minimal stdio MCP server for the ``hello-lingtai`` example Agent Plugin.

Deliberately **stdlib only**. A real third-party plugin cannot import the kernel
it is dropped into, and it cannot assume which MCP SDK — or which SDK major
version — the host happens to have installed for the ``python3`` on PATH. So
this speaks the wire protocol directly: newline-delimited JSON-RPC 2.0 over
stdio, which is exactly what the MCP stdio transport is. It runs under any
Python 3 with no third-party packages at all.

Four methods, which is everything a tools-only server needs: ``initialize``,
``notifications/initialized``, ``tools/list``, ``tools/call`` (plus ``ping``).
The one tool is ``hello``.

Logs go to stderr. stdout is the JSON-RPC channel and writing anything else
there corrupts the session; that is the one rule an MCP server author cannot
break.
"""
from __future__ import annotations

import json
import sys

SERVER_NAME = "hello-lingtai"
SERVER_VERSION = "1.0.0"

#: Used only when a client omits ``protocolVersion``. Otherwise the client's
#: requested version is echoed back, which is the negotiation every MCP client
#: expects and keeps this example working as the spec revision moves.
FALLBACK_PROTOCOL_VERSION = "2025-06-18"

TOOLS = [
    {
        "name": "hello",
        "description": (
            "Return a greeting. Exists to prove an Agent Plugin's mcp.json "
            "server was registered and can actually be reached."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Who to greet. Defaults to 'world'.",
                },
            },
            "required": [],
            "additionalProperties": False,
        },
    },
]


def _log(message: str) -> None:
    print(f"[{SERVER_NAME}] {message}", file=sys.stderr, flush=True)


def _text_result(text: str, *, is_error: bool = False) -> dict:
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


def _handle(method: str, params: dict) -> dict:
    """Return the JSON-RPC ``result`` for one request. Raises for unknown methods."""
    if method == "initialize":
        requested = params.get("protocolVersion")
        return {
            "protocolVersion": (
                requested if isinstance(requested, str) and requested
                else FALLBACK_PROTOCOL_VERSION
            ),
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            "instructions": (
                "Call `hello` to confirm this plugin's MCP server is live."
            ),
        }
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": TOOLS}
    if method == "tools/call":
        name = params.get("name")
        if name != "hello":
            return _text_result(f"unknown tool: {name!r}", is_error=True)
        arguments = params.get("arguments") or {}
        who = arguments.get("name") or "world"
        return _text_result(f"hello, {who} — from the {SERVER_NAME} Agent Plugin")
    raise LookupError(method)


def main() -> None:
    _log("started")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError as e:
            _log(f"dropping unparseable line: {e}")
            continue
        if not isinstance(message, dict):
            continue

        method = message.get("method")
        request_id = message.get("id")
        # A message with no `id` is a notification: handle nothing, answer
        # nothing. Replying to one is a protocol violation.
        if request_id is None:
            continue

        params = message.get("params")
        params = params if isinstance(params, dict) else {}
        try:
            response = {"jsonrpc": "2.0", "id": request_id, "result": _handle(method, params)}
        except LookupError:
            response = {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32601, "message": f"method not found: {method}"},
            }
        except Exception as e:  # a tool bug must not kill the session
            _log(f"internal error handling {method!r}: {e}")
            response = {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32603, "message": f"internal error: {e}"},
            }
        sys.stdout.write(json.dumps(response) + "\n")
        sys.stdout.flush()
    _log("stdin closed, exiting")


if __name__ == "__main__":
    main()
