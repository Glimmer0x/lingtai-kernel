"""Glob capability — find files by pattern.

Usage: Agent(capabilities=["glob"]) or capabilities=["file"]
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
    "summary; set it only when exact paths are not needed."
)
_ROOT_KEYS = frozenset({"action", "input", "reasoning", "_reasoning"})
_INPUT_KEYS = frozenset({"pattern", "path", "summary"})


def get_description(lang: str = "en") -> str:
    return (
        "Find files matching a glob pattern. Use glob(action='glob', "
        "input={'pattern': '...', 'path': '...', 'summary': False}, "
        "reasoning='...') for an ordinary search; input.path defaults to the "
        "agent workdir and input.summary is an exact-boolean a-priori summary "
        "control. Use '**/' for recursive search (for example, '**/*.py' matches "
        "Python files in nested relative paths according to FileIO matching). "
        "Results are sorted file paths and include traversal fields when the walk "
        "is truncated. Load the installed guide once with "
        "glob(action='manual', input={}, reasoning='...'); after the manual "
        "result, continue with the canonical ordinary glob call instead of "
        "repeating manual."
    )


def get_schema(lang: str = "en") -> dict:
    ordinary_input = {
        "title": "glob input",
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Glob pattern for the search.",
            },
            "path": {
                "type": "string",
                "description": "Directory to search; defaults to the agent workdir.",
            },
            "summary": {
                "type": "boolean",
                "description": _SUMMARY_DESCRIPTION,
                "default": False,
            },
        },
        "required": ["pattern"],
        "additionalProperties": False,
    }
    manual_input = {
        "title": "manual input",
        "type": "object",
        "properties": {},
        "required": [],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["glob", "manual"],
                "description": "Select the ordinary glob search or installed manual.",
            },
            "input": {
                "description": "Strict action-specific glob or manual input.",
                "anyOf": [ordinary_input, manual_input],
            },
        },
        "required": ["action", "input"],
        "additionalProperties": False,
    }


def _error(message: str, setting: dict[str, Any]) -> dict[str, Any]:
    """Build one glob-owned error result with the invocation setting snapshot."""
    return {"status": "error", "message": message, "current_setting": dict(setting)}


def _keys_are_closed(value: Mapping[Any, Any], allowed: frozenset[str]) -> bool:
    """Return whether a mapping has only string keys from *allowed*.

    The explicit string check keeps malformed direct calls (including mappings
    with unhashable/non-string keys) as ordinary tool errors rather than leaking
    a ``TypeError`` from membership checks.
    """
    try:
        keys = value.keys()
        return all(isinstance(key, str) and key in allowed for key in keys)
    except Exception:
        return False


def setup(agent: "BaseAgent") -> None:
    """Set up the glob capability on an agent."""

    def handle_glob(args: Mapping[str, Any]) -> dict:
        # Settings are deliberately read before validating or dispatching any
        # operation. The shared reader is a strict v1 placeholder: it reports
        # missing/valid/hot/invalid snapshots without selecting glob behavior.
        snapshot = read_settings(agent, "glob")
        setting = current_setting(snapshot, "glob")

        if not isinstance(args, Mapping):
            return _error("glob arguments must be an object", setting)
        if not _keys_are_closed(args, _ROOT_KEYS):
            return _error("glob arguments contain unsupported fields", setting)
        try:
            action = args.get("action")
            payload = args.get("input")
        except Exception:
            return _error("glob arguments are malformed", setting)

        # The two root metadata names are accepted only for the kernel's
        # reasoning plumbing. They never become part of the nested payload and
        # never reach FileIO.
        if type(action) is not str or action not in ("glob", "manual"):
            return _error(f"Unsupported action for glob: {action!r}", setting)
        if not isinstance(payload, Mapping):
            return _error("input must be an object", setting)
        if not _keys_are_closed(payload, _INPUT_KEYS):
            return _error("glob input contains unsupported fields", setting)

        if action == "manual":
            try:
                manual_has_input = bool(payload)
            except Exception:
                return _error("manual input must be an empty object", setting)
            if manual_has_input:
                return _error("manual input must be an empty object", setting)
            try:
                loaded = dict(load_installed_manual(agent, "file-manual"))
            except Exception as exc:
                return _error(f"Glob manual failed: {exc}", setting)
            loaded["current_setting"] = dict(setting)
            return loaded

        try:
            if "pattern" not in payload:
                return _error("pattern is required", setting)
            pattern = payload.get("pattern")
            if not isinstance(pattern, str):
                return _error("pattern must be a string", setting)
            if not pattern:
                return _error("pattern is required", setting)

            if "path" in payload:
                search_dir = payload.get("path")
                if not isinstance(search_dir, str):
                    return _error("path must be a string", setting)
            else:
                search_dir = str(agent._working_dir)
            # Validate the genuine exact-boolean control, but intentionally do
            # not forward it to FileIO or let it affect matching.
            if "summary" in payload and type(payload.get("summary")) is not bool:
                return _error("summary must be a boolean", setting)
            search_dir = resolve_workdir_path(agent, search_dir)
        except Exception as exc:
            return _error(f"Glob failed: {exc}", setting)

        try:
            matches = agent._file_io.glob(pattern, root=search_dir)
            result: dict[str, Any] = {
                "matches": matches,
                "count": len(matches),
                "current_setting": dict(setting),
            }
            # Issue #164: surface traversal budget / exclusion info so the
            # LLM can react to partial results instead of treating them
            # as definitive ("no files found anywhere").
            stats = getattr(agent._file_io, "last_traversal", None)
            if stats is not None and stats.truncated_reason is not None:
                result["truncated"] = True
                result["truncated_reason"] = stats.truncated_reason
                result["traversal"] = {
                    "visited": stats.visited,
                    "elapsed_ms": stats.elapsed_ms,
                    "dirs_pruned": stats.dirs_pruned,
                }
            return result
        except Exception as exc:
            return _error(f"Glob failed: {exc}", setting)

    agent.add_tool(
        "glob",
        schema=get_schema(),
        handler=handle_glob,
        description=get_description(),
        glossary_package=__package__,
    )
