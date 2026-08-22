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

Packaging: this directory is an **Agent Plugins v1.0.0** package. ``plugin.json``
beside this module is the manifest the kernel's own plugin reader validates, and
the manual is an owned skill at ``skills/mcp-manual/`` rather than a bare
``manual/`` directory convention — see ``lingtai/tools/_plugin.py`` and the
:data:`~lingtai.tools.mcp.plugin.MCP_TOOL_PLUGIN` descriptor, which is the single
source of the family's name, its action list, and the mount name the reserved
``manual`` child reads from. Packaging is presentation-layer only: the package
ships no ``mcp.json``, so nothing about it registers, activates, or launches an
MCP server.

Ownership: this module is the agent-callable *tool* slice only. The registry
machinery it renders (validation, JSONL I/O, catalog load, identity projection,
addon decompression, XML build) is a service and lives at
``lingtai/services/mcp_registry.py``; it is imported lazily inside ``setup`` and
the handlers, per the ``lingtai.tools → lingtai`` lazy-back-edge rule.

Usage: ``Agent(capabilities=["mcp"])`` or via init.json.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Mapping

from ..tool_family import ChildTool
from ..tool_family.manual import MANUAL_INPUT_SCHEMA
from .plugin import MCP_DECLARED_ACTIONS, MCP_TOOL_PLUGIN

if TYPE_CHECKING:
    from ..tool_family import ToolFamily
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

_DESCRIPTION = (
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
)

# Both actions are signpost-only reads that take no arguments at all, so both
# children share the one canonical strict-empty ``input`` — the same literal
# the generic ``manual`` child registers, reused rather than hand-copied so the
# schema-only and dispatching families cannot advertise different shapes.
# ``ToolFamily.build_schema`` deep-copies per child, and dispatch reads only
# ``properties``, so one shared object is safe.
_EMPTY_INPUT: dict[str, Any] = MANUAL_INPUT_SCHEMA

_ACTION_DESCRIPTION = (
    "info: signpost-only action; re-reads the registry and returns "
    "a runtime health snapshot (registry contents, problems, registry path) "
    "without the manual body. manual: return only the mcp-manual skill body. "
    "Neither action mutates MCP configuration."
)


def _build_family(agent: "BaseAgent | None") -> "ToolFamily":
    """Build the two-child ``mcp`` family; the registry is declared exactly once.

    Composition is the plugin's: :data:`~lingtai.tools.mcp.plugin.MCP_TOOL_PLUGIN`
    owns the family name and appends the reserved ``manual`` child bound to the
    owned ``mcp-manual`` skill's mount name, so this module declares only mcp's
    *own* action. Declaring ``manual`` here would raise ``BuiltinToolPluginError``
    rather than quietly shipping a manual pointing somewhere else.

    With an ``agent``, children are bound to real handlers for dispatch. With
    ``None``, the module-level schema-only family is built: its handlers raise
    if ever called, and constructing it at import time proves the fixed
    registry has no duplicate or reserved-name collision (``ToolFamilyError``
    raises here rather than shipping silently). Both paths declare the same
    ordered children, so the composed schema and the dispatching family can
    never drift apart.

    The plugin registers its ``manual`` child directly and unwrapped:
    ``ToolFamily.handle()`` must dispatch that child's own canonical
    MCP-compatible result verbatim (no double wrap). mcp's flat public shape is
    reconstructed from it strictly *after* dispatch, in ``handle_mcp`` — never
    inside a registered child.
    """
    if agent is None:
        def _unused(_input: Mapping[str, Any]) -> dict[str, Any]:
            raise AssertionError("the module-level schema-only ToolFamily never dispatches")

        info_handler: Any = _unused
    else:
        info_handler = lambda _input: _reconcile(agent)  # noqa: E731
    # Keyed by the plugin's declared action list, so the enum order the schema
    # advertises and the children that dispatch it come from one tuple; an
    # action declared without a handler raises here rather than at call time.
    handlers: dict[str, Any] = {"info": info_handler}
    return MCP_TOOL_PLUGIN.build_family(
        [
            ChildTool(name, _EMPTY_INPUT, handlers[name], title=f"{name} input")
            for name in MCP_DECLARED_ACTIONS
        ],
        agent,
    )


_FAMILY = _build_family(None)


def get_description(lang: str = "en") -> str:
    return _DESCRIPTION


def get_schema(lang: str = "en") -> dict:
    # Composed by the generic ToolFamily infra from each child's own canonical
    # ``input_schema``. The public action enum stays exactly ``["info",
    # "manual"]``; the pre-migration hand-written action description is
    # preserved verbatim so the signpost promise the model reads is unchanged.
    schema = _FAMILY.build_schema()
    schema["properties"]["action"]["description"] = _ACTION_DESCRIPTION
    return schema


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
        # ``child_names``, a tuple, which compares by ``==`` and never hashes,
        # so an unhashable value simply does not match — whereas
        # ``ToolFamily.handle``'s ``action not in self._children`` dict lookup
        # would raise ``TypeError`` on it. That is precisely why this routing
        # exists ahead of the delegation below.
        action = args.get("action", "") if isinstance(args, Mapping) else ""
        if action not in family.child_names:
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
