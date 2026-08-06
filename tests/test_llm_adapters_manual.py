"""Parity tests for the llm-adapters manual vs the adapter registry.

Guards the progressive-disclosure deliverable shipped with the Codex transport
work: the manual's provider inventory must match the actual registered provider
keys, and the parent system-manual router must advertise the new reference.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lingtai.llm._register import register_all_adapters
from lingtai.llm.service import LLMService

REPO_ROOT = Path(__file__).resolve().parents[1]
ADAPTER_MANUAL = (
    REPO_ROOT
    / "src/lingtai/intrinsic_skills/system-manual/reference/llm-adapters/SKILL.md"
)
SYSTEM_MANUAL = REPO_ROOT / "src/lingtai/intrinsic_skills/system-manual/SKILL.md"


@pytest.fixture(scope="module")
def registered_keys() -> set[str]:
    register_all_adapters()
    return set(LLMService._adapter_registry.keys())


def test_manual_lists_every_registered_provider_key(registered_keys):
    """Every provider key registered by the kernel appears in the llm-adapters
    manual's inventory table (provider keys / aliases column)."""

    text = ADAPTER_MANUAL.read_text(encoding="utf-8")
    missing = sorted(k for k in registered_keys if k not in text)
    assert not missing, f"manual omits registered provider key(s): {missing}"


def test_manual_inventory_table_present():
    """The manual carries the named-adapters inventory table."""

    text = ADAPTER_MANUAL.read_text(encoding="utf-8")
    assert "## Named adapters" in text
    assert "Provider keys" in text


def test_system_manual_advertises_llm_adapters_reference():
    """system-manual's catalog and router table advertise the llm-adapters
    reference so the topic is discoverable without guessing."""

    text = SYSTEM_MANUAL.read_text(encoding="utf-8")
    assert "llm-adapters" in text
    assert "reference/llm-adapters/SKILL.md" in text


def test_system_manual_frontmatter_mentions_llm_adapters():
    """system-manual frontmatter (description/tags) advertises the LLM-adapter
    route."""

    text = SYSTEM_MANUAL.read_text(encoding="utf-8")
    frontmatter = text.split("---", 2)[1]
    assert "LLM adapters" in frontmatter or "llm-adapters" in frontmatter
