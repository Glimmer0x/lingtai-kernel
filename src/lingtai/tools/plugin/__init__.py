"""Plugin capability — Agent Plugins catalog and registration snapshot.

Symmetric to the ``mcp`` capability, and deliberately just as thin. What the
capability reports splits along one line, and that line is the design:

- **Declared → registered.** ``init.json`` ``manifest.plugins`` (canonical) and
  ``manifest.capabilities.plugin.paths`` (its alias, the key PR #1232 shipped)
  name plugin package directories. ``Agent`` registers them at boot — *before*
  capability setup, next to addon decompression — so the plugin's ``skills/``
  is composed into the skills catalog and its ``mcp.json`` servers hold
  ``mcp_registry.jsonl`` records stamped ``source="plugin:<name>"``.
- **Inherited → discovered only.** ``manifest.capabilities.skills.paths`` is
  still scanned, and plugins found there are still listed — but nothing of
  theirs is mounted. Dropping a directory into a skills path must never silently
  register a third party's MCP server; only an explicit declaration does that.

The capability itself remains **pure presentation**: it writes no file. It reads
the boot registration snapshot the Agent stored, re-scans the configured paths
for the catalog, and renders both into the protected ``plugin`` prompt section.
The one mutation point is ``services.plugin_registry.register_plugins``, which
runs at boot/refresh, not from any model-facing action — so ``info`` cannot mount
anything, and picking up a newly declared plugin is a ``system(action="refresh")``.

Registration is registry-level, exactly as ``addons:[]`` is: a plugin's MCP
server becomes registered and visible, never running. Activation still requires
an explicit ``init.json`` top-level ``mcp`` entry.

Tool surface: ``info`` returns the registration snapshot — every declared plugin
with what mounted, what was skipped and why — plus the discovery catalog and
per-path health, without the manual body; ``manual`` returns the plugin-manual
body on demand. Both are action children of one LTP v2 ``ToolFamily`` (see
``lingtai/tools/CONTRACT.md`` "Envelope"): the public tool name is ``plugin`` and
the public action values are ``info``/``manual``, carried in the canonical
``action`` + ``input`` + ``reasoning`` + ``summarize`` envelope with a strict
empty ``input`` per action.

Ownership: this module is the agent-callable *tool* slice only. The machinery it
renders (manifest validation, §4.1 path containment, skills/MCP component
discovery, registration, pruning, XML build) is a service and lives at
``lingtai/services/plugin_registry.py``; it is imported lazily inside ``setup``
and the handlers, per the ``lingtai.tools → lingtai`` lazy-back-edge rule.

Packaging: this directory is a **tool plugin** — a plugin-style package that
ships its handler code, its ``manual/SKILL.md``, and its capability declaration
together. ``plugin.py`` holds the descriptor
(:data:`~lingtai.tools.plugin.plugin.TOOL_PLUGIN`); this module declares only the
``info`` action and lets the descriptor append the reserved ``manual`` bound to
the packaged skill, and names its tool and error surface from the descriptor
rather than from repeated literals. That is the *tools*-layer sense of "plugin"
(``lingtai/tools/_plugin.py``) and it is emphatically **not** the Agent Plugins
v1.0.0 sense this tool reports. This package ships no ``plugin.json``, is never
scanned by ``read_plugins``, never appears in its own ``info`` snapshot, and owns
no ``source="plugin:plugin"`` record — the non-recursion that lets the reporter
be packaged without having to mount itself before it can report.

Usage: ``Agent(plugins=[...])`` or ``Agent(capabilities={"plugin": {"paths":
[...]}})``, or via init.json.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Mapping

from ..tool_family import ChildTool, ToolFamily
from ..tool_family.manual import MANUAL_INPUT_SCHEMA
from .plugin import PLUGIN_ACTIONS, TOOL_PLUGIN

if TYPE_CHECKING:
    from lingtai.kernel.base_agent import BaseAgent

PROVIDERS = {"providers": [], "default": "builtin"}


# ---------------------------------------------------------------------------
# Path collection
# ---------------------------------------------------------------------------

def _collect_paths(agent: "BaseAgent", paths: list[str] | None) -> list[str]:
    """Union the declared paths with the skills capability's, for **discovery**.

    Three sources, in order: this capability's own ``paths`` (the alias
    declaration key), every path the boot registration declared (the canonical
    ``manifest.plugins``, which does not otherwise reach this capability), and
    the skills capability's paths. Duplicates are dropped, so a directory named
    by more than one is scanned once.

    The discovery set is deliberately wider than the declaration set. A plugin
    bundles Agent Skills, so the directories an operator already points the
    skills capability at are the same directories plugins land in; inheriting
    them means a plugin dropped there is at least *visible* without a second
    declaration. It is not mounted — inherited paths never register anything,
    only ``manifest.plugins`` and its alias do. Including the declared paths here
    is what keeps a declared plugin's per-path health and scan problems visible
    in ``info`` even when it was declared through the canonical key alone.
    """
    ordered: list[str] = list(paths or [])
    snapshot = getattr(agent, "_plugin_registration", None) or {}
    ordered.extend(p for p in snapshot.get("declared", []) or [] if isinstance(p, str))
    for name, kwargs in getattr(agent, "_capabilities", []) or []:
        if name != "skills" or not isinstance(kwargs, Mapping):
            continue
        for raw in kwargs.get("paths", []) or []:
            if isinstance(raw, str):
                ordered.append(raw)
    seen: set[str] = set()
    return [p for p in ordered if not (p in seen or seen.add(p))]


# ---------------------------------------------------------------------------
# Reconciliation (shared by setup and the ``info`` action)
# ---------------------------------------------------------------------------

def _catalog_entry(record: dict) -> dict:
    """Build one ``discovered`` entry — the catalog facts, not the full record."""
    entry = {
        "name": record["name"],
        "version": record["version"],
        "summary": record["summary"],
        "skill_count": record["skill_count"],
        "mcp_server_count": record["mcp_server_count"],
        "source": record["source"],
    }
    if record.get("homepage"):
        entry["homepage"] = record["homepage"]
    return entry


def _skills_enabled(agent: "BaseAgent") -> bool:
    """Whether the skills capability is loaded on this agent.

    A declared plugin's ``skills/`` is composed into the skills catalog scan; if
    the capability is off there is no catalog to compose into, and the snapshot
    must say so rather than claim a mount that did not happen.
    """
    return any(name == "skills" for name, _ in getattr(agent, "_capabilities", []) or [])


def _registered_entries(agent: "BaseAgent", snapshot: dict) -> list[dict]:
    """Project the boot registration snapshot into the ``registered`` list."""
    skills_on = _skills_enabled(agent)
    entries: list[dict] = []
    for plugin in snapshot.get("plugins", []) or []:
        entry = dict(plugin)
        entry.pop("skill_paths", None)
        entry["skipped"] = list(plugin.get("skipped") or [])
        # Closed namespace: a plugin's skills live inside the plugin (readable
        # via file/read from <source>) and are listed in the plugins field as
        # <skill_names>; they are never composed into the vanilla skills
        # catalog. skills_mounted therefore means "visible as the plugin's own
        # skills", not "composed into the skills catalog".
        entry["skills_mounted"] = bool(plugin.get("skills")) and skills_on
        if plugin.get("skills") and not skills_on:
            entry["skipped"].append({
                "component": "skills/",
                "reason": (
                    "skills capability is not enabled on this agent, so the "
                    "plugin's skills are listed in the plugins field without a "
                    "skills-catalog composition"
                ),
            })
        entries.append(entry)
    return entries


def _reconcile(agent: "BaseAgent", paths: list[str] | None = None) -> dict:
    """Re-scan the configured paths, render the prompt, return the snapshot.

    Read-only. The registration snapshot is whatever ``Agent`` recorded when it
    ran ``register_plugins`` at boot/refresh; this function reports it, never
    re-runs it. Discovery is re-scanned live, so a plugin added to a configured
    directory shows up as ``discovered`` immediately — mounting it is a
    declaration in ``init.json`` plus ``system(action="refresh")``.
    """
    from lingtai.services.plugin_registry import _build_registry_xml, read_plugins

    snapshot = getattr(agent, "_plugin_registration", None) or {}
    registered = _registered_entries(agent, snapshot)
    registered_names = {entry["name"] for entry in registered}

    resolved_paths = _collect_paths(agent, paths)
    records, problems, report = read_plugins(agent._working_dir, resolved_paths)
    discovered = [
        _catalog_entry(r) for r in records if r["name"] not in registered_names
    ]

    xml = _build_registry_xml(registered, discovered)
    agent.update_system_prompt("plugin", xml, protected=True)

    return {
        "status": "ok",
        "declared": list(snapshot.get("declared", []) or []),
        "registered_count": len(registered),
        "registered": registered,
        "discovered_count": len(discovered),
        "discovered": discovered,
        "mcp_appended": list(snapshot.get("mcp_appended", []) or []),
        "mcp_pruned": list(snapshot.get("mcp_pruned", []) or []),
        "paths": report,
        "problems": problems,
    }


def _flatten_manual_result(plugin_result: dict) -> dict:
    """Adapt the canonical ``manual`` child result to plugin's flat public shape.

    ``ToolFamily.handle()`` has already dispatched to the registered ``manual``
    child (``build_manual_child``) and returned its canonical result *verbatim*
    (no double wrap) — full body at ``content[0].text``, host-local path at
    ``structuredContent.manual_path``, plus the loader's truthful
    ``status``/``error`` facts. This capability's public result keys its body
    ``plugin_manual`` (the tool-specific key ``mcp`` established with
    ``mcp_manual``), so this Host-owned adapter runs strictly *after* dispatch —
    never inside a registered child, and never on the ``info`` path.
    """
    flat = {
        "status": plugin_result.get("status", "ok"),
        "plugin_manual": plugin_result["content"][0]["text"],
        "manual_path": plugin_result["structuredContent"]["manual_path"],
    }
    if "error" in plugin_result:
        flat["error"] = plugin_result["error"]
    return flat


# ---------------------------------------------------------------------------
# Tool surface
# ---------------------------------------------------------------------------

_DESCRIPTION = (
    "READ-ONLY: this tool itself installs and runs nothing. `info` re-scans the "
    "configured plugin paths and returns the boot registration snapshot; "
    "`manual` returns the plugin-manual body. Neither action mounts, "
    "unmounts, or launches anything. "
    "Your per-agent Agent Plugins catalog (agent-plugins.org, v1.0.0). The "
    "<registered_plugin> section in your system prompt lists every visible "
    "plugin with a <mount> stamp. `registered` = declared in init.json "
    "manifest.plugins and mounted at boot: its skills are in your skills "
    "catalog and its mcp.json servers hold mcp_registry.jsonl records with "
    "source=\"plugin:<name>\" — registered but NOT running, so activation "
    "still needs an init.json top-level mcp entry. `discovered` = merely found "
    "on an inherited skills path: nothing mounted, skills absent from your "
    "catalog, MCP servers absent from mcp_registry.jsonl. Before using this "
    "tool (inspecting, authoring, installing, or uninstalling a plugin), read "
    "the `plugin-manual` skill — call `manual` to fetch its body (plugin.json "
    "contract, path containment, the registration and uninstall flow), and "
    "call `info` for the current snapshot including every skipped component "
    "and why; no exceptions. To install a plugin, add its directory to "
    "manifest.plugins in init.json and call system(action=\"refresh\"); to "
    "uninstall, remove it from that list and refresh."
)

# Both actions are flagpost-only reads that take no arguments at all, so both
# children share the one canonical strict-empty ``input`` — the same literal
# the generic ``manual`` child registers, reused rather than hand-copied so the
# schema-only and dispatching families cannot advertise different shapes.
# ``ToolFamily.build_schema`` deep-copies per child, and dispatch reads only
# ``properties``, so one shared object is safe.
_EMPTY_INPUT: dict[str, Any] = MANUAL_INPUT_SCHEMA

#: This capability's own declared-action lines. The reserved ``manual`` line is
#: appended by the tool plugin from the packaged skill's frontmatter (see
#: :meth:`~lingtai.tools._plugin.ToolPlugin.manual_action_description`), so the
#: skill name the schema advertises cannot drift from the skill that ships.
_DECLARED_ACTION_DESCRIPTION = (
    "info: read-only action; re-scans the configured plugin paths and returns "
    "the boot registration snapshot (registered plugins with what mounted and "
    "what was skipped and why, discovered-only plugins, per-path report, "
    "problems) without the manual body. Neither action registers or "
    "unregisters anything — mounting happens at boot from init.json "
    "manifest.plugins, so a newly declared plugin needs "
    "system(action=\"refresh\")."
)

_ACTION_DESCRIPTION = (
    f"{_DECLARED_ACTION_DESCRIPTION} {TOOL_PLUGIN.manual_action_description()}"
)

#: The unknown-action envelope's action list, rendered from the tool plugin's
#: own public action tuple rather than hand-copied, so adding an action cannot
#: leave the error message advertising a stale surface.
_SUPPORTED_ACTIONS = " or ".join(repr(action) for action in PLUGIN_ACTIONS)


def _build_family(agent: "BaseAgent | None", paths: list[str] | None = None) -> ToolFamily:
    """Build the two-child ``plugin`` family; the registry is declared exactly once.

    Composition runs through this package's own tool plugin
    (:data:`~lingtai.tools.plugin.plugin.TOOL_PLUGIN`): this function declares
    only ``info``, and the descriptor appends the reserved ``manual`` child bound
    to the skill the package ships. Declaring ``manual`` here — or rebinding it
    to other material — raises ``ToolPluginError`` at import rather than shipping
    a family whose manual points somewhere other than the packaged skill.

    With an ``agent``, children are bound to real handlers for dispatch. With
    ``None``, the module-level schema-only family is built: its handlers raise
    if ever called, and constructing it at import time proves the fixed
    registry has no duplicate or reserved-name collision (``ToolFamilyError``
    raises here rather than shipping silently). Both paths declare the same
    ordered children, so the composed schema and the dispatching family can
    never drift apart.

    The ``manual`` child the descriptor appends is registered directly,
    unwrapped: ``ToolFamily.handle()`` must dispatch its own canonical
    MCP-compatible result verbatim (no double wrap). This capability's flat
    public shape is reconstructed from that canonical result strictly *after*
    dispatch, in ``handle_plugin`` — never inside a registered child.
    """
    if agent is None:
        def _unused(_input: Mapping[str, Any]) -> dict[str, Any]:
            raise AssertionError("the module-level schema-only ToolFamily never dispatches")

        info_handler: Any = _unused
    else:
        info_handler = lambda _input: _reconcile(agent, paths)  # noqa: E731
    return TOOL_PLUGIN.build_family(
        [ChildTool("info", _EMPTY_INPUT, info_handler, title="info input")],
        agent=agent,
    )


_FAMILY = _build_family(None)


def get_description(lang: str = "en") -> str:
    return _DESCRIPTION


def get_schema(lang: str = "en") -> dict:
    # Composed by the generic ToolFamily infra from each child's own canonical
    # ``input_schema``. The public action enum is exactly ``PLUGIN_ACTIONS`` —
    # this package's one declared action plus the reserved ``manual`` the tool
    # plugin appends — the same two-action flagpost surface ``mcp`` exposes.
    schema = _FAMILY.build_schema()
    schema["properties"]["action"]["description"] = _ACTION_DESCRIPTION
    return schema


def setup(agent: "BaseAgent", paths: list[str] | None = None, **_ignored) -> None:
    """Set up the plugin capability.

    ``paths`` is the alias declaration list from ``init.json``
    ``manifest.capabilities.plugin.paths``; the canonical declaration key is the
    manifest-level ``manifest.plugins``, and the skills capability's own paths
    are inherited on top of both for *discovery* (see ``_collect_paths``).

    Setup itself writes nothing. Registration of the declared plugins already
    happened in ``Agent``, before capability setup, so by the time this runs the
    skills catalog and ``mcp_registry.jsonl`` are in their mounted state and this
    capability only has to report them.
    """
    resolved = list(paths) if paths else []
    _reconcile(agent, resolved)

    family = _build_family(agent, resolved)

    def handle_plugin(args: dict) -> dict:
        # The generic ``ToolFamily`` dispatcher validates ``action``,
        # type-checks and strips root ``summarize``, rejects unknown root
        # fields, and rejects any ``input`` key outside the selected action's
        # own declared schema — both actions declare a strict empty input, so
        # any extra input field fails here, before ``_reconcile`` re-scans the
        # plugin paths or the manual child touches the filesystem.
        #
        # The unknown-action envelope is rendered here, in the Host layer, for
        # the same two reasons ``mcp`` renders its own: a missing ``action`` key
        # must show the empty-string default (not ``None``), and invalid JSON
        # can make ``action`` unhashable (``[]`` / ``{}``, issue #513's explicit
        # blocker). Membership is tested against ``child_names``, a tuple, which
        # compares by ``==`` and never hashes, so an unhashable value simply
        # does not match — whereas ``ToolFamily.handle``'s ``action not in
        # self._children`` dict lookup would raise ``TypeError`` on it.
        action = args.get("action", "") if isinstance(args, Mapping) else ""
        if action not in family.child_names:
            return {
                "status": "error",
                "message": f"unknown action: {action!r}, only {_SUPPORTED_ACTIONS} is supported",
            }
        result = family.handle(args)
        if action == "manual" and "content" in result:
            return _flatten_manual_result(result)
        return result

    agent.add_tool(
        TOOL_PLUGIN.name,
        schema=get_schema(),
        handler=handle_plugin,
        description=get_description(),
        glossary_package=__package__,
    )
