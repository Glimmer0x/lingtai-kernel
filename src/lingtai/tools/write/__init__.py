"""Write capability — create or overwrite a file.

Usage: Agent(capabilities=["write"]) or capabilities=["file"]
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from .._file_paths import resolve_workdir_path
from .._manual import load_installed_manual
from .._settings import SettingsSnapshot, current_setting, read_settings

if TYPE_CHECKING:
    from lingtai.kernel.base_agent import BaseAgent


_ACTION_INPUT_FIELDS = {
    "write": {"file_path", "content"},
    "manual": set(),
}
_ALLOWED_ROOT_FIELDS = {"action", "input", "reasoning", "_reasoning"}


def get_description(lang: str = "en") -> str:
    return (
        "Create or overwrite a file. Use write(action='write', input={'file_path': "
        "'...', 'content': '...'}, reasoning='...') for a complete write. Use "
        "write(action='manual', input={}, reasoning='...') to load the installed "
        "file-manual procedure. Parent directories are created automatically; "
        "small changes to existing files should use edit."
    )


def get_schema(lang: str = "en") -> dict[str, Any]:
    """Return the raw closed action/input schema owned by this tool.

    ``BaseAgent`` adds the optional root ``reasoning`` property when constructing
    the final Agent-facing schema. Reasoning is metadata and is intentionally not
    part of this raw schema or either nested input branch.
    """
    return {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["write", "manual"],
                "description": "Required operation: write a file or return the installed file-manual.",
            },
            "input": {
                "description": "Strict action-specific write input.",
                "anyOf": [
                    {
                        "title": "write input",
                        "type": "object",
                        "properties": {
                            "file_path": {
                                "type": "string",
                                "description": "Path to the file to write.",
                            },
                            "content": {
                                "type": "string",
                                "description": "Complete UTF-8 text content to write.",
                            },
                        },
                        "required": ["file_path", "content"],
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


def _settings_diagnostic(agent: "BaseAgent") -> dict[str, Any]:
    """Read write settings exactly once for one call and build safe evidence."""
    try:
        snapshot = read_settings(agent, "write")
    except Exception as exc:
        # The foundation reader normally converts all expected filesystem and
        # validation failures into a snapshot. Keep the result contract intact
        # even if an injected test/future reader unexpectedly raises.
        snapshot = SettingsSnapshot(
            "settings_error",
            "error",
            None,
            f"settings read failed ({type(exc).__name__})",
        )
    return current_setting(snapshot, "write")


def _with_setting(result: dict[str, Any], diagnostic: dict[str, Any]) -> dict[str, Any]:
    result["current_setting"] = diagnostic
    return result


def setup(agent: "BaseAgent") -> None:
    """Set up the write capability on an agent."""

    def handle_write(args: dict) -> dict:
        # This must remain the first operation on every call. The placeholder is
        # diagnostic-only; it never selects or changes write behavior.
        diagnostic = _settings_diagnostic(agent)

        if not isinstance(args, Mapping):
            return _with_setting(
                {"status": "error", "message": "write arguments must be an object"},
                diagnostic,
            )
        raw = dict(args)

        # ToolExecutor removes public root ``reasoning`` and stores it as
        # internal ``_reasoning``. Direct public callers may provide either key;
        # neither is part of the action dispatch input.
        unknown = set(raw) - _ALLOWED_ROOT_FIELDS
        if unknown:
            return _with_setting(
                {"status": "error", "message": "unsupported write argument"},
                diagnostic,
            )

        if "action" not in raw:
            return _with_setting(
                {"status": "error", "message": "action is required"}, diagnostic
            )
        action = raw["action"]
        if not isinstance(action, str) or action not in _ACTION_INPUT_FIELDS:
            return _with_setting(
                {
                    "status": "error",
                    "message": "action must be one of write or manual",
                },
                diagnostic,
            )

        if "input" not in raw:
            return _with_setting(
                {"status": "error", "message": "input is required"}, diagnostic
            )
        action_input = raw["input"]
        if not isinstance(action_input, Mapping):
            return _with_setting(
                {"status": "error", "message": "input must be an object"}, diagnostic
            )
        action_args = dict(action_input)
        if set(action_args) - _ACTION_INPUT_FIELDS[action]:
            return _with_setting(
                {"status": "error", "message": "unsupported write input field"},
                diagnostic,
            )

        if action == "manual":
            try:
                loaded = load_installed_manual(agent, "file-manual")
            except Exception as exc:
                return _with_setting(
                    {
                        "status": "error",
                        "action": "manual",
                        "message": f"Cannot load file-manual ({type(exc).__name__})",
                    },
                    diagnostic,
                )
            loaded = dict(loaded)
            loaded["action"] = "manual"
            return _with_setting(loaded, diagnostic)

        # Preserve the historical write validation and FileIO delegation while
        # accepting only the new nested input branch.
        file_path = action_args.get("file_path", "")
        if not isinstance(file_path, str):
            return _with_setting(
                {"status": "error", "message": "file_path must be a string"},
                diagnostic,
            )
        if not file_path:
            return _with_setting(
                {"status": "error", "message": "file_path is required"}, diagnostic
            )
        if "content" not in action_args:
            return _with_setting(
                {"status": "error", "message": "content is required"}, diagnostic
            )
        content = action_args["content"]
        if not isinstance(content, str):
            return _with_setting(
                {"status": "error", "message": "content must be a string"}, diagnostic
            )

        try:
            path = resolve_workdir_path(agent, file_path)
            agent._file_io.write(path, content)
            result = {
                "status": "ok",
                "path": path,
                "bytes": len(content.encode("utf-8")),
            }
        except Exception as exc:
            # Keep the existing structured FileIO error shape and resolved path
            # behavior; the current setting is independent evidence only.
            path_for_message = locals().get("path", file_path)
            result = {
                "status": "error",
                "message": f"Cannot write {path_for_message}: {exc}",
            }
        return _with_setting(result, diagnostic)

    agent.add_tool(
        "write",
        schema=get_schema(),
        handler=handle_write,
        description=get_description(),
        glossary_package=__package__,
    )
