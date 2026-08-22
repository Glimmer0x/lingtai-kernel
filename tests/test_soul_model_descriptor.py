"""Focused evidence for soul's consumed package-local model descriptor."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from lingtai.tools import soul
from lingtai.tools.soul.descriptor import SOUL_MODEL_DESCRIPTOR


class _ManualAgent:
    def __init__(self, working_dir: Path) -> None:
        self._working_dir = working_dir


def test_descriptor_is_the_active_model_facing_identity() -> None:
    """The descriptor is consumed by the shipped schema family and prose, not
    inert plugin metadata awaiting an external registry or activation path.
    """
    descriptor = SOUL_MODEL_DESCRIPTOR

    assert descriptor.root_name == "soul"
    assert soul._FAMILY.name == descriptor.root_name
    assert soul.get_description() == descriptor.description
    assert "six actions" in descriptor.description
    assert "LINGTAI_SOUL_FLOW_ENABLED=1" in descriptor.description
    assert "no action in this family can enable flow" in descriptor.description
    assert descriptor.manual_skill_name == "soul-manual"


def test_descriptor_drives_the_active_description_and_reserved_manual_child(
    tmp_path: Path, monkeypatch
) -> None:
    """Prove both descriptor values are consumed at the existing root boundary.

    The manual call still uses the regular reserved child and installed catalog;
    this test adds no registry entry, activation, or host lifecycle behavior.
    """
    descriptor = replace(
        SOUL_MODEL_DESCRIPTOR,
        description="descriptor-provided model prose",
        manual_skill_name="soul-manual-descriptor-probe",
    )
    monkeypatch.setattr(soul, "SOUL_MODEL_DESCRIPTOR", descriptor)

    manual_path = (
        tmp_path
        / ".library"
        / "intrinsic"
        / "capabilities"
        / descriptor.manual_skill_name
        / "SKILL.md"
    )
    manual_path.parent.mkdir(parents=True)
    manual_path.write_text("# descriptor manual\n", encoding="utf-8")

    assert soul.get_description() == "descriptor-provided model prose"
    assert soul.handle(_ManualAgent(tmp_path), {"action": "manual", "input": {}}) == {
        "status": "ok",
        "manual": "# descriptor manual\n",
        "manual_path": str(manual_path),
    }
