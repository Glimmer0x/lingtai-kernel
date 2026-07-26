"""Grep capability — search file contents by regex.

Usage: Agent(capabilities=["grep"]) or capabilities=["file"]
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from .._file_paths import resolve_workdir_path
from .._manual import load_installed_manual
from .._settings import current_setting, read_settings

if TYPE_CHECKING:
    from lingtai.kernel.base_agent import BaseAgent


_SUMMARY_DESCRIPTION = (
    "Optional. Default false. When true, the raw result is preserved in the "
    "durable log and replaced before entering context by a reasoning-guided "
    "summary; set it only when exact matches are not needed."
)
_ACTION_FIELDS = {
    "grep": ("pattern", "path", "glob", "max_matches", "summary"),
    "manual": (),
}
_ALLOWED_ROOT_FIELDS = ("action", "input", "reasoning", "_reasoning")


def get_description(lang: str = "en") -> str:
    return (
        "Search file contents for lines matching a regex pattern. Use grep(action='grep', "
        "input={'pattern': '...', 'path': '...', 'glob': '*.py', "
        "'max_matches': 200, 'summary': False}, reasoning='...') for an ordinary "
        "search; input.path defaults to the agent workdir, input.glob filters "
        "basenames before reads, and input.max_matches caps returned matches. "
        "Results contain file path, line number, and matched text, with traversal "
        "metadata when the scan is truncated. Load the installed guide once with "
        "grep(action='manual', input={}, reasoning='...'); after the manual result, "
        "continue with the canonical ordinary grep call instead of repeating manual."
    )


def get_schema(lang: str = "en") -> dict:
    """Return the raw closed action/input schema.

    ``BaseAgent`` adds the optional root ``reasoning`` property when it builds
    the model-facing schema. Reasoning is metadata, not nested grep input.
    """
    return {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["grep", "manual"],
                "description": "Required operation: search content or return the installed manual.",
            },
            "input": {
                "description": "Strict action-specific grep or manual input.",
                "anyOf": [
                    {
                        "title": "grep input",
                        "type": "object",
                        "properties": {
                            "pattern": {
                                "type": "string",
                                "description": "Regular expression pattern to search for.",
                            },
                            "path": {
                                "type": "string",
                                "description": "File or directory to search; defaults to the agent workdir.",
                            },
                            "glob": {
                                "type": "string",
                                "description": "Basename glob filter applied before reads.",
                                "default": "*",
                            },
                            "max_matches": {
                                "type": "integer",
                                "description": "Maximum matching lines to return.",
                                "default": 200,
                            },
                            "summary": {
                                "type": "boolean",
                                "description": _SUMMARY_DESCRIPTION,
                                "default": False,
                            },
                        },
                        "required": ["pattern"],
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
    """Attach one fresh, secret-free settings diagnostic to a public result."""
    value = dict(result)
    value["current_setting"] = dict(diagnostic)
    return value


def setup(agent: "BaseAgent") -> None:
    """Set up the grep capability on an agent."""

    def handle_grep(args: Any) -> dict:
        # Settings are evidence only, but are reread before every operation,
        # including malformed and manual calls. No FileIO operation occurs
        # before the canonical action/input checks below.
        snapshot = read_settings(agent, "grep")
        diagnostic = current_setting(snapshot, "grep")

        def error(message: str) -> dict:
            return _with_setting({"status": "error", "message": message}, diagnostic)

        if not isinstance(args, Mapping):
            return error("grep arguments must be an object")
        try:
            root_keys = list(args.keys())
        except Exception:
            return error("grep arguments must be an object")
        if any(not isinstance(key, str) or key not in _ALLOWED_ROOT_FIELDS for key in root_keys):
            return error("grep accepts only root action, input, reasoning, and _reasoning")
        if "action" not in root_keys or "input" not in root_keys:
            return error("grep requires root action and input")

        try:
            action = args["action"]
            raw_input = args["input"]
        except Exception:
            return error("grep arguments are malformed")
        if type(action) is not str or action not in _ACTION_FIELDS:
            return error(f"Unsupported action for grep: {action!r}")

        if not isinstance(raw_input, Mapping):
            return error("grep input must be an object")
        try:
            action_input = dict(raw_input)
        except Exception:
            return error("grep input must be an object")
        if any(not isinstance(key, str) for key in action_input):
            return error("grep input field names must be strings")
        allowed_fields = _ACTION_FIELDS[action]
        if any(key not in allowed_fields for key in action_input):
            return error(f"unsupported grep input field for action {action!r}")

        if action == "manual":
            if action_input:
                return error("manual input must be an empty object")
            try:
                manual = load_installed_manual(agent, "file-manual")
            except Exception as exc:
                return error(f"Grep manual failed: {exc}")
            return _with_setting(manual, diagnostic)

        if "pattern" not in action_input:
            return error("pattern is required")
        pattern = action_input["pattern"]
        if not isinstance(pattern, str):
            return error("pattern must be a string")
        if not pattern:
            return error("pattern is required")

        if "path" in action_input and not isinstance(action_input["path"], str):
            return error("path must be a string")
        if "glob" in action_input and not isinstance(action_input["glob"], str):
            return error("glob must be a string")
        if "max_matches" in action_input and type(action_input["max_matches"]) is not int:
            return error("max_matches must be an integer")
        if "summary" in action_input and type(action_input["summary"]) is not bool:
            return error("summary must be a boolean")

        search_path = action_input.get("path", str(agent._working_dir))
        glob_filter = action_input.get("glob", "*")
        max_matches = action_input.get("max_matches", 200)
        try:
            search_path = resolve_workdir_path(agent, search_path)
        except Exception as exc:
            return error(f"Grep failed: {exc}")

        try:
            # Push the basename glob into the service so excluded files are
            # pruned before stat / read, instead of scanning every file under
            # the search root and post-filtering the matches. ``*`` (and the
            # empty string, as owned by the source service) means no filter.
            service_glob = None if glob_filter in ("", "*") else glob_filter
            raw_results = agent._file_io.grep(
                pattern,
                path=search_path,
                max_results=max_matches,
                glob_filter=service_glob,
            )
            matches = [
                {"file": result.path, "line": result.line_number, "text": result.line}
                for result in raw_results
            ]
            result: dict[str, Any] = {
                "matches": matches,
                "count": len(matches),
                "truncated": len(raw_results) >= max_matches,
            }
            # Surface traversal budget / exclusion metadata so partial results
            # are not mistaken for a definitive search result.
            stats = getattr(agent._file_io, "last_traversal", None)
            if stats is not None and stats.truncated_reason is not None:
                result["truncated"] = True
                result["truncated_reason"] = stats.truncated_reason
                result["traversal"] = {
                    "visited": stats.visited,
                    "elapsed_ms": stats.elapsed_ms,
                    "dirs_pruned": stats.dirs_pruned,
                    "files_skipped_size": stats.files_skipped_size,
                    "files_skipped_binary": stats.files_skipped_binary,
                }
            return _with_setting(result, diagnostic)
        except Exception as exc:
            return error(f"Grep failed: {exc}")

    agent.add_tool(
        "grep",
        schema=get_schema(),
        handler=handle_grep,
        description=get_description(),
        glossary_package=__package__,
    )
