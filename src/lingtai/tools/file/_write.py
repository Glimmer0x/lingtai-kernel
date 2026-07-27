"""The ``file`` family's ``write`` operation: create or overwrite a whole file.

Owns the full-file write and its receipt (``path`` plus the UTF-8 byte count).
Parent directories are created by the injected ``FileIOService``. Behavior is
unchanged from the pre-migration ``write`` tool; only its ownership moved here.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from .._file_paths import resolve_workdir_path

if TYPE_CHECKING:
    from lingtai.kernel.base_agent import BaseAgent

__all__ = ["build_operation"]


def build_operation(agent: "BaseAgent"):
    """Return the bound ``write`` operation for the ``file`` family.

    The returned callable takes only this action's own validated ``input``
    mapping and returns the canonical raw write receipt
    (``{"status": "ok", "path": ..., "bytes": ...}``) or a
    ``{"status": "error", ...}`` dict.
    """

    def handle_write(args: dict) -> dict:
        path = args.get("file_path", "")
        if not path:
            return {"status": "error", "message": "file_path is required"}
        if "content" not in args:
            return {"status": "error", "message": "content is required"}
        content = args["content"]
        path = resolve_workdir_path(agent, path)
        try:
            agent._file_io.write(path, content)
            return {"status": "ok", "path": path, "bytes": len(content.encode("utf-8"))}
        except Exception as e:
            return {"status": "error", "message": f"Cannot write {path}: {e}"}

    return handle_write
