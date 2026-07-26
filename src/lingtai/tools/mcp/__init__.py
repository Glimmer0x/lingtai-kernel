"""MCP capability — per-agent registry of MCP servers (pure presentation).

Symmetric to the ``knowledge`` / ``skills`` capabilities:

- Per-agent registry lives at ``<agent>/mcp_registry.jsonl`` (sibling to
  ``init.json``). One JSON record per line.
- The capability scans the registry on setup, validates each line, and renders
  the registry as XML into the system prompt's ``mcp`` section.
- Boot-time decompression: any name in ``init.json``'s ``addons: [...]`` list
  that isn't already in the registry gets appended from the kernel-shipped
  catalog (``lingtai/mcp_catalog.json``). Append-only, idempotent.
- All registry mutations (register, deregister, update) happen via file
  operations from the agent (``write``, ``edit``). The capability provides
  guidance via the umbrella SKILL.md, with ``info`` re-rendering the prompt
  section and reporting health while ``manual`` returns the manual body.

Tool surface: ``info`` returns the current registry and a runtime health
snapshot without the manual body; ``manual`` returns the umbrella manual body on
demand.

Ownership: this module is the agent-callable *tool* slice only. The registry
machinery it renders (validation, JSONL I/O, catalog load, identity projection,
addon decompression, XML build) is a service and lives at
``lingtai/services/mcp_registry.py``; it is imported lazily inside ``setup`` and
the handlers, per the ``lingtai.tools → lingtai`` lazy-back-edge rule.

Usage: ``Agent(capabilities=["mcp"])`` or via init.json.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from lingtai.kernel.tool_dispatch import dispatch_action
from lingtai.tools._settings import current_setting, read_settings

if TYPE_CHECKING:
    from lingtai.kernel.base_agent import BaseAgent

PROVIDERS = {"providers": [], "default": "builtin"}


# ---------------------------------------------------------------------------
# Reconciliation (shared by setup and the ``info`` action)
# ---------------------------------------------------------------------------

def _registered_entry(record: dict, identity: dict | None) -> dict:
    """Build one ``registered`` entry, attaching identity only when present."""
    entry = {"name": record["name"], "summary": record["summary"]}
    if identity and identity.get("accounts"):
        entry["identity"] = identity
    return entry


def _reconcile(agent: "BaseAgent") -> dict:
    """Read registry, render into prompt, return health snapshot."""
    from lingtai.services.mcp_registry import (
        read_registry,
        read_identities,
        _build_registry_xml,
        _registry_path,
    )

    working_dir = agent._working_dir
    records, problems = read_registry(working_dir)
    identities = read_identities(working_dir)

    xml = _build_registry_xml(records, identities)
    agent.update_system_prompt("mcp", xml, protected=True)

    # Health: the umbrella manual must be present.
    intrinsic_dir = working_dir / ".library" / "intrinsic"
    manual_path = intrinsic_dir / "capabilities" / "mcp" / "SKILL.md"
    result = {
        "status": "ok",
        "registry_path": str(_registry_path(working_dir)),
        "registered_count": len(records),
        "registered": [
            _registered_entry(r, identities.get(r["name"]))
            for r in records
        ],
        "problems": problems,
    }
    return result


def _manual(agent: "BaseAgent") -> dict:
    manual_path = agent._working_dir / ".library" / "intrinsic" / "capabilities" / "mcp" / "SKILL.md"
    if not manual_path.is_file():
        return {
            "status": "degraded",
            "mcp_manual": "",
            "manual_path": str(manual_path),
            "error": "mcp manual missing — initializer may have failed or capability not installed correctly",
        }
    return {
        "status": "ok",
        "mcp_manual": manual_path.read_text(encoding="utf-8"),
        "manual_path": str(manual_path),
    }


# ---------------------------------------------------------------------------
# Tool surface
# ---------------------------------------------------------------------------

_DESCRIPTION = (
    "SIGNPOST ONLY: this tool does not register, activate, configure, or "
    "troubleshoot MCP servers by itself. Use "
    "mcp(action=\"info\", input={}, reasoning=\"check registry health\") "
    "to re-read the registry and return registry health, or "
    "mcp(action=\"manual\", input={}, reasoning=\"load MCP guidance\") "
    "to return the mcp-manual body. Your per-agent MCP server registry is "
    "listed in the <registered_mcp> catalog in your system prompt. Before using "
    "this tool (registering, deregistering, updating, or troubleshooting MCP "
    "servers), read the `mcp-manual` skill — call `manual` to fetch its body "
    "(registration contract, file paths, schema), and call `info` for the current "
    "registry health snapshot; no exceptions. To register, deregister, or update "
    "MCPs, edit mcp_registry.jsonl directly with write/edit and call "
    "system(action=\"refresh\")."
)

# This is the raw module schema. BaseAgent adds the optional root-level
# ``reasoning`` property when building the model-facing schema; it does not
# belong in either empty ``input`` branch.
_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": ["info", "manual"],
            "description": (
                "info: signpost-only action; re-reads the registry and returns "
                "a runtime health snapshot (registry contents, problems, registry path) "
                "without the manual body. manual: return only the mcp-manual skill body. "
                "Neither action mutates MCP configuration."
            ),
        },
        "input": {
            "anyOf": [
                {
                    "title": "info input",
                    "type": "object",
                    "properties": {},
                    "required": [],
                    "additionalProperties": False,
                },
                {
                    "title": "manual input",
                    "type": "object",
                    "properties": {},
                    "required": [],
                    "additionalProperties": False,
                },
            ]
        },
    },
    "required": ["action", "input"],
    "additionalProperties": False,
}


def get_description(lang: str = "en") -> str:
    return _DESCRIPTION


def get_schema(lang: str = "en") -> dict:
    return _SCHEMA


def setup(agent: "BaseAgent", **_ignored) -> None:
    """Set up the mcp capability.

    The capability is pure presentation: it reads the registry from disk and
    renders it into the system prompt. Decompression of init.json's addons:
    field happens in the Agent initializer via
    ``lingtai.services.mcp_registry.decompress_addons()`` before setup is called.
    """
    _reconcile(agent)

    def handle_mcp(args: dict) -> dict:
        # Settings are evidence only.  Read them before inspecting or dispatching
        # the call so every path (including malformed and unknown calls) reports
        # the fresh Agent-owned placeholder snapshot.
        snapshot = read_settings(agent, "mcp")
        diagnostic = current_setting(snapshot, "mcp")

        def with_setting(result: dict) -> dict:
            result["current_setting"] = diagnostic
            return result

        def malformed(message: str) -> dict:
            return with_setting({"status": "error", "message": message})

        if not isinstance(args, Mapping):
            return malformed("mcp arguments must be an object")

        allowed = {"action", "input", "reasoning", "_reasoning"}
        if any(key not in allowed for key in args):
            return malformed(
                "mcp accepts only root action, input, reasoning, and _reasoning"
            )
        if "action" not in args or "input" not in args:
            return malformed("mcp requires root action and input")
        if not isinstance(args["input"], Mapping):
            return malformed("mcp input must be an object")

        # Unwrap exactly once at the normalization boundary.  The two public
        # actions have no payload, so selected input must be an empty mapping.
        action_input = dict(args["input"])
        if action_input:
            return malformed("mcp input must be an empty object")

        result = dispatch_action(
            {"action": args["action"], "input": action_input},
            {
                "info": lambda _args: _reconcile(agent),
                "manual": lambda _args: _manual(agent),
            },
            unknown=lambda action: {
                "status": "error",
                "message": f"unknown action: {action!r}, only 'info' or 'manual' is supported",
            },
        )
        return with_setting(result)

    agent.add_tool(
        "mcp",
        schema=get_schema(),
        handler=handle_mcp,
        description=get_description(),
        glossary_package=__package__,
    )
