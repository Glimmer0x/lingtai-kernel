"""Read capability — read text file contents.

Usage: Agent(capabilities=["read"]) or capabilities=["file"]
"""
from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

from lingtai.kernel.tool_result_artifacts import PREVENTIVE_MAX_CHARS

from .._file_paths import resolve_workdir_path
from .._manual import load_installed_manual
from .._settings import current_setting, read_settings

if TYPE_CHECKING:
    from lingtai.kernel.base_agent import BaseAgent

PROVIDERS = {"providers": [], "default": "builtin"}

# Read defaults to a smaller everyday page budget while the runtime tool-result
# boundary remains a larger non-configurable hard ceiling. Callers may pass
# ``max_chars`` per read call; values above the runtime ceiling are clamped.
DEFAULT_READ_CAP_CHARS: int = 100_000
READ_HARD_CAP_CHARS: int = PREVENTIVE_MAX_CHARS

_ACTION_FIELDS = {
    "read": ("file_path", "offset", "limit", "max_chars", "summary"),
    "manual": (),
}
_ALLOWED_ROOT_FIELDS = ("action", "input", "reasoning", "_reasoning")


def _valid_cap(value: object) -> int | None:
    return value if type(value) is int and value > 0 else None


def _runtime_hard_cap(agent: "BaseAgent") -> int:
    """Return the active runtime hard ceiling for provider-visible tool results."""
    executor_cap = _valid_cap(getattr(getattr(agent, "_executor", None), "_max_result_chars", None))
    if executor_cap is not None:
        return min(executor_cap, READ_HARD_CAP_CHARS)
    return READ_HARD_CAP_CHARS


def _resolve_call_cap(agent: "BaseAgent", requested_max_chars: object) -> int:
    """Return the per-call read cap, clamped by the runtime hard ceiling.

    ``max_chars`` lets the caller intentionally ask for smaller or larger chunks
    than the read default while the runtime hard cap remains the ceiling that
    prevents provider-visible tool-result blowups. Invalid per-call values are
    ignored and use the read default, preserving the pre-migration read math.
    """
    runtime_cap = _runtime_hard_cap(agent)
    requested_cap = _valid_cap(requested_max_chars)
    if requested_cap is None:
        return min(DEFAULT_READ_CAP_CHARS, runtime_cap)
    return min(requested_cap, runtime_cap)


def get_description(lang: str = "en") -> str:
    return (
        "Read the contents of a text file. Use read(action='read', input={'file_path': "
        "'...', 'offset': 1, 'limit': 2000, 'max_chars': 100000, 'summary': False}, "
        "reasoning='...') for an ordinary text read. The nested input is strict and "
        "closed; file_path is required, offset is 1-based with default 1, limit "
        "defaults to 2000 lines, and max_chars is clamped by the 200 000 runtime "
        "hard cap. Returns numbered lines and continuation metadata when capped; "
        "check truncated, cap_chars, returned_chars, next_offset, "
        "remaining_lines_estimate, and line_truncated. Before large or continued "
        "reads, load the installed guide with read(action='manual', input={}, "
        "reasoning='...'). This tool reads text files only and cannot read binary, "
        "images, or audio."
    )


def get_schema(lang: str = "en") -> dict:
    """Return the raw closed action/input schema.

    ``BaseAgent`` adds the optional root ``reasoning`` property when it builds
    the model-facing schema. It is metadata, not a read action input.
    """
    return {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["read", "manual"],
                "description": "Required operation: read a file or return the installed manual.",
            },
            "input": {
                "description": "Strict action-specific read input.",
                "anyOf": [
                    {
                        "title": "read input",
                        "type": "object",
                        "properties": {
                            "file_path": {
                                "type": "string",
                                "description": "Path to the text file to read.",
                            },
                            "offset": {
                                "type": "integer",
                                "description": "Line number to start from (1-based).",
                                "default": 1,
                            },
                            "limit": {
                                "type": "integer",
                                "description": "Maximum number of lines to read.",
                                "default": 2000,
                            },
                            "max_chars": {
                                "type": "integer",
                                "description": (
                                    "Optional per-call character budget for read content. "
                                    "Defaults to 100 000; values above the runtime hard cap "
                                    "are clamped to 200 000."
                                ),
                            },
                            "summary": {
                                "type": "boolean",
                                "description": (
                                    "Optional a-priori summary control. Default false; when "
                                    "true, preserve the raw result before replacing the "
                                    "model-visible result with a generated summary."
                                ),
                                "default": False,
                            },
                        },
                        "required": ["file_path"],
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


def _apply_cap(
    lines: list[str],
    start: int,
    requested_limit: int,
    cap_chars: int,
) -> tuple[str, dict]:
    """Build numbered content string, capping at *cap_chars* on whole-line boundaries.

    Returns ``(numbered_content, extra_meta)`` where *extra_meta* contains
    continuation fields only when the result was truncated.
    """
    total_lines = len(lines)
    end_exclusive = min(start + requested_limit, total_lines)
    window = lines[start:end_exclusive]

    chars_used = 0
    kept: list[str] = []
    line_truncated = False
    for i, line in enumerate(window):
        numbered_line = f"{start + i + 1}\t{line}"
        if chars_used + len(numbered_line) > cap_chars:
            if not kept:
                # A single line can exceed the cap by itself. Return a bounded
                # prefix, but mark the result as truncated so callers do not
                # mistake the prefix for the whole line.
                kept.append(numbered_line[:cap_chars])
                line_truncated = True
            break
        kept.append(numbered_line)
        chars_used += len(numbered_line)

    numbered = "".join(kept)
    returned_lines = len(kept)
    last_returned_line = start + returned_lines  # 1-based

    truncated = line_truncated or returned_lines < len(window)
    if not truncated:
        meta: dict = {}
    else:
        next_offset = last_returned_line + 1 if returned_lines else start + 1
        remaining = total_lines - last_returned_line
        meta = {
            "truncated": True,
            "cap_chars": cap_chars,
            "returned_chars": len(numbered),
            "requested_offset": start + 1,
            "requested_limit": requested_limit,
            "last_returned_line": last_returned_line if returned_lines else None,
            "next_offset": next_offset,
            "remaining_lines_estimate": max(0, remaining),
        }
        if line_truncated:
            meta["line_truncated"] = True

    return numbered, meta


def setup(agent: "BaseAgent") -> None:
    """Set up the read capability on an agent."""

    def handle_read(args: Any) -> dict:
        # Settings are evidence only, but must be reread before every operation,
        # including malformed and manual calls. No target FileIO operation occurs
        # before the canonical action/input checks below.
        snapshot = read_settings(agent, "read")
        diagnostic = current_setting(snapshot, "read")

        def error(message: str) -> dict:
            return _with_setting({"status": "error", "message": message}, diagnostic)

        if not isinstance(args, Mapping):
            return error("read arguments must be an object")
        try:
            root_keys = list(args.keys())
        except Exception:
            return error("read arguments must be an object")
        if any(not isinstance(key, str) or key not in _ALLOWED_ROOT_FIELDS for key in root_keys):
            return error("read accepts only root action, input, reasoning, and _reasoning")
        if "action" not in root_keys or "input" not in root_keys:
            return error("read requires root action and input")

        action = args["action"]
        if not isinstance(action, str) or action not in _ACTION_FIELDS:
            return error(f"Unsupported action for read: {action!r}")

        raw_input = args["input"]
        if not isinstance(raw_input, Mapping):
            return error("read input must be an object")
        try:
            action_input = dict(raw_input)
        except Exception:
            return error("read input must be an object")
        if any(not isinstance(key, str) for key in action_input):
            return error("read input field names must be strings")
        allowed_fields = _ACTION_FIELDS[action]
        if any(key not in allowed_fields for key in action_input):
            return error(f"unsupported read input field for action {action!r}")

        if action == "manual":
            if action_input:
                return error("manual input must be an empty object")
            return _with_setting(load_installed_manual(agent, "read-manual"), diagnostic)

        if "file_path" not in action_input:
            return error("file_path is required")
        file_path = action_input["file_path"]
        if not isinstance(file_path, str):
            return error("file_path must be a string")
        if not file_path:
            return error("file_path is required")

        for field in ("offset", "limit"):
            if field in action_input and type(action_input[field]) is not int:
                return error(f"{field} must be an integer")
        if "max_chars" in action_input and type(action_input["max_chars"]) is not int:
            return error("max_chars must be an integer")
        if "summary" in action_input and type(action_input["summary"]) is not bool:
            return error("summary must be a boolean")

        path = resolve_workdir_path(agent, file_path)
        offset = action_input.get("offset", 1)
        limit = action_input.get("limit", 2000)
        max_chars = action_input.get("max_chars")
        try:
            content = agent._file_io.read(path)
        except FileNotFoundError:
            # Spill-aware messaging: if the missing file is under
            # tmp/tool-results/, it was an ephemeral sidecar artifact
            # that has been cleaned up. Give a specific hint instead
            # of the generic "File not found".
            # Normalize to collapse ".." components so that e.g.
            # tmp/tool-results/../not-a-spill.txt is NOT misclassified
            # as a spill path.
            try:
                rel = Path(path).resolve().relative_to(
                    Path(agent._working_dir).resolve()
                )
            except (ValueError, OSError):
                rel = Path(path)
            parts = rel.parts
            if len(parts) >= 3 and parts[0] == "tmp" and parts[1] == "tool-results":
                return error(
                    "Spill artifact expired: this tmp/tool-results/ sidecar file "
                    "no longer exists. The original tool result content is "
                    "unavailable. Use the preview from the manifest or rerun the "
                    "source tool."
                )
            return error(f"File not found: {path}")
        except Exception as exc:
            return error(f"Cannot read {path}: {exc}")
        lines = content.splitlines(keepends=True)
        start = max(0, offset - 1)
        numbered, extra = _apply_cap(lines, start, limit, _resolve_call_cap(agent, max_chars))
        result: dict = {
            "content": numbered,
            "total_lines": len(lines),
            "lines_shown": len(numbered.splitlines()) if numbered else 0,
        }
        result.update(extra)
        return _with_setting(result, diagnostic)

    agent.add_tool(
        "read",
        schema=get_schema(),
        handler=handle_read,
        description=get_description(),
        glossary_package=__package__,
    )
