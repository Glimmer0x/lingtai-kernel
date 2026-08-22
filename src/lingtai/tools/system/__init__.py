"""System intrinsic — runtime, lifecycle, and synchronization.

An LTP v2 family (``../CONTRACT.md``): one model-facing root ``system`` with
twelve fixed canonical action children, each owning its own strict ``input``
object. Every retained action value, its semantics, receipts, privilege gates,
and errors are exactly what they were. Children never consume model tool slots.

Actions (voluntary, agent-callable):
    refresh       — stop, reload MCP servers and config from working dir, restart
    sleep         — self only, go to sleep (no karma needed)
    lull          — put another agent to sleep (requires karma)
    suspend       — suspend another agent (requires karma)
    cpr           — resuscitate a suspended agent (requires karma)
    interrupt     — interrupt a running agent's current turn (requires karma)
    clear         — force a full molt on another agent (requires karma)
    nirvana       — permanently destroy an agent's working directory (requires nirvana)
    presets       — list available presets in the agent's library
    name_set      — set the agent's true name (真名), once and immutable
    name_nickname — set/change the agent's display name (别名), mutable
    manual        — return the installed system-manual skill without mutation

Two ownership moves happened when the ``psyche`` family was dissolved:

* ``name_set``/``name_nickname`` arrived here from ``psyche``. Naming is
  runtime identity state, which is what this family owns. They update live
  in-memory identity, persist ``.agent.json``, and rewrite the protected prompt
  ``identity`` section — they are NOT raw init/config editing, and NOT the
  physical agent address/workdir rename (an operator migration workflow
  documented in ``system-manual``, unchanged and out of scope here).
* The public ``summarize`` action LEFT for ``context``. Context hygiene is now
  ``context(action='summarize')`` (record-only) and
  ``context(action='rebuild')`` (full prompt reconstruction, summary application,
  then provider replay), where the explicit action replaced the old internal
  mode discriminator. ``system`` exposes no ``summarize`` action and no
  compatibility alias; ``summarize.py`` remains here only as the private
  engine those actions call.

Notification verbs (``check``/``dismiss_channel``/``dismiss_event``/
``dismiss_ref``) are **not** on ``system`` — they live exclusively on the
standalone ``notification`` tool.  ``system`` no longer exposes any
notification or dismiss compatibility alias.  The kernel still *synthesizes*
a notification tool-call pair on the agent's behalf when changes arrive during
IDLE/ASLEEP states (delivery plumbing, not an agent-callable action); the agent
reads/clears via the ``notification`` tool.

Identity and runtime state surface via other channels:
    - identity prompt section — every turn, cached prefix
    - per-result immutable `_meta.tool_meta` plus complete current final-carrier `_meta.agent_meta` on eligible tool results
    - `.status.json` — written by the kernel; read with read({".status.json"})
      when the agent wants the deep dive

Sub-modules:
    preset.py        — _preset_ref_in(), _check_context_fits(), _refresh(), _presets().
    karma.py         — _KARMA_ACTIONS, _NIRVANA_ACTIONS, _check_karma_gate(),
                       _sleep(), _lull(), _suspend(), _cpr(), _interrupt(),
                       _clear(), _nirvana().
    name.py          — _name_set(), _name_nickname().
    summarize.py     — _summarize() engine, SUMMARIZE_MARKER. Private: the
                       public actions that call it live on ``context``.
    schema.py        — ACTION_ORDER, INPUT_SCHEMAS, get_description().

``get_schema()`` is composed here from :data:`~.schema.INPUT_SCHEMAS` by the
generic ``ToolFamily`` infra rather than hand-assembled, so the advertised and
the validated shapes are generated from one registry and cannot drift.
"""
from __future__ import annotations

from typing import Any, Mapping

# --- Re-exports from sub-modules for backward compatibility ---

# Schema data (tool registration). ``get_schema`` is composed below from
# ``INPUT_SCHEMAS``; ``schema.py`` deliberately defines no second one.
from .schema import (  # noqa: F401
    ACTION_ENUM_DESCRIPTION,
    ACTION_ORDER,
    INPUT_SCHEMAS,
)
from .descriptor import SYSTEM_TOOL_DESCRIPTOR
# Historical import surface; the descriptor-backed manual child still delegates
# to this shared Host-owned loader through ``build_manual_child``.
from .._manual import load_installed_manual as load_installed_manual  # noqa: F401
from ..tool_family import ChildTool, ToolFamily
from ..tool_family.manual import build_manual_child

# Summarize — the agent-authored context-summarization ENGINE. This module
# stays here, but ``system`` no longer exposes a public ``summarize`` action:
# that public ownership moved to ``context(action='summarize'|'rebuild')``,
# which imports ``_summarize`` as its private engine. These names remain
# importable because the kernel and adapters use ``SUMMARIZE_MARKER`` and
# ``mark_pending_summaries_done`` for the forced-rebuild path; they are an
# internal runtime interface, NOT a model-visible compatibility alias.
from .summarize import _summarize, SUMMARIZE_MARKER  # noqa: F401

# Name — the agent's true name and nickname, moved here from the dissolved
# ``psyche`` family.
from .name import _name_set, _name_nickname  # noqa: F401

# Notification submission — the canonical helper any producer (intrinsic
# or in-process MCP) can call to surface a notification to the agent.
# Re-exported here for back-compat: ``system`` historically owned the
# producer-facing publish entry point, and many in-process producers still
# import ``publish_notification`` / ``clear_notification`` from here.  The
# agent-facing notification *verbs* (check/dismiss) now live exclusively on the
# standalone ``notification`` tool; ``system`` exposes none of them.  The
# functions live in ``lingtai.kernel.notifications`` (single source of truth,
# accessible to non-intrinsic call sites and external producers that import the
# module directly).
from lingtai.kernel.notifications import (  # noqa: F401
    submit as publish_notification,
    clear as clear_notification,
)

# Preset
from .preset import _preset_ref_in, _check_context_fits, _refresh, _presets  # noqa: F401

# Karma
from .karma import (  # noqa: F401
    _KARMA_ACTIONS,
    _NIRVANA_ACTIONS,
    _check_karma_gate,
    _sleep,
    _lull,
    _suspend,
    _cpr,
    _interrupt,
    _clear,
    _nirvana,
)


# ---------------------------------------------------------------------------
# Module-level intrinsic protocol — family composition and handle()
# ---------------------------------------------------------------------------

# The one canonical action -> handler registry. The package-local descriptor
# supplies the public action order and installed-manual skill name; ``manual``
# is absent here because ``build_manual_child`` owns that child's schema and
# handler. Each handler keeps its historical
# ``(agent, args)`` signature and its module home, so this migration moves no
# lifecycle, preset, or summarization logic.
_ACTION_HANDLERS = {
    "refresh": _refresh,
    "sleep": _sleep,
    "lull": _lull,
    "interrupt": _interrupt,
    "suspend": _suspend,
    "cpr": _cpr,
    "clear": _clear,
    "nirvana": _nirvana,
    "presets": _presets,
    "name_set": _name_set,
    "name_nickname": _name_nickname,
}


def _strip_nulls(action_input: Mapping[str, Any]) -> dict[str, Any]:
    """Drop explicit nulls so "absent" and "null" mean the same downstream.

    Strict provider schemas express an optional field as a REQUIRED nullable
    property, so the model must send ``{"preset": null, "revert_preset": null}``
    for a plain refresh. The pre-existing handlers key off
    ``args.get("preset")`` / ``args.get("reason", "")``, so stripping nulls here
    reproduces the pre-migration behavior exactly — including ``refresh``'s
    preset/revert conflict check and ``clear``'s fallback to the caller's own
    name — without touching those handlers.
    """
    return {key: value for key, value in action_input.items() if value is not None}


def _build_children(agent) -> list[ChildTool]:
    """Build the eleven children from the one canonical registry.

    ``agent`` may be ``None`` for the module-level schema-only family, whose
    children are never dispatched — only their schemas are read.

    Each non-manual child adapts the generic ``Callable[[Mapping], dict]``
    child contract to the handler's historical ``(agent, args)`` signature.
    The handler receives only its own validated ``input`` mapping: never
    ``action``, ``reasoning``, ``_reasoning``, or ``summarize``.
    """

    def _bind(action: str):
        handler = _ACTION_HANDLERS[action]

        def _dispatch(action_input: Mapping[str, Any]) -> dict:
            return handler(agent, _strip_nulls(action_input))

        return _dispatch

    children: list[ChildTool] = []
    for action_metadata in SYSTEM_TOOL_DESCRIPTOR.actions:
        action = action_metadata.name
        if action == "manual":
            children.append(
                build_manual_child(agent, SYSTEM_TOOL_DESCRIPTOR.manual_skill_name)
            )
        else:
            children.append(
                ChildTool(
                    action,
                    action_metadata.input_schema,
                    _bind(action),
                    title=f"{action} input",
                )
            )
    return children


# Composes the model-facing schema. Building it at import time is also the
# registry's duplicate/reserved-name collision check: a collision raises
# ``ToolFamilyError`` here rather than shipping silently. It never dispatches —
# ``system`` is an intrinsic *module*, not a per-Agent manager object, so there
# is no instance to hang a family off; ``handle()`` binds one to the passed
# agent per call from this same registry.
_FAMILY = ToolFamily(SYSTEM_TOOL_DESCRIPTOR.name, _build_children(None))


def _build_family(agent) -> ToolFamily:
    """Build the per-call dispatching family with handlers bound to *agent*.

    Construction is cheap (eleven ``ChildTool`` dataclasses and a name check),
    and building it per call keeps ``agent`` out of module state, which matters
    because one process may serve several agents.
    """
    return ToolFamily(SYSTEM_TOOL_DESCRIPTOR.name, _build_children(agent))


def get_description(lang: str = "en") -> str:
    """Return the descriptor-owned canonical model-facing system prose."""
    return SYSTEM_TOOL_DESCRIPTOR.description


def get_schema(lang: str = "en") -> dict[str, Any]:
    """Return the composed model-facing ``system`` family schema.

    Composed by the generic ``ToolFamily`` infra from each action's own
    canonical ``input_schema`` in :mod:`.schema`, rather than hand-assembled:
    root ``action`` + per-action ``input`` + required ``reasoning`` + optional
    ``summarize``, with a root ``allOf`` correlating each ``action`` const to
    that exact action's ``input`` shape. ``lang`` is accepted for source
    compatibility and ignored: schema prose is canonical English and
    language-independent.
    """
    schema = _FAMILY.build_schema()
    # The generic composer writes a neutral "Required operation within the
    # system family." description. System's own per-action prose (the karma /
    # nirvana privilege classes, the preset and summarize procedures, the
    # notification-tool pointer) is the model's only in-schema guide to *which*
    # action to pick, so it replaces that placeholder here rather than being
    # lost.
    schema["properties"]["action"]["description"] = (
        SYSTEM_TOOL_DESCRIPTOR.action_enum_description
    )
    return schema


def _adapt_manual_result(mcp_result: dict) -> dict:
    """Flatten the reserved ``manual`` child's canonical result to system's shape.

    The reserved child is registered unwrapped, so ``ToolFamily.handle()``
    returns its canonical ``content``/``structuredContent`` result verbatim.
    System's public manual result predates that generic contract and must stay
    the flat ``status``/``manual``/``manual_path`` shape (plus ``error`` when
    degraded), so this Host-owned adapter runs strictly *after* dispatch —
    never inside the child, and never as a second envelope around it.
    """
    flat: dict[str, Any] = {
        "status": mcp_result.get("status", "ok"),
        "manual": mcp_result["content"][0]["text"],
        "manual_path": mcp_result["structuredContent"]["manual_path"],
    }
    if "error" in mcp_result:
        flat["error"] = mcp_result["error"]
    return flat


def handle(agent, args: dict) -> dict:
    """Handle the ``system`` family root — validate the envelope, dispatch one action.

    Envelope validation and cross-action rejection belong to the generic
    dispatcher (``tool_family/CONTRACT.md``): it validates ``action`` before
    child lookup, type-checks and strips root ``summarize``, rejects unknown
    root fields, and rejects ``input`` keys outside the selected action's own
    declared schema *before* any handler runs. That last layer is what makes a
    cross-action smuggle such as ``action='sleep', input={'address': ...}``
    fail with no signal file written anywhere.

    This function owns only what is system-specific: dropping ``_tc_id``, and
    the two post-dispatch presentation adaptations below.

    Notification verbs (``check``/``dismiss_*``) and the old ``notification``/
    ``dismiss`` compatibility aliases are **not** handled here: they live
    exclusively on the standalone ``notification`` tool, and remain unknown
    actions.  ``summarize`` is likewise **not** a system action any more: it is
    a context-hygiene operation and moved to ``context(action='summarize')``
    with the applying half as ``context(action='rebuild')``.  No compatibility
    alias is kept, so the old ``system(action='summarize')`` is an unknown
    action here and fails loudly with the message below.
    """
    raw = dict(args or {})
    # ``base_agent._dispatch_tool`` injects the wire ``_tc_id`` into EVERY
    # intrinsic's args (capabilities like ``web`` never see it). It is kernel
    # transport metadata, not a public root field and not action input, so it
    # is dropped here before the envelope's closed-root check — system does not
    # consume it.
    raw.pop("_tc_id", None)

    action = raw.get("action")
    result = _build_family(agent).handle(raw)

    if action == "manual" and "content" in result:
        return _adapt_manual_result(result)
    if result.get("error_code") == "ACTION_REQUIRED":
        # Preserve system's pre-migration unknown-action error verbatim.
        return {"status": "error", "message": f"Unknown system action: {action}"}
    return result
