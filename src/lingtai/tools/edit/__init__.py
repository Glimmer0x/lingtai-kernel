"""Edit capability — exact string replacement in a file.

Usage: Agent(capabilities=["edit"]) or capabilities=["file"]
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from .._file_paths import resolve_workdir_path
from .._manual import load_installed_manual
from .._settings import current_setting, read_settings

if TYPE_CHECKING:
    from lingtai.kernel.base_agent import BaseAgent


_ACTION_FIELDS = {
    "edit": ("file_path", "old_string", "new_string", "replace_all"),
    "manual": (),
}
_ALLOWED_ROOT_FIELDS = ("action", "input", "reasoning", "_reasoning")


def get_description(lang: str = "en") -> str:
    return (
        "Replace an exact string in a file with action='edit' and a nested input "
        "object. The edit input requires file_path, old_string, new_string, and "
        "replace_all (a boolean or null; null means false). Fails if old_string "
        "is not found or is ambiguous. Use action='manual' with input={} once "
        "to return the installed file-manual skill; after the manual result, "
        "continue the original edit instead of repeating manual."
    )


def get_schema(lang: str = "en") -> dict:
    """Return the raw closed action/input schema.

    ``BaseAgent`` adds the optional root ``reasoning`` property when it builds
    the model-facing schema. It is metadata, not an edit action input.
    """
    return {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["edit", "manual"],
                "description": "Required operation: edit a file or return the installed manual.",
            },
            "input": {
                "description": "Strict action-specific edit input.",
                "anyOf": [
                    {
                        "title": "edit input",
                        "type": "object",
                        "properties": {
                            "file_path": {
                                "type": "string",
                                "description": "Path to the existing file to edit.",
                            },
                            "old_string": {
                                "type": "string",
                                "description": "Exact text to find.",
                            },
                            "new_string": {
                                "type": "string",
                                "description": "Replacement text.",
                            },
                            "replace_all": {
                                "type": ["boolean", "null"],
                                "description": "Replace every match; null preserves the historical false default.",
                            },
                        },
                        # Strict providers require the semantic optional field to
                        # be present while nullable. Direct calls may omit it.
                        "required": ["file_path", "old_string", "new_string", "replace_all"],
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


def _with_setting(result: Mapping[str, Any], diagnostic: dict[str, Any]) -> dict[str, Any]:
    """Attach one fresh settings diagnostic to every public result."""
    value = dict(result)
    value["current_setting"] = diagnostic
    return value


def setup(agent: "BaseAgent") -> None:
    """Set up the edit capability on an agent."""

    def handle_edit(args: Any) -> dict:
        # This must remain the first operation for every call, including
        # malformed, unknown, manual, and failed edit calls. Settings are
        # evidence only and never select edit behavior.
        snapshot = read_settings(agent, "edit")
        diagnostic = current_setting(snapshot, "edit")

        def error(message: str) -> dict:
            return _with_setting({"status": "error", "message": message}, diagnostic)

        if not isinstance(args, Mapping):
            return error("edit arguments must be an object")

        if any(key not in _ALLOWED_ROOT_FIELDS for key in args):
            return error("edit accepts only root action, input, reasoning, and _reasoning")
        if "action" not in args or "input" not in args:
            return error("edit requires root action and input")

        action = args["action"]
        if not isinstance(action, str) or action not in _ACTION_FIELDS:
            return error(f"Unsupported action for edit: {action!r}")

        raw_input = args["input"]
        if not isinstance(raw_input, Mapping):
            return error("edit input must be an object")
        action_input = dict(raw_input)
        allowed_fields = _ACTION_FIELDS[action]
        if any(key not in allowed_fields for key in action_input):
            return error(f"unsupported edit input field for action {action!r}")

        if action == "manual":
            if action_input:
                # Kept separate from the unknown-field check so manual's closed
                # empty object remains explicit even for unusual Mapping types.
                return error("manual input must be an empty object")
            return _with_setting(load_installed_manual(agent, "file-manual"), diagnostic)

        for field in ("file_path", "old_string", "new_string"):
            if field not in action_input:
                return error(f"{field} is required")
            if not isinstance(action_input[field], str):
                return error(f"{field} must be a string")

        if "replace_all" in action_input:
            raw_replace_all = action_input["replace_all"]
            if raw_replace_all is not None and type(raw_replace_all) is not bool:
                return error("replace_all must be a boolean or null")
            replace_all = raw_replace_all is True
        else:
            # Direct handler calls may omit the strict-provider field; preserve
            # the historical false behavior while the public schema requires it.
            replace_all = False

        path_value = action_input["file_path"]
        if not path_value:
            return error("file_path is required")
        path = resolve_workdir_path(agent, path_value)
        old = action_input["old_string"]
        new = action_input["new_string"]
        try:
            content = agent._file_io.read(path)
        except FileNotFoundError:
            return error(f"File not found: {path}")
        except Exception as exc:
            return error(f"Cannot read {path}: {exc}")
        count = content.count(old)
        if count == 0:
            return error(f"old_string not found in {path}")
        if count > 1 and not replace_all:
            return error(
                f"old_string found {count} times — use replace_all=true or provide more context"
            )
        if replace_all:
            updated = content.replace(old, new)
        else:
            updated = content.replace(old, new, 1)
        try:
            agent._file_io.write(path, updated)
        except Exception as exc:
            return error(f"Cannot write {path}: {exc}")
        return _with_setting(
            {"status": "ok", "replacements": count if replace_all else 1},
            diagnostic,
        )

    agent.add_tool(
        "edit",
        schema=get_schema(),
        handler=handle_edit,
        description=get_description(),
        glossary_package=__package__,
    )
