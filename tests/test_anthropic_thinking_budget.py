"""Anthropic extended-thinking budget resolution for every kernel tier."""
from __future__ import annotations

import pytest

from lingtai.kernel.config import THINKING_LEVELS
from lingtai.llm.anthropic.adapter import AnthropicAdapter


@pytest.mark.parametrize(
    "thinking,budget",
    [
        ("minimal", 1024),
        ("low", 2048),
        ("medium", 8192),
        ("high", 16384),
        ("xhigh", 32768),
        ("max", 65536),
    ],
)
def test_resolve_thinking_budget_maps_every_selectable_level(thinking, budget):
    assert AnthropicAdapter._resolve_thinking_budget(thinking) == budget


@pytest.mark.parametrize("thinking", ["none", "default", "", None])
def test_resolve_thinking_budget_off_values(thinking):
    """Explicit "none" and the omitted-value sentinel both disable thinking."""
    assert AnthropicAdapter._resolve_thinking_budget(thinking) is None


def test_resolve_thinking_budget_unknown_tier_is_off():
    assert AnthropicAdapter._resolve_thinking_budget("ultra") is None


def test_every_thinking_level_is_mapped():
    """No manifest-selectable level may fall through to a silent default."""
    assert set(AnthropicAdapter._THINKING_BUDGETS) == set(THINKING_LEVELS)


def test_selected_levels_never_silently_disable_thinking():
    for level in THINKING_LEVELS:
        resolved = AnthropicAdapter._resolve_thinking_budget(level)
        if level == "none":
            assert resolved is None
        else:
            assert isinstance(resolved, int) and resolved > 0


def test_budgets_are_monotonic_in_effort():
    ordered = [lvl for lvl in THINKING_LEVELS if lvl != "none"]
    budgets = [AnthropicAdapter._THINKING_BUDGETS[lvl] for lvl in ordered]
    assert budgets == sorted(budgets)
