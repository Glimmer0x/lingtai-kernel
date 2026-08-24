"""The ``file`` family's ``glob`` operation: find files by pattern.

Owns the sorted match list the service returns and the issue-#164 traversal
budget block, so a partial scan is never mistaken for "no files found
anywhere". Behavior is unchanged from the pre-migration ``glob`` tool; only its
ownership moved here.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from .._file_paths import resolve_workdir_path

if TYPE_CHECKING:
    from lingtai.kernel.tool_plugin import FileIOPort, WorkdirPort

__all__ = ["build_operation"]


def build_operation(workdir: "WorkdirPort", file_io: "FileIOPort"):
    """Return the bound ``glob`` operation for the ``file`` family.

    The returned callable takes only this action's own validated ``input``
    mapping and returns the canonical raw glob result (the service's sorted
    ``matches``, ``count``, and the traversal block) or a
    ``{"status": "error", ...}`` dict.
    """

    def handle_glob(args: dict) -> dict:
        pattern = args.get("pattern", "")
        if not pattern:
            return {"status": "error", "message": "pattern is required"}
        search_dir = args.get("path", str(workdir.path))
        search_dir = resolve_workdir_path(workdir.path, search_dir)
        try:
            matches = file_io.glob(pattern, root=search_dir)
            result: dict = {"matches": matches, "count": len(matches)}
            # Issue #164: surface traversal budget / exclusion info so the
            # LLM can react to partial results instead of treating them
            # as definitive ("no files found anywhere").
            stats = getattr(file_io, "last_traversal", None)
            if stats is not None and stats.truncated_reason is not None:
                result["truncated"] = True
                result["truncated_reason"] = stats.truncated_reason
                result["traversal"] = {
                    "visited": stats.visited,
                    "elapsed_ms": stats.elapsed_ms,
                    "dirs_pruned": stats.dirs_pruned,
                }
            return result
        except Exception as e:
            return {"status": "error", "message": f"Glob failed: {e}"}

    return handle_glob
