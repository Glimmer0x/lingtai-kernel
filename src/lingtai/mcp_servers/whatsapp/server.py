"""LingTai WhatsApp MCP server."""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any

import mcp.types as types
from mcp.server import Server, ServerRequestContext
from mcp.server.stdio import stdio_server

from .. import _config
from .._results import json_tool_result as _tool_result
from .._results import text_resource_result as _resource_result
from .._results import unknown_resource_error as _unknown_resource
from .._results import unknown_tool_error as _unknown_tool
from .licc import push_inbox_event
from .manager import WhatsAppManager, SCHEMA, DESCRIPTION
from .resources import resource_text
from .webhook_server import WhatsAppWebhookServer

log = logging.getLogger("lingtai.mcp_servers.whatsapp")

_SERVER_INSTRUCTIONS = (
    "lingtai-whatsapp: official Meta WhatsApp Cloud API client. "
    "Configure via LINGTAI_WHATSAPP_CONFIG. Inbound delivery requires a public HTTPS webhook."
)


def load_config() -> tuple[dict[str, Any], Path]:
    return _config.load_config_file(
        "LINGTAI_WHATSAPP_CONFIG",
        label="WhatsApp",
        missing_env_msg="LINGTAI_WHATSAPP_CONFIG env var not set",
    )


def _accounts_from_config(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    accounts = cfg.get("accounts")
    if not accounts:
        raise ValueError("config must contain 'accounts' list")
    return list(accounts)


def build_manager() -> tuple[WhatsAppManager, Path]:
    cfg, config_path = load_config()
    working_dir = Path(os.environ.get("LINGTAI_AGENT_DIR", os.getcwd()))
    working_dir.mkdir(parents=True, exist_ok=True)

    def _on_inbound(event: dict[str, Any]) -> None:
        push_inbox_event(sender=event["from"], subject=event["subject"], body=event["body"], metadata=event.get("metadata"), wake=event.get("wake", True))

    manager = WhatsAppManager(
        accounts_config=_accounts_from_config(cfg),
        working_dir=working_dir,
        on_inbound=_on_inbound,
        config_source=os.environ.get("LINGTAI_WHATSAPP_CONFIG") or str(config_path),
    )
    try:
        path = manager.write_identity_file()
        log.info("Wrote WhatsApp MCP identity metadata to %s", path)
    except Exception as e:
        log.warning("Failed to write WhatsApp MCP identity metadata (continuing): %s", e)
    return manager, working_dir


def build_server(manager: WhatsAppManager | None) -> Server:
    async def _list_tools(
        _ctx: ServerRequestContext,
        _params: types.PaginatedRequestParams | None,
    ) -> types.ListToolsResult:
        return types.ListToolsResult(
            tools=[types.Tool(name="whatsapp", description=DESCRIPTION, input_schema=SCHEMA)],
        )

    async def _call_tool(
        _ctx: ServerRequestContext,
        params: types.CallToolRequestParams,
    ) -> types.CallToolResult:
        if params.name != "whatsapp":
            raise _unknown_tool(params.name)
        if manager is None:
            return _tool_result({"status": "error", "error": "WhatsApp manager not initialized; check LINGTAI_WHATSAPP_CONFIG"})
        try:
            result = await asyncio.to_thread(manager.handle, params.arguments or {})
        except Exception as e:
            result = {"status": "error", "error": str(e), "error_type": type(e).__name__}
        return _tool_result(result)

    async def _list_resources(
        _ctx: ServerRequestContext,
        _params: types.PaginatedRequestParams | None,
    ) -> types.ListResourcesResult:
        return types.ListResourcesResult(
            resources=[types.Resource(uri=uri, name=uri.rsplit("/", 1)[-1], mime_type=mime) for uri, mime in [
                ("lingtai://manifest", "application/json"),
                ("lingtai://skills/whatsapp", "text/markdown; profile=lingtai-skill"),
                ("lingtai://docs/configuration", "text/markdown"),
                ("lingtai://docs/troubleshooting", "text/markdown"),
                ("lingtai://status", "application/json"),
                ("lingtai://onboarding/whatsapp", "text/markdown"),
                ("lingtai://onboarding/html-template", "text/html"),
            ]],
        )

    async def _read_resource(
        _ctx: ServerRequestContext,
        params: types.ReadResourceRequestParams,
    ) -> types.ReadResourceResult:
        status = manager.handle({"action": "status"}) if manager is not None else {"status": "not_initialized"}
        uri = str(params.uri)
        try:
            text, mime = resource_text(uri, status)
        except KeyError as exc:
            # `resource_text` signals an unlisted URI with a bare KeyError,
            # which would flatten to -32603. Same lookup-miss classification as
            # the other resource servers.
            raise _unknown_resource(uri) from exc
        return _resource_result(uri, text, mime)

    server: Server = Server(
        "lingtai-whatsapp",
        instructions=_SERVER_INSTRUCTIONS,
        on_list_tools=_list_tools,
        on_call_tool=_call_tool,
        on_list_resources=_list_resources,
        on_read_resource=_read_resource,
    )
    return server


async def serve() -> None:
    manager: WhatsAppManager | None = None
    webhook_server: WhatsAppWebhookServer | None = None
    try:
        manager, _wd = build_manager()
        log.info("WhatsApp manager initialized")
        webhook_server = WhatsAppWebhookServer.from_manager_config(manager)
        if webhook_server is not None:
            webhook_server.start()
    except Exception as e:
        log.error("eager start failed; tool calls will return errors until fixed: %s", e)
    server = build_server(manager)
    try:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())
    finally:
        if webhook_server is not None:
            webhook_server.stop()
