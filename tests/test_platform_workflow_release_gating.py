"""Static trigger contract for expensive hosted platform checks."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = (
    "kernel-macos-smoke-pr.yml",
    "kernel-windows-pr.yml",
    "shell-windows-pr.yml",
)


@pytest.mark.parametrize("filename", WORKFLOWS)
def test_expensive_platform_workflow_runs_only_on_published_release(filename: str) -> None:
    data = yaml.safe_load((REPO_ROOT / ".github" / "workflows" / filename).read_text())
    on = data.get("on") or data.get(True)  # PyYAML YAML 1.1 `on` quirk.
    assert on == {"release": {"types": ["published"]}}
    assert data["name"].endswith("release contract")
