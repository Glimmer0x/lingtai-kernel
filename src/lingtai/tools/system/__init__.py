"""System intrinsic — runtime, lifecycle, and synchronization.

Actions (voluntary, agent-callable):
    refresh   — stop, reload MCP servers and config from working dir, restart
    sleep     — self only, go to sleep (no karma needed)
    lull      — put another agent to sleep (requires karma)
    suspend   — suspend another agent (requires karma)
    cpr       — resuscitate a suspended agent (requires karma)
    interrupt — interrupt a running agent's current turn (requires karma)
    clear     — force a full molt on another agent (requires karma)
    nirvana   — permanently destroy an agent's working directory (requires nirvana)
    presets   — list available presets in the agent's library
    manual    — return the installed system-manual skill without mutation
    summarize — record an agent-authored compact replacement for a prior
                tool-result block in runtime history. Pick targets from
                ``_meta.agent_meta.agent_state.current_tool_result_chars.top_results``.
                (Legacy: a successful summarize of a ``large_tool_result``
                tool_call_id still auto-clears any leftover reminder.)

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
    summarize.py     — _summarize() function, SUMMARIZE_MARKER.
    schema.py        — get_description(), get_schema().
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .._settings import SettingsSnapshot, current_setting, read_settings

# --- Re-exports from sub-modules for backward compatibility ---

# Schema (tool registration)
from .schema import get_description, get_schema  # noqa: F401
from .._manual import load_installed_manual

# Summarize — agent-authored context summarization
from .summarize import _summarize, SUMMARIZE_MARKER  # noqa: F401

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
# Module-level intrinsic protocol — handle()
# ---------------------------------------------------------------------------


_SYSTEM_ACTIONS = (
    "refresh", "sleep", "lull", "interrupt", "suspend", "cpr", "clear",
    "nirvana", "presets", "summarize", "manual",
)

# One public dispatcher.  The nested field allowlists are the runtime contract
# behind schema.py's closed action branches; they deliberately do not include
# any historical flat fields.
_ACTION_INPUT_FIELDS: dict[str, frozenset[str]] = {
    "refresh": frozenset({"reason", "preset", "revert_preset"}),
    "sleep": frozenset({"reason", "force"}),
    "lull": frozenset({"address"}),
    "interrupt": frozenset({"address"}),
    "suspend": frozenset({"address"}),
    "cpr": frozenset({"address"}),
    "clear": frozenset({"address", "reason"}),
    "nirvana": frozenset({"address"}),
    "presets": frozenset(),
    "summarize": frozenset({"items", "rebuild"}),
    "manual": frozenset(),
}
_REQUIRED_INPUT_FIELDS: dict[str, frozenset[str]] = {
    action: frozenset({"address"})
    for action in ("lull", "interrupt", "suspend", "cpr", "clear", "nirvana")
}


def _manual(agent, args: dict) -> dict:
    """Return the installed system manual without changing runtime state."""
    return load_installed_manual(agent, "system-manual")


_HANDLERS = {
    "refresh": _refresh,
    "sleep": _sleep,
    "lull": _lull,
    "suspend": _suspend,
    "cpr": _cpr,
    "interrupt": _interrupt,
    "clear": _clear,
    "nirvana": _nirvana,
    "presets": _presets,
    "summarize": _summarize,
    "manual": _manual,
}


def _setting_evidence(agent) -> dict[str, Any]:
    """Read the Agent-owned no-op settings snapshot once for this call."""
    try:
        snapshot = read_settings(agent, "system")
    except Exception as exc:  # defensive boundary for minimal/fake Agent seams
        snapshot = SettingsSnapshot(
            "settings_error",
            "error",
            None,
            f"settings reader failed ({type(exc).__name__})",
        )
    try:
        return current_setting(snapshot, "system")
    except Exception as exc:  # keep every result bounded even on a broken seam
        return {
            "configurable": False,
            "placeholder": "no-op",
            "source": "settings_error",
            "settings_revision": "error",
            "settings_hash": None,
            "settings_error": f"settings diagnostic failed ({type(exc).__name__})",
            "change_hint": "Edit settings/system.json; changes never change system behavior.",
        }


def _result_with_setting(result: Mapping[str, Any], setting: dict[str, Any]) -> dict[str, Any]:
    """Attach fresh settings evidence without allowing handlers to spoof it."""
    rendered = dict(result)
    rendered["current_setting"] = setting
    return rendered


def _error(message: str, setting: dict[str, Any], *, action: str | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {"status": "error", "message": message}
    if action is not None:
        result["action"] = action
    return _result_with_setting(result, setting)


def _require_string(value: Any, field: str, *, nonempty: bool = False) -> None:
    if not isinstance(value, str) or (nonempty and not value.strip()):
        qualifier = "non-empty " if nonempty else ""
        raise ValueError(f"{field} must be a {qualifier}string")


def _validate_summary_items(items: Any) -> None:
    if not isinstance(items, list) or not items:
        raise ValueError("summarize input 'items' must be a non-empty list")
    for item in items:
        if not isinstance(item, Mapping) or set(item) != {"tool_call_id", "summary"}:
            raise ValueError("each summarize item must contain only tool_call_id and summary")
        _require_string(item["tool_call_id"], "tool_call_id", nonempty=True)
        _require_string(item["summary"], "summary")


def _validate_input(action: str, action_input: Mapping[str, Any]) -> dict[str, Any]:
    """Validate one closed action branch and return a private flat call shape."""
    fields = set(action_input)
    allowed = _ACTION_INPUT_FIELDS[action]
    unknown = fields - allowed
    if unknown:
        raise ValueError("unsupported system input field")
    missing = _REQUIRED_INPUT_FIELDS.get(action, frozenset()) - fields
    if missing:
        raise ValueError("system action input is missing a required field")

    values = dict(action_input)
    for field in ("reason", "preset"):
        if field in values:
            _require_string(values[field], field)
    for field in ("force", "revert_preset", "rebuild"):
        if field in values and type(values[field]) is not bool:
            raise ValueError(f"{field} must be a boolean")
    if "address" in values:
        _require_string(values["address"], "address", nonempty=True)

    if action == "summarize":
        if set(values) == {"rebuild"}:
            if values["rebuild"] is not True:
                raise ValueError("rebuild-only summarize input requires rebuild=true")
        elif "items" in values:
            _validate_summary_items(values["items"])
        else:
            raise ValueError("summarize input requires items or rebuild=true")
    elif action in {"presets", "manual"} and values:
        # Kept explicit so an accidental allowlist expansion cannot make these
        # read-only branches accept options silently.
        raise ValueError("this system action accepts an empty input object")

    return {"action": action, **values}


def handle(agent, args: Mapping[str, Any] | None) -> dict:
    """Handle one canonical ``system(action=..., input={...})`` call.

    The provider-facing reasoning field is removed by ToolExecutor and arrives
    as ``_reasoning``.  ``_tc_id`` is likewise kernel metadata; neither is part
    of the public root schema.  Every validation, action, and exception path
    carries a fresh settings/current_setting diagnostic.
    """
    setting = _setting_evidence(agent)
    if not isinstance(args, Mapping):
        return _error("system arguments must be an object", setting)
    try:
        raw = dict(args)
    except Exception:
        return _error("system arguments are malformed", setting)
    unknown_root = set(raw) - {"action", "input", "reasoning", "_reasoning", "_tc_id"}
    if unknown_root:
        return _error("unsupported system argument", setting)
    if any(
        key in raw and not isinstance(raw[key], str)
        for key in ("reasoning", "_reasoning", "_tc_id")
    ):
        return _error("system reasoning metadata must be strings", setting)

    action = raw.get("action")
    if not isinstance(action, str) or action not in _SYSTEM_ACTIONS:
        label = action if isinstance(action, str) else type(action).__name__
        return _error(f"Unknown system action: {label}"[:240], setting)
    action_input = raw.get("input")
    if not isinstance(action_input, Mapping):
        return _error("input must be an object", setting, action=action)

    try:
        dispatch_args = _validate_input(action, action_input)
    except Exception:
        return _error("invalid system action input", setting, action=action)

    # Preserve kernel metadata for handlers that use it, without exposing any
    # public flat argument or allowing it to alter branch validation.
    for key in ("reasoning", "_reasoning", "_tc_id"):
        if key in raw:
            dispatch_args["_reasoning" if key == "reasoning" else key] = raw[key]
    try:
        result = _HANDLERS[action](agent, dispatch_args)
        if not isinstance(result, Mapping):
            return _error("system action returned an invalid result", setting, action=action)
        return _result_with_setting(result, setting)
    except Exception as exc:
        # Lifecycle handlers can touch external state. Keep their exception
        # seam bounded and never echo exception text, paths, or payloads.
        return _error(
            "system action failed safely",
            setting,
            action=action,
        ) | {"error_type": type(exc).__name__}
