"""The ``file`` family's ``edit`` operation: exact string replacement.

Owns the exact-match discipline that makes edit safe: a missing ``old_string``
and an ambiguous one (more than one occurrence without ``replace_all``) both
fail loudly and leave the file untouched. Behavior is unchanged from the
pre-migration ``edit`` tool; only its ownership moved here.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from .._file_paths import resolve_workdir_path

if TYPE_CHECKING:
    from lingtai.kernel.base_agent import BaseAgent

__all__ = ["build_operation"]


def build_operation(agent: "BaseAgent"):
    """Return the bound ``edit`` operation for the ``file`` family.

    The returned callable takes only this action's own validated ``input``
    mapping and returns the canonical raw edit receipt
    (``{"status": "ok", "replacements": ...}``) or a
    ``{"status": "error", ...}`` dict — including the exact not-found and
    ambiguity messages.
    """

    def handle_edit(args: dict) -> dict:
        path = args.get("file_path", "")
        if not path:
            return {"status": "error", "message": "file_path is required"}
        if "old_string" not in args:
            return {"status": "error", "message": "old_string is required"}
        if "new_string" not in args:
            return {"status": "error", "message": "new_string is required"}
        path = resolve_workdir_path(agent, path)
        old = args["old_string"]
        new = args["new_string"]
        replace_all = args.get("replace_all", False)
        try:
            content = agent._file_io.read(path)
        except FileNotFoundError:
            return {"status": "error", "message": f"File not found: {path}"}
        except Exception as e:
            return {"status": "error", "message": f"Cannot read {path}: {e}"}
        count = content.count(old)
        if count == 0:
            return {"status": "error", "message": f"old_string not found in {path}"}
        if count > 1 and not replace_all:
            return {"status": "error", "message": f"old_string found {count} times — use replace_all=true or provide more context"}
        if replace_all:
            updated = content.replace(old, new)
        else:
            updated = content.replace(old, new, 1)
        try:
            agent._file_io.write(path, updated)
        except Exception as e:
            return {"status": "error", "message": f"Cannot write {path}: {e}"}
        return {"status": "ok", "replacements": count if replace_all else 1}

    return handle_edit
