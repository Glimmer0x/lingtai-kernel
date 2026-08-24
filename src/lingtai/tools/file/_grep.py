"""The ``file`` family's ``grep`` operation: search file contents by regex.

Owns the match cap, the glob filter pushed down into the service so excluded
files are pruned before stat/read, and the issue-#164 traversal budget block.
Behavior is unchanged from the pre-migration ``grep`` tool; only its ownership
moved here.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .._file_paths import resolve_workdir_path

if TYPE_CHECKING:
    from lingtai.kernel.tool_plugin import FileIOPort, WorkdirPort

__all__ = ["build_operation"]


def build_operation(workdir: "WorkdirPort", file_io: "FileIOPort"):
    """Return the bound ``grep`` operation for the ``file`` family.

    The returned callable takes only this action's own validated ``input``
    mapping and returns the canonical raw grep result (matches with file path
    and line number, ``count``, ``truncated``, and the traversal block) or a
    ``{"status": "error", ...}`` dict.
    """

    def handle_grep(args: dict) -> dict:
        pattern = args.get("pattern", "")
        if not pattern:
            return {"status": "error", "message": "pattern is required"}
        search_path = args.get("path", str(workdir.path))
        search_path = resolve_workdir_path(workdir.path, search_path)
        max_matches = args.get("max_matches", 200)
        glob_filter = args.get("glob", "*")
        try:
            # Push the glob filter into the service so excluded files are
            # pruned *before* stat / read, instead of scanning every file
            # under the search root and post-filtering the matches. ``"*"``
            # is the schema default and means "no filter".
            service_glob = None if glob_filter in (None, "", "*") else glob_filter
            raw_results = file_io.grep(
                pattern,
                path=search_path,
                max_results=max_matches,
                glob_filter=service_glob,
            )
            matches = [{"file": r.path, "line": r.line_number, "text": r.line} for r in raw_results]
            # truncated: true when the (already glob-pruned) scan hit its
            # cap — there may be more matching files beyond what was
            # scanned.
            truncated = len(raw_results) >= max_matches
            result: dict[str, Any] = {
                "matches": matches,
                "count": len(matches),
                "truncated": truncated,
            }
            # Issue #164: surface traversal budget / exclusion info so the
            # LLM can react to partial results instead of treating them
            # as definitive ("no matches found anywhere").
            stats = getattr(file_io, "last_traversal", None)
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
            return result
        except Exception as e:
            return {"status": "error", "message": f"Grep failed: {e}"}

    return handle_grep
