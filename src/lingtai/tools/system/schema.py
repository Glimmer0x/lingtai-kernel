"""Public schema and description for the ``system`` intrinsic."""
from __future__ import annotations


_ACTIONS = [
    "refresh", "sleep", "lull", "interrupt", "suspend", "cpr", "clear",
    "nirvana", "presets", "summarize", "manual",
]


def get_description(lang: str = "en") -> str:
    return (
        "Runtime inspection, lifecycle control, synchronization, and inter-agent "
        "management. The public shape is system(action=..., input={...}); every "
        "action has its own strict input object. Self-actions (no permissions "
        "needed): sleep, refresh, summarize, manual, presets. Karma actions "
        "(require admin.karma=True): lull, interrupt, suspend, cpr, clear. Nirvana "
        "requires admin.karma=True and admin.nirvana=True. Notification verbs do "
        "not live here; use the standalone notification tool. Call "
        "system(action='manual', input={}) for the installed system-manual skill."
    )


def _empty_input(description: str) -> dict:
    return {
        "type": "object",
        "properties": {},
        "required": [],
        "additionalProperties": False,
        "description": description,
    }


def _string(name: str, description: str, *, min_length: int | None = None) -> dict:
    result = {"type": "string", "description": description}
    if min_length is not None:
        result["minLength"] = min_length
    return result


def _bool(name: str, description: str) -> dict:
    return {"type": "boolean", "description": description}


def _object_input(properties: dict, description: str, *, required: tuple[str, ...] = ()) -> dict:
    return {
        "type": "object",
        "properties": properties,
        "required": list(required),
        "additionalProperties": False,
        "description": description,
    }


def _input_branch(action: str, input_schema: dict) -> dict:
    """Name one closed action-specific input branch for provider schemas."""
    branch = dict(input_schema)
    branch["title"] = f"{action} input"
    return branch


def _summarize_input() -> dict:
    item = {
        "type": "object",
        "properties": {
            "tool_call_id": _string("tool_call_id", "Prior tool-result block id.", min_length=1),
            "summary": _string("summary", "Agent-authored compact replacement text."),
        },
        "required": ["tool_call_id", "summary"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": item,
                "minItems": 1,
                "description": "One or more prior tool-result blocks to summarize.",
            },
            "rebuild": _bool(
                "rebuild",
                "Request a provider-context rebuild after recording the summaries.",
            ),
        },
        "required": [],
        "additionalProperties": False,
        "anyOf": [
            {"required": ["items"]},
            {
                "properties": {
                    "rebuild": {
                        "enum": [True],
                        "description": "Rebuild pending summaries.",
                    },
                },
                "required": ["rebuild"],
            },
        ],
        "description": (
            "Record agent-authored summaries. Use items, or pass rebuild=true "
            "alone for a pure rebuild of already-pending summaries."
        ),
    }


def get_schema(lang: str = "en") -> dict:
    """Return the raw public schema; reasoning is injected by BaseAgent only."""
    reason = _string("reason", "Reason for the requested operation.")
    address = _string("address", "Target agent address (working-directory path).", min_length=1)
    refresh = _object_input(
        {
            "reason": reason,
            "preset": _string("preset", "Optional authorized preset to activate before refresh."),
            "revert_preset": _bool("revert_preset", "Return to the configured default preset."),
        },
        "Refresh from init.json; optional preset selection is handled by refresh.",
    )
    sleep = _object_input(
        {"reason": reason, "force": _bool("force", "Sleep despite pending notifications.")},
        "Put this agent to sleep.",
    )
    target = _object_input(
        {"address": address}, "Target another agent.", required=("address",)
    )
    clear = _object_input(
        {"address": address, "reason": reason},
        "Force a full molt on another agent.",
        required=("address",),
    )
    branches = [
        _input_branch("refresh", refresh),
        _input_branch("sleep", sleep),
        _input_branch("lull", target),
        _input_branch("interrupt", target),
        _input_branch("suspend", target),
        _input_branch("cpr", target),
        _input_branch("clear", clear),
        _input_branch("nirvana", target),
        _input_branch("presets", _empty_input("List available presets.")),
        _input_branch("summarize", _summarize_input()),
        _input_branch("manual", _empty_input("Return the installed system manual; read-only.")),
    ]
    return {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": _ACTIONS,
                "description": "The system operation to perform.",
            },
            "input": {
                "description": "Action-specific input; see the selected action branch.",
                "anyOf": branches,
            },
        },
        "required": ["action", "input"],
        "additionalProperties": False,
    }
