"""Psyche intrinsic — bare essentials of agent self.

Canonical contract: a closed root ``action`` enum selects a strict,
action-specific ``input`` object (the "object" dimension of the former
(object, action) matrix is folded into the action name itself — e.g.
``pad_edit``, ``lingtai_load`` — since ``load`` alone collides between
``lingtai`` and ``pad``). ``reasoning`` is injected/stripped by the kernel
(BaseAgent._build_tool_schemas / ToolExecutor._prepare_args); psyche's own
schema never declares it.

Actions:
    lingtai_update / lingtai_load — edit/load system/lingtai.md (self-authored
        identity → `character` section)
    pad_edit / pad_load / pad_append — edit/load system/pad.md (agent's
        working notes), append pinned files
    context_molt — molt (shed context, keep a briefing)
    name_set / name_nickname — set true name (once), set/clear nickname
    manual — return the installed psyche-manual skill

Sub-modules:
    _snapshots.py — Snapshot and summary persistence for the molt machinery.
    _pad.py       — Pad CRUD and append-file management.
    _lingtai.py   — Lingtai identity/character management.
    _molt.py      — Context molt core, name handlers, system-initiated molt.

Internal:
    boot — boot-time hook: load lingtai + pad into prompt, register post-molt
        reload. Called from base_agent.__init__ after intrinsics are wired.
"""
from __future__ import annotations

from typing import Any, Mapping

# --- Re-exports from sub-modules for backward compatibility ---

# Snapshots (used by consultation, inquiry, etc.)
from ._snapshots import SNAPSHOT_SCHEMA_VERSION, _write_molt_snapshot, _write_molt_summary  # noqa: F401

# Pad (used by boot, and cross-referenced by lingtai/append)
from ._pad import _pad_edit, _pad_load, _pad_append  # noqa: F401

# Lingtai (used by boot, and cross-referenced by pad)
from ._lingtai import _lingtai_update, _lingtai_load  # noqa: F401

# Molt (the public surface)
from ._molt import _context_molt, _name_set, _name_nickname, context_forget  # noqa: F401
from .._manual import load_installed_manual
from .._settings import current_setting, read_settings


# ---------------------------------------------------------------------------
# Schema / description
# ---------------------------------------------------------------------------

_TOOL_NAME = "psyche"


def get_description(lang: str = "en") -> str:
    return (
        "Identity, pad, name, and context management — lingtai: your 灵台 "
        "(character); psyche updates it immediately, while a nonempty "
        "configured lingtai value is authoritative on reconstruction and an "
        "absent or empty value enables self-evolution. pad: system-prompt "
        "sketchboard (system/pad.md) — plans, tasks, notes. context_molt: "
        "molt (凝蜕) — shed conversation, keep stores. name: set true name "
        "(once) or change nickname. Call psyche(action='manual', input={}) "
        "to return the installed psyche-manual skill."
    )


def get_schema(lang: str = "en") -> dict:
    return {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "lingtai_update",
                    "lingtai_load",
                    "pad_edit",
                    "pad_load",
                    "pad_append",
                    "context_molt",
                    "name_set",
                    "name_nickname",
                    "manual",
                ],
                "description": (
                    "Required operation. lingtai_update/lingtai_load: your 灵台 "
                    "— configured nonempty values force it on reconstruction, "
                    "absent/empty configuration lets it self-evolve. "
                    "pad_edit/pad_load/pad_append: your sketchboard in your "
                    "system prompt (system/pad.md); pad_append pins files as "
                    "read-only reference. context_molt: shed your "
                    "conversation context window, keep a briefing — requires "
                    "input.summary and input.session_journal_path; tend the "
                    "four stores BEFORE molting, see psyche-manual. "
                    "name_set: your true name (once). name_nickname: your "
                    "display name (mutable). manual: return the installed "
                    "psyche-manual skill."
                ),
            },
            "input": {
                "description": (
                    "Strict action-specific input; the selected action is "
                    "validated again at dispatch."
                ),
                "anyOf": [
                    {
                        "title": "lingtai_update input",
                        "type": "object",
                        "properties": {
                            "content": {
                                "type": "string",
                                "description": (
                                    "Your full identity (replaces entirely); "
                                    "empty string clears it."
                                ),
                            },
                        },
                        "required": ["content"],
                        "additionalProperties": False,
                    },
                    {
                        "title": "lingtai_load input",
                        "type": "object",
                        "properties": {},
                        "required": [],
                        "additionalProperties": False,
                    },
                    {
                        "title": "pad_edit input",
                        "type": "object",
                        "properties": {
                            "content": {
                                "type": ["string", "null"],
                                "description": (
                                    "Written as-is to pad.md; empty string "
                                    "clears it. Use null when supplying only "
                                    "files. At least one of content/files is "
                                    "required."
                                ),
                            },
                            "files": {
                                "type": ["array", "null"],
                                "items": {"type": "string"},
                                "description": (
                                    "File paths (text files only) imported "
                                    "inline into pad.md. Use null when "
                                    "supplying only content. At least one of "
                                    "content/files is required."
                                ),
                            },
                        },
                        "required": ["content", "files"],
                        "additionalProperties": False,
                    },
                    {
                        "title": "pad_load input",
                        "type": "object",
                        "properties": {},
                        "required": [],
                        "additionalProperties": False,
                    },
                    {
                        "title": "pad_append input",
                        "type": "object",
                        "properties": {
                            "files": {
                                "type": ["array", "null"],
                                "items": {"type": "string"},
                                "description": (
                                    "File paths (text files only). Pins files "
                                    "as read-only reference in your system "
                                    "prompt — re-read on every load including "
                                    "after molt. Pass [] to clear, or null to "
                                    "return the current list unchanged. Max "
                                    "100k tokens total. Paths relative to "
                                    "working directory. See psyche-manual."
                                ),
                            },
                        },
                        "required": ["files"],
                        "additionalProperties": False,
                    },
                    {
                        "title": "context_molt input",
                        "type": "object",
                        "properties": {
                            "summary": {
                                "type": "string",
                                "description": (
                                    "Your session retrospective (~10,000 "
                                    "tokens). Write as a record — what "
                                    "happened, what you learned, what "
                                    "remains. The four stores must be tended "
                                    "BEFORE molt. Saved to "
                                    "`system/summaries/molt_<count>_<ts>.md` "
                                    "and replayed to the next you. This is a "
                                    "business field, distinct from the "
                                    "unrelated executor-control "
                                    "`summary=true` a-priori result-"
                                    "summarization flag. See psyche-manual "
                                    "for full writing guidance."
                                ),
                            },
                            "session_journal_path": {
                                "type": "string",
                                "description": (
                                    "REQUIRED for context_molt. The path to "
                                    "the session-journal entry you wrote for "
                                    "the just-finished segment BEFORE "
                                    "molting: "
                                    "knowledge/session-journal/<entry>/"
                                    "KNOWLEDGE.md (a per-segment sub-entry, "
                                    "NOT the parent index). Must be inside "
                                    "your workdir, exist, be non-empty UTF-8, "
                                    "have valid YAML frontmatter with `name` "
                                    "and `description`, and identify itself "
                                    "as session knowledge via "
                                    "`type: session-journal` or "
                                    "`session_journal: true`. The molt is "
                                    "refused before any context is shed if "
                                    "this is missing or invalid. See "
                                    "psyche-manual §4."
                                ),
                            },
                            "keep_tool_calls": {
                                "type": ["array", "null"],
                                "items": {"type": "string"},
                                "description": (
                                    "Optional list of tool-call IDs to "
                                    "replay across the molt, in your chosen "
                                    "order. Use null for none. If any ID is "
                                    "not found, molt is refused. Keep short "
                                    "— durable stores are primary "
                                    "persistence. See psyche-manual."
                                ),
                            },
                            "keep_last": {
                                "type": ["integer", "null"],
                                "description": (
                                    "Optional (default: 20 when null). "
                                    "Number of recent conversation entries "
                                    "to replay into the fresh session. Pass "
                                    "0 to archive everything. Overlapping "
                                    "entries with keep_tool_calls are "
                                    "deduplicated."
                                ),
                            },
                        },
                        "required": [
                            "summary",
                            "session_journal_path",
                            "keep_tool_calls",
                            "keep_last",
                        ],
                        "additionalProperties": False,
                    },
                    {
                        "title": "name_set input",
                        "type": "object",
                        "properties": {
                            "content": {
                                "type": "string",
                                "description": "Your chosen true name.",
                            },
                        },
                        "required": ["content"],
                        "additionalProperties": False,
                    },
                    {
                        "title": "name_nickname input",
                        "type": "object",
                        "properties": {
                            "content": {
                                "type": "string",
                                "description": (
                                    "Your chosen nickname; empty string "
                                    "clears it."
                                ),
                            },
                        },
                        "required": ["content"],
                        "additionalProperties": False,
                    },
                    {
                        "title": "manual input",
                        "type": "object",
                        "properties": {},
                        "required": [],
                        "additionalProperties": False,
                    },
                ],
            },
        },
        "required": ["action", "input"],
        "additionalProperties": False,
    }


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

# Per-action closed input field set — mirrors the anyOf branches above.
_ACTION_INPUT_FIELDS: dict[str, set[str]] = {
    "lingtai_update": {"content"},
    "lingtai_load": set(),
    "pad_edit": {"content", "files"},
    "pad_load": set(),
    "pad_append": {"files"},
    "context_molt": {
        "summary",
        "session_journal_path",
        "keep_tool_calls",
        "keep_last",
    },
    "name_set": {"content"},
    "name_nickname": {"content"},
    "manual": set(),
}

# Explicit dispatch table, keyed by the flattened canonical action name.
_DISPATCH: dict[str, object] = {
    "lingtai_update": _lingtai_update,
    "lingtai_load": _lingtai_load,
    "pad_edit": _pad_edit,
    "pad_load": _pad_load,
    "pad_append": _pad_append,
    "context_molt": _context_molt,
    "name_set": _name_set,
    "name_nickname": _name_nickname,
}

# Root-level keys tolerated alongside action/input: the kernel-injected wire
# tool_use_id (base_agent._dispatch_tool) and the public/internal reasoning
# pair (ToolExecutor._prepare_args strips public `reasoning` into
# `_reasoning` before the handler runs; direct in-process callers may pass
# either).
_ROOT_TOLERATED = {"action", "input", "reasoning", "_reasoning", "_tc_id"}


def _current_setting(agent: Any) -> dict[str, Any]:
    """Fresh, copy-safe, no-op settings snapshot captured at call start."""
    snapshot = read_settings(agent, _TOOL_NAME)
    return current_setting(snapshot, _TOOL_NAME)


def _attach_setting(
    result: Mapping[str, Any], setting: Mapping[str, Any]
) -> dict[str, Any]:
    copied = dict(result)
    copied["current_setting"] = dict(setting)
    return copied


def _error(message: str, setting: Mapping[str, Any]) -> dict[str, Any]:
    return {"error": message, "current_setting": dict(setting)}


def _is_string_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _validate_action_input(action: str, values: Mapping[str, Any]) -> str | None:
    """Repeat the schema's consequential type checks before side effects."""
    if action in {"lingtai_update", "name_set", "name_nickname"}:
        if not isinstance(values["content"], str):
            return f"input.content for {action} must be a string."
        return None

    if action == "pad_edit":
        content = values["content"]
        files = values["files"]
        if content is not None and not isinstance(content, str):
            return "input.content for pad_edit must be a string or null."
        if files is not None and not _is_string_list(files):
            return "input.files for pad_edit must be an array of strings or null."
        if content is None and not files:
            return "pad_edit requires non-null content or at least one file."
        return None

    if action == "pad_append":
        files = values["files"]
        if files is not None and not _is_string_list(files):
            return "input.files for pad_append must be an array of strings or null."
        return None

    if action == "context_molt":
        if not isinstance(values["summary"], str):
            return "input.summary for context_molt must be a string."
        if not isinstance(values["session_journal_path"], str):
            return "input.session_journal_path for context_molt must be a string."
        keep_tool_calls = values["keep_tool_calls"]
        if keep_tool_calls is not None and not _is_string_list(keep_tool_calls):
            return (
                "input.keep_tool_calls for context_molt must be an array of "
                "strings or null."
            )
        keep_last = values["keep_last"]
        if keep_last is not None and (
            isinstance(keep_last, bool) or not isinstance(keep_last, int)
        ):
            return "input.keep_last for context_molt must be an integer or null."
        return None

    return None


def handle(agent, args: dict) -> dict:
    """Handle psyche tool — dispatch on the canonical (action, input) contract."""
    setting = _current_setting(agent)
    if args is None:
        raw: dict[Any, Any] = {}
    elif not isinstance(args, Mapping):
        return _error("psyche arguments must be an object.", setting)
    else:
        raw = dict(args)

    if any(not isinstance(key, str) for key in raw):
        return _error("psyche argument keys must be strings.", setting)

    action = raw.get("action")
    unknown_root = set(raw) - _ROOT_TOLERATED
    if unknown_root:
        return _error(
            f"Unsupported psyche argument(s): {', '.join(sorted(unknown_root))}.",
            setting,
        )

    if not isinstance(action, str) or action not in _ACTION_INPUT_FIELDS:
        valid = ", ".join(sorted(_ACTION_INPUT_FIELDS))
        return _error(
            f"Unknown action: {action!r}. Must be one of: {valid}.", setting
        )

    for passthrough in ("reasoning", "_reasoning", "_tc_id"):
        if passthrough in raw and not isinstance(raw[passthrough], str):
            return _error(f"{passthrough} must be a string.", setting)

    action_input = raw.get("input")
    if not isinstance(action_input, Mapping):
        return _error("input must be an object.", setting)
    action_args = dict(action_input)
    if any(not isinstance(key, str) for key in action_args):
        return _error("input field names must be strings.", setting)

    expected = _ACTION_INPUT_FIELDS[action]
    actual = set(action_args)
    unsupported_input = actual - expected
    if unsupported_input:
        return _error(
            f"Unsupported input field(s) for {action}: "
            f"{', '.join(sorted(unsupported_input))}.",
            setting,
        )
    missing_input = expected - actual
    if missing_input:
        return _error(
            f"Missing required input field(s) for {action}: "
            f"{', '.join(sorted(missing_input))}.",
            setting,
        )

    validation_error = _validate_action_input(action, action_args)
    if validation_error:
        return _error(validation_error, setting)

    # Strict schemas express semantic optionals as required nullable fields;
    # null means "not supplied" to the legacy behavior owners.
    dispatch_args = {key: value for key, value in action_args.items() if value is not None}
    for passthrough in ("reasoning", "_reasoning", "_tc_id"):
        if passthrough in raw:
            dispatch_args[passthrough] = raw[passthrough]

    if action == "manual":
        return _attach_setting(
            load_installed_manual(agent, "psyche-manual"), setting
        )

    handler = _DISPATCH.get(action)
    if handler is None:
        return _error(f"Internal: handler for {action!r} not found.", setting)
    result = handler(agent, dispatch_args)
    if not isinstance(result, Mapping):
        return _error(
            f"Internal: handler for {action!r} returned a non-object result.",
            setting,
        )
    return _attach_setting(result, setting)


# ---------------------------------------------------------------------------
# Boot hook
# ---------------------------------------------------------------------------


def boot(agent) -> None:
    """Boot-time hook: load lingtai + pad into the prompt, register post-molt
    reload. Called from base_agent.__init__ after intrinsics are wired."""
    _pad_load(agent, {})
    _lingtai_load(agent, {})
    if not hasattr(agent, "_post_molt_hooks"):
        agent._post_molt_hooks = []
    agent._post_molt_hooks.append(
        lambda: (_lingtai_load(agent, {}), _pad_load(agent, {}))
    )
