"""Contract tests for the agent-directory MANUAL.md generator.

Pins the promises in src/lingtai/kernel/agent_manual/CONTRACT.md: first
generation when missing, strict no-op on a matching template_version,
regeneration on a stale version, crash-atomic writes, live-snapshot rendering
from a facts dict, the no-secrets discipline, the directory-map structure,
and the absence of any overlay mechanism.
"""
from __future__ import annotations

import os

import pytest

from lingtai.kernel.agent_manual import (
    ensure_agent_manual,
    render_manual,
    template_version,
    _read_template,
)
from lingtai.kernel.workdir import workdir_layout


SAMPLE_FACTS = {
    "agent_name": "mimo",
    "agent_id": "20260809-120000-abcd",
    "created_at": "2026-08-09T12:00:00Z",
    "molt_count": 7,
    "provider": "anthropic",
    "model": "claude-fable-5",
    "preset": "eco100",
    "context_limit": 200000,
    "heartbeat": "publishing",
    "source_revision": "0.9.0 df2b523d",
    "mcp_status": "3 non-intrinsic tool(s) registered",
    "workdir": "/agents/mimo",
    "pad_pointer": "system/pad.md",
}


def test_workdir_layout_names_manual(tmp_path):
    assert workdir_layout(tmp_path).manual == tmp_path / "MANUAL.md"


def test_first_generation_when_missing(tmp_path):
    target = ensure_agent_manual(tmp_path, facts=SAMPLE_FACTS)
    assert target == tmp_path / "MANUAL.md"
    text = target.read_text(encoding="utf-8")
    assert template_version(text) == template_version(_read_template())
    # No unexpanded placeholders survive rendering.
    assert "{{" not in text


def test_noop_when_same_template_version(tmp_path):
    first = ensure_agent_manual(tmp_path, facts=SAMPLE_FACTS)
    before = first.read_text(encoding="utf-8")
    mtime = first.stat().st_mtime_ns
    # Different facts must not matter: version match means strict no-op.
    second = ensure_agent_manual(tmp_path, facts={"agent_name": "other"})
    assert second is None
    assert first.read_text(encoding="utf-8") == before
    assert first.stat().st_mtime_ns == mtime


def test_regenerates_when_version_stale(tmp_path):
    manual = tmp_path / "MANUAL.md"
    manual.write_text(
        "---\ntemplate_version: agent-manual/v0\n---\nold body\n",
        encoding="utf-8",
    )
    target = ensure_agent_manual(tmp_path, facts=SAMPLE_FACTS)
    assert target == manual
    text = manual.read_text(encoding="utf-8")
    assert template_version(text) == template_version(_read_template())
    assert "old body" not in text


def test_regenerates_when_version_missing(tmp_path):
    manual = tmp_path / "MANUAL.md"
    manual.write_text("hand-rolled, no version head\n", encoding="utf-8")
    assert ensure_agent_manual(tmp_path, facts=SAMPLE_FACTS) == manual
    assert template_version(manual.read_text(encoding="utf-8")) is not None


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission semantics")
def test_atomic_write_leaves_no_partial_file(tmp_path):
    root = tmp_path / "agent"
    root.mkdir()
    root.chmod(0o500)  # writes into the directory fail
    try:
        with pytest.raises(OSError):
            ensure_agent_manual(root, facts=SAMPLE_FACTS)
    finally:
        root.chmod(0o700)
    # Neither a partial MANUAL.md nor temp litter may remain.
    assert list(root.iterdir()) == []


def test_live_section_renders_facts():
    text = render_manual(SAMPLE_FACTS)
    for value in ("mimo", "20260809-120000-abcd", "claude-fable-5", "eco100",
                  "200000", "df2b523d", "/agents/mimo"):
        assert value in text
    assert "molt count 7" in text


def test_missing_facts_render_as_unknown():
    text = render_manual({})
    assert "unknown" in text
    assert "{{" not in text


def test_secrets_never_rendered(tmp_path):
    secrets_dir = tmp_path / ".secrets"
    secrets_dir.mkdir()
    (secrets_dir / "api_key.txt").write_text("SUPER-SECRET-ON-DISK", encoding="utf-8")
    # Even a caller mistakenly passing credential facts must not leak them:
    # secret-named keys are scrubbed before substitution.
    facts = dict(SAMPLE_FACTS, api_key="sk-canary-123", bot_token="tok-canary")
    target = ensure_agent_manual(tmp_path, facts=facts)
    text = target.read_text(encoding="utf-8")
    assert "SUPER-SECRET-ON-DISK" not in text
    assert "sk-canary-123" not in text
    assert "tok-canary" not in text
    # The path and its discipline are named, content never quoted.
    assert ".secrets/" in text


def test_directory_map_table_structure():
    text = render_manual(SAMPLE_FACTS)
    header_idx = text.index("| Path |")
    for path in (
        "`init.json`",
        "`system/`",
        "`system/lingtai.md`",
        "`system/pad.md`",
        "`system/pad_append.json`",
        "`system/summaries/`",
        "`knowledge/`",
        "`.library/`",
        "`taskcard/`",
        "`history/`",
        "`logs/`",
        "`.secrets/`",
        "`delegates/`",
        "`mail/`",
    ):
        row_idx = text.index(f"| {path} |")
        assert row_idx > header_idx
        row = text[row_idx:].splitlines()[0]
        # Path | What | Maintainer | Editable | Rules -> 6 pipes per row.
        assert row.count("|") == 6


def test_no_overlay_mechanism_referenced():
    text = render_manual(SAMPLE_FACTS)
    assert "MANUAL.local" not in text
    assert "overlay" not in text.lower()


def test_rendering_is_deterministic():
    assert render_manual(SAMPLE_FACTS) == render_manual(SAMPLE_FACTS)
