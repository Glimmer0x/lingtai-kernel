"""Shared loader for manuals installed in an agent's intrinsic skill catalog."""
from __future__ import annotations

from pathlib import Path

#: The per-agent library directory ``Agent._install_intrinsic_manuals`` writes
#: each tool's manual tree into, relative to the agent's working directory.
INSTALLED_CAPABILITIES_ROOT = (".library", "intrinsic", "capabilities")


def installed_manual_path(working_dir: Path, skill_name: str) -> Path:
    """Return where one installed intrinsic manual lives for *working_dir*.

    The single definition of that path. ``load_installed_manual`` reads it and
    ``tools/_plugin.py`` publishes it as a plugin's mount point, so the loader
    and a package's declared mount cannot drift apart.
    """
    return Path(working_dir).joinpath(
        *INSTALLED_CAPABILITIES_ROOT, skill_name, "SKILL.md"
    )


def load_installed_manual(agent, skill_name: str) -> dict:
    """Return one installed intrinsic manual without mutating agent state."""
    manual_path = installed_manual_path(agent._working_dir, skill_name)
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
