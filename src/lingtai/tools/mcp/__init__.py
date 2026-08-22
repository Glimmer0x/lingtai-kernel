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
demand. Both are action children of one LTP v2 ``ToolFamily`` (see
``lingtai/tools/CONTRACT.md`` "Envelope"): the public tool name stays ``mcp`` and
the public action values stay ``info``/``manual``, now carried in the canonical
``action`` + ``input`` + ``reasoning`` + ``summarize`` envelope with a strict
empty ``input`` per action. Neither action's observable result changed.

Ownership: this module is the agent-callable *tool* slice only. The registry
machinery it renders (validation, JSONL I/O, catalog load, identity projection,
addon decompression, XML build) is a service and lives at
``lingtai/services/mcp_registry.py``; it is imported lazily inside ``setup`` and
the handlers, per the ``lingtai.tools → lingtai`` lazy-back-edge rule.

Usage: ``Agent(capabilities=["mcp"])`` or via init.json.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Mapping

from ..tool_family import ChildTool, ToolFamily
from .plugin import MCP_ACTIONS, MCP_INPUT_SCHEMAS, MCP_PLUGIN

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


def _flatten_manual_result(mcp_result: dict) -> dict:
    """Adapt the canonical ``manual`` child result to mcp's public flat shape.

    ``ToolFamily.handle()`` has already dispatched to the registered ``manual``
    child (``build_manual_child``) and returned its canonical result *verbatim*
    (no double wrap) — full body at ``content[0].text``, host-local path at
    ``structuredContent.manual_path``, plus the loader's truthful
    ``status``/``error`` facts. mcp's own public result shape predates that
    generic contract and must stay exactly ``status``/``mcp_manual``/
    ``manual_path`` (note the tool-specific body key), so this Host-owned
    adapter runs strictly *after* dispatch — never inside a registered child,
    and never on the ``info`` path.
    """
    flat = {
        "status": mcp_result.get("status", "ok"),
        "mcp_manual": mcp_result["content"][0]["text"],
        "manual_path": mcp_result["structuredContent"]["manual_path"],
    }
    if "error" in mcp_result:
        flat["error"] = mcp_result["error"]
    return flat


# ---------------------------------------------------------------------------
# Tool surface
# ---------------------------------------------------------------------------
#
# The package-local ``MCP_PLUGIN`` owns mcp's fixed model-facing identity:
# description, public action order, strict-empty action schemas, and the
# bundled manual child.  This module keeps only the Host-facing reconciliation
# and legacy result adaptation that require an agent instance.


def _build_family(agent: "BaseAgent | None") -> ToolFamily:
    """Build MCP's agent-bound or schema-only family from its local descriptor.

    The descriptor owns the fixed public action order, both strict-empty input
    declarations, and the reserved package-manual child. This adapter binds
    only ``info`` to the Host-owned registry projection when an agent exists.
    """
    if agent is None:
        def _unused(_input: Mapping[str, Any]) -> dict[str, Any]:
            raise AssertionError("the module-level schema-only ToolFamily never dispatches")

        info_handler: Any = _unused
    else:
        info_handler = lambda _input: _reconcile(agent)  # noqa: E731
    return MCP_PLUGIN.build_family([
        ChildTool("info", MCP_INPUT_SCHEMAS["info"], info_handler, title="info input"),
    ])


_FAMILY = _build_family(None)


def get_description(lang: str = "en") -> str:
    return MCP_PLUGIN.description


def get_schema(lang: str = "en") -> dict:
    # The descriptor owns the fixed action signpost; ToolFamily composes the
    # same child schemas that the agent-bound family validates during dispatch.
    return MCP_PLUGIN.build_schema(_FAMILY)


def setup(agent: "BaseAgent", **_ignored) -> None:
    """Set up the mcp capability.

    The capability is pure presentation: it reads the registry from disk and
    renders it into the system prompt. Decompression of init.json's addons:
    field happens in the Agent initializer via
    ``lingtai.services.mcp_registry.decompress_addons()`` before setup is called.
    """
    _reconcile(agent)

    family = _build_family(agent)

    def handle_mcp(args: dict) -> dict:
        # The generic ``ToolFamily`` dispatcher validates ``action``,
        # type-checks and strips root ``summarize``, rejects unknown root
        # fields, and rejects any ``input`` key outside the selected action's
        # own declared schema — both actions declare a strict empty input, so
        # any extra input field fails here, before ``_reconcile`` re-reads the
        # registry or the manual child touches the filesystem.
        #
        # mcp's exact pre-migration unknown-action envelope is preserved here,
        # in the Host layer, rather than by changing the generic dispatcher's
        # own canonical error shape. Two pre-migration facts the generic
        # dispatcher does not reproduce on its own are restored before
        # delegating, both proven by ``test_mcp_show_unknown_action_returns_error``:
        # a missing ``action`` key renders the empty-string default (not
        # ``None``), and invalid JSON can make ``action`` unhashable (``[]`` /
        # ``{}``, issue #513's explicit blocker). Membership is tested against
        # the descriptor's ``MCP_ACTIONS`` tuple, which compares by ``==`` and
        # never hashes, so an unhashable value simply does not match — whereas
        # ``ToolFamily.handle``'s ``action not in self._children`` dict lookup
        # would raise ``TypeError`` on it. That is precisely why this routing
        # exists ahead of the delegation below.
        action = args.get("action", "") if isinstance(args, Mapping) else ""
        if action not in MCP_ACTIONS:
            return {
                "status": "error",
                "message": f"unknown action: {action!r}, only 'info' or 'manual' is supported",
            }
        result = family.handle(args)
        if action == "manual" and "content" in result:
            return _flatten_manual_result(result)
        return result

    agent.add_tool(
        "mcp",
        schema=get_schema(),
        handler=handle_mcp,
        description=get_description(),
        glossary_package=__package__,
    )
