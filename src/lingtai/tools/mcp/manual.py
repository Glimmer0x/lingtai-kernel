"""Package-owned manual child for the model-facing :mod:`lingtai.tools.mcp` root.

The MCP registry is deliberately Host-owned, but the model-facing guidance is a
resource of this package.  Keeping the loader here means ``mcp(action="manual")``
reads the same bundled ``manual/SKILL.md`` that ships with the capability; it
never asks the registry service to rescan, register, activate, or configure an
MCP server.

The returned child result follows the generic ``ToolFamily`` manual wire shape
so ``mcp.__init__`` can preserve its historical flat ``mcp_manual`` presentation
adapter strictly after dispatch.
"""
from __future__ import annotations

import copy
from importlib import resources
from typing import Any, Mapping

from ..tool_family import ChildTool
from ..tool_family.manual import MANUAL_INPUT_SCHEMA

__all__ = ["build_manual_child", "load_packaged_manual"]

_PACKAGE = "lingtai.tools.mcp"
_MANUAL_RESOURCE = "manual/SKILL.md"


def load_packaged_manual() -> dict[str, str]:
    """Load MCP's bundled manual without touching any agent or registry state.

    The flat loader shape intentionally mirrors ``load_installed_manual`` so the
    canonical child result and the root's legacy presentation adapter retain
    their stable fields.  A broken wheel/resource remains a truthful degraded
    result rather than an activation or registry-repair path.
    """
    resource = resources.files(_PACKAGE).joinpath(_MANUAL_RESOURCE)
    path = str(resource)
    try:
        body = resource.read_text(encoding="utf-8")
    except (FileNotFoundError, ModuleNotFoundError, AttributeError, OSError):
        return {
            "status": "degraded",
            "manual": "",
            "manual_path": path,
            "error": (
                "mcp manual missing — initializer may have failed or capability "
                "not installed correctly"
            ),
        }
    return {"status": "ok", "manual": body, "manual_path": path}


def _to_canonical_manual_result(loaded: Mapping[str, Any]) -> dict[str, Any]:
    """Map the package manual loader result to ToolFamily's child wire shape."""
    result: dict[str, Any] = {
        "status": loaded.get("status", "ok"),
        "content": [{"type": "text", "text": loaded.get("manual", "")}],
        "structuredContent": {"manual_path": loaded.get("manual_path", "")},
    }
    if "error" in loaded:
        result["error"] = loaded["error"]
    return result


def build_manual_child() -> ChildTool:
    """Build MCP's reserved package-owned ``manual`` child.

    Its handler closes over this package's resource loader, so the manual action
    is independent of agent-local intrinsic copies and cannot cause registry I/O.
    ``copy.deepcopy`` prevents a future family-local mutation from altering the
    generic strict-empty schema literal shared by all manual actions.
    """
    return ChildTool(
        name="manual",
        input_schema=copy.deepcopy(MANUAL_INPUT_SCHEMA),
        handler=lambda _input: _to_canonical_manual_result(load_packaged_manual()),
        title="manual input",
    )
