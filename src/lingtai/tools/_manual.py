"""Shared loader for manuals installed in an agent's intrinsic skill catalog."""
from __future__ import annotations


def _agent_working_dir(source):
    """Resolve the agent working directory from an Agent or a workdir port.

    Historically this loader took the whole ``Agent`` and read its private
    ``_working_dir``. A family that has recut onto the declared host-plugin
    contract holds no Agent at all — only a
    ``lingtai.kernel.tool_plugin.WorkdirPort``, whose entire capability is
    ``path``. Both are accepted so migrated and unmigrated families share one
    loader instead of forking the manual contract.

    Neither shape being resolvable is a wiring defect, and it is named as one:
    an ``Agent`` whose ``_working_dir`` is unset would otherwise fall through to
    the port branch and raise a misleading ``AttributeError`` about a missing
    ``path``.
    """
    working_dir = getattr(source, "_working_dir", None)
    if working_dir is not None:
        return working_dir
    path = getattr(source, "path", None)
    if path is not None:
        return path
    raise AttributeError(
        f"cannot resolve an agent working directory from "
        f"{type(source).__name__}: it is neither a live Agent with "
        "'_working_dir' set nor a WorkdirPort with 'path'"
    )


def load_installed_manual(source, skill_name: str) -> dict:
    """Return one installed intrinsic manual without mutating agent state.

    *source* is the live ``Agent`` or a least-privilege workdir port; see
    :func:`_agent_working_dir`.
    """
    manual_path = (
        _agent_working_dir(source)
        / ".library"
        / "intrinsic"
        / "capabilities"
        / skill_name
        / "SKILL.md"
    )
    if not manual_path.is_file():
        return {
            "status": "degraded",
            "manual": "",
            "manual_path": str(manual_path),
            "error": (
                f"{skill_name} manual missing — initializer may have failed or "
                "capability not installed correctly"
            ),
        }
    return {
        "status": "ok",
        "manual": manual_path.read_text(encoding="utf-8"),
        "manual_path": str(manual_path),
    }
