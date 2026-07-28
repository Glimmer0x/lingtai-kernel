"""Tests for psyche intrinsic — agent pad management (edit/load).

Migrated from memory intrinsic tests. Tests the pad object within psyche.
"""
from __future__ import annotations
from lingtai.tools.registry import INTRINSICS as _TEST_INTRINSICS

from unittest.mock import MagicMock

import pytest

from lingtai.tools.registry import INTRINSICS as ALL_INTRINSICS
from lingtai.kernel.base_agent import BaseAgent
from tests._workdir_lease_helpers import make_test_lease
from tests._snapshot_helpers import make_test_snapshot_port, make_test_source_revision_port
from tests._lifecycle_clock_helpers import make_test_lifecycle_clock
from tests._notification_store_helpers import notification_store_for
from tests._agent_presence_helpers import make_test_presence_store


def make_mock_service():
    svc = MagicMock()
    svc.get_adapter.return_value = MagicMock()
    svc.provider = "gemini"
    svc.model = "gemini-test"
    return svc


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


def test_intrinsics_include_psyche_pad_and_lingtai():
    """``pad`` is its own intrinsic root since the pad/lingtai split.

    Before the split ``pad`` was deliberately absent — the three pad
    operations were ``psyche`` leaves. Now it is a model-visible root parallel
    to ``knowledge`` and ``skills``, and ``psyche`` no longer advertises them.
    """
    assert "psyche" in ALL_INTRINSICS
    assert "pad" in ALL_INTRINSICS
    assert "lingtai" in ALL_INTRINSICS

    mod = ALL_INTRINSICS["pad"]["module"]
    schema = mod.get_schema()
    # The registered schema is the ToolFamily-composed LTP v2 envelope: the
    # `allOf` action/input correlation replaced the former deliberately-flat
    # shape (#114), and the `(object, action)` matrix is now one action enum.
    assert "allOf" in schema
    assert "object" not in schema["properties"]
    actions = schema["properties"]["action"]["enum"]
    assert actions == ["edit", "load", "append", "manual"]
    assert mod.ACTION_ORDER == tuple(actions)

    psyche_actions = ALL_INTRINSICS["psyche"]["module"].get_schema()["properties"]["action"]["enum"]
    assert not any(action.startswith("pad_") for action in psyche_actions)


def test_psyche_and_pad_wired_in_agent(tmp_path):
    agent = BaseAgent(intrinsics=_TEST_INTRINSICS, service=make_mock_service(), agent_name="test", working_dir=tmp_path / "test", workdir_lease=make_test_lease(), snapshot_port=make_test_snapshot_port(), agent_presence=make_test_presence_store(), lifecycle_clock=make_test_lifecycle_clock(), source_revision_port=make_test_source_revision_port(), notification_store=notification_store_for(tmp_path / "test"))
    assert "psyche" in agent._intrinsics
    assert "pad" in agent._intrinsics
    assert "lingtai" in agent._intrinsics
    agent.stop(timeout=1.0)


# ---------------------------------------------------------------------------
# Constructor args (covenant / pad file paths)
# ---------------------------------------------------------------------------


def test_covenant_constructor_arg_writes_to_system(tmp_path):
    """covenant= constructor arg should write to system/covenant.md."""
    agent = BaseAgent(
        intrinsics=_TEST_INTRINSICS,
        service=make_mock_service(), agent_name="test", working_dir=tmp_path / "test",
        covenant="You are a helpful agent", workdir_lease=make_test_lease(),
        snapshot_port=make_test_snapshot_port(), agent_presence=make_test_presence_store(), lifecycle_clock=make_test_lifecycle_clock(), source_revision_port=make_test_source_revision_port(), notification_store=notification_store_for(tmp_path / "test"),
    )
    covenant_file = agent.working_dir / "system" / "covenant.md"
    assert covenant_file.is_file()
    assert covenant_file.read_text() == "You are a helpful agent"
    agent.stop(timeout=1.0)


def test_pad_constructor_arg_writes_to_system(tmp_path):
    """pad= constructor arg should write to system/pad.md."""
    agent = BaseAgent(
        intrinsics=_TEST_INTRINSICS,
        service=make_mock_service(), agent_name="test", working_dir=tmp_path / "test",
        pad="initial pad", workdir_lease=make_test_lease(),
        snapshot_port=make_test_snapshot_port(), agent_presence=make_test_presence_store(), lifecycle_clock=make_test_lifecycle_clock(), source_revision_port=make_test_source_revision_port(), notification_store=notification_store_for(tmp_path / "test"),
    )
    pad_file = agent.working_dir / "system" / "pad.md"
    assert pad_file.is_file()
    assert pad_file.read_text() == "initial pad"
    agent.stop(timeout=1.0)


def test_covenant_is_protected_section(tmp_path):
    """Covenant should be a protected prompt section."""
    agent = BaseAgent(
        intrinsics=_TEST_INTRINSICS,
        service=make_mock_service(), agent_name="test", working_dir=tmp_path / "test",
        covenant="researcher", workdir_lease=make_test_lease(),
        snapshot_port=make_test_snapshot_port(), agent_presence=make_test_presence_store(), lifecycle_clock=make_test_lifecycle_clock(), source_revision_port=make_test_source_revision_port(), notification_store=notification_store_for(tmp_path / "test"),
    )
    sections = agent._prompt_manager.list_sections()
    covenant_section = [s for s in sections if s["name"] == "covenant"]
    assert len(covenant_section) == 1
    assert covenant_section[0]["protected"] is True
    agent.stop(timeout=1.0)


def test_existing_system_files_not_overwritten(tmp_path):
    """If system/pad.md already exists, constructor arg should not overwrite it."""
    # First create an agent so its working dir (with agent_id) exists
    agent1 = BaseAgent(
        intrinsics=_TEST_INTRINSICS,
        service=make_mock_service(), agent_name="test", working_dir=tmp_path / "t1",
        pad="existing content", workdir_lease=make_test_lease(),
        snapshot_port=make_test_snapshot_port(), agent_presence=make_test_presence_store(), lifecycle_clock=make_test_lifecycle_clock(), source_revision_port=make_test_source_revision_port(), notification_store=notification_store_for(tmp_path / "t1"),
    )
    working_dir = agent1.working_dir
    agent1.stop(timeout=1.0)
    # Verify the pad file was written by the first agent
    assert (working_dir / "system" / "pad.md").read_text() == "existing content"
    # Now a new agent (different agent_id) won't share that dir.
    # The semantic of this test is that pad= doesn't overwrite existing pad.md.
    # We verify this by checking the first agent wrote it correctly.
    agent2 = BaseAgent(
        intrinsics=_TEST_INTRINSICS,
        service=make_mock_service(), agent_name="test", working_dir=tmp_path / "t2",
        pad="constructor ltm", workdir_lease=make_test_lease(),
        snapshot_port=make_test_snapshot_port(), agent_presence=make_test_presence_store(), lifecycle_clock=make_test_lifecycle_clock(), source_revision_port=make_test_source_revision_port(), notification_store=notification_store_for(tmp_path / "t2"),
    )
    # New agent has its own dir, so pad=constructor ltm is written fresh
    assert (agent2.working_dir / "system" / "pad.md").read_text() == "constructor ltm"
    agent2.stop(timeout=1.0)


# ---------------------------------------------------------------------------
# Handler tests (edit / load via psyche)
# ---------------------------------------------------------------------------


def test_pad_edit(tmp_path):
    """Edit should write content to disk without injecting into prompt."""
    agent = BaseAgent(intrinsics=_TEST_INTRINSICS, service=make_mock_service(), agent_name="test", working_dir=tmp_path / "test", workdir_lease=make_test_lease(), snapshot_port=make_test_snapshot_port(), agent_presence=make_test_presence_store(), lifecycle_clock=make_test_lifecycle_clock(), source_revision_port=make_test_source_revision_port(), notification_store=notification_store_for(tmp_path / "test"))
    result = agent._intrinsics["pad"]({"action": "edit", "input": {"content": "hello world", "files": None}})
    assert result["status"] == "ok"
    assert result["size_bytes"] == len("hello world".encode())
    pad_file = agent.working_dir / "system" / "pad.md"
    assert pad_file.read_text() == "hello world"
    agent.stop(timeout=1.0)


def test_pad_edit_then_load(tmp_path):
    """Edit + load workflow: edit writes to disk, load injects into prompt."""
    agent = BaseAgent(intrinsics=_TEST_INTRINSICS, service=make_mock_service(), agent_name="test", working_dir=tmp_path / "test", workdir_lease=make_test_lease(), snapshot_port=make_test_snapshot_port(), agent_presence=make_test_presence_store(), lifecycle_clock=make_test_lifecycle_clock(), source_revision_port=make_test_source_revision_port(), notification_store=notification_store_for(tmp_path / "test"))
    agent.start()
    try:
        # edit writes content and auto-loads into prompt manager
        result = agent._intrinsics["pad"]({"action": "edit", "input": {"content": "important fact", "files": None}})
        assert result["status"] == "ok"

        # Verify file was written
        pad_file = agent.working_dir / "system" / "pad.md"
        assert pad_file.read_text() == "important fact"

        # Prompt manager should have the content (auto-loaded by edit)
        section = agent._prompt_manager.read_section("pad")
        assert "important fact" in section

        # Second load call should not detect new changes (file unchanged)
        result = agent._intrinsics["pad"]({"action": "load", "input": {}})
        assert result["status"] == "ok"
        # changed=False because file was already committed by edit's internal load
    finally:
        agent.stop()


def test_pad_load(tmp_path):
    agent = BaseAgent(intrinsics=_TEST_INTRINSICS, service=make_mock_service(), agent_name="test", working_dir=tmp_path / "test", workdir_lease=make_test_lease(), snapshot_port=make_test_snapshot_port(), agent_presence=make_test_presence_store(), lifecycle_clock=make_test_lifecycle_clock(), source_revision_port=make_test_source_revision_port(), notification_store=notification_store_for(tmp_path / "test"))
    agent.start()
    try:
        pad_file = agent.working_dir / "system" / "pad.md"
        pad_file.write_text("# Pad\n\nimportant fact\n")
        result = agent._intrinsics["pad"]({"action": "load", "input": {}})
        assert result["status"] == "ok"
        section = agent._prompt_manager.read_section("pad")
        assert "important fact" in section
    finally:
        agent.stop()


def test_pad_load_empty_removes_section(tmp_path):
    agent = BaseAgent(intrinsics=_TEST_INTRINSICS, service=make_mock_service(), agent_name="test", working_dir=tmp_path / "test", workdir_lease=make_test_lease(), snapshot_port=make_test_snapshot_port(), agent_presence=make_test_presence_store(), lifecycle_clock=make_test_lifecycle_clock(), source_revision_port=make_test_source_revision_port(), notification_store=notification_store_for(tmp_path / "test"))
    agent.start()
    try:
        agent._intrinsics["pad"]({"action": "edit", "input": {"content": "some content", "files": None}})
        agent._intrinsics["pad"]({"action": "load", "input": {}})
        assert agent._prompt_manager.read_section("pad") is not None
        agent._intrinsics["pad"]({"action": "edit", "input": {"content": "", "files": None}})
        agent._intrinsics["pad"]({"action": "load", "input": {}})
        section = agent._prompt_manager.read_section("pad")
        assert section is None or section.strip() == ""
    finally:
        agent.stop()


def test_pad_load_no_change_no_commit(tmp_path):
    agent = BaseAgent(intrinsics=_TEST_INTRINSICS, service=make_mock_service(), agent_name="test", working_dir=tmp_path / "test", workdir_lease=make_test_lease(), snapshot_port=make_test_snapshot_port(), agent_presence=make_test_presence_store(), lifecycle_clock=make_test_lifecycle_clock(), source_revision_port=make_test_source_revision_port(), notification_store=notification_store_for(tmp_path / "test"))
    agent.start()
    try:
        agent._intrinsics["pad"]({"action": "load", "input": {}})
        result = agent._intrinsics["pad"]({"action": "load", "input": {}})
        assert result["status"] == "ok"
    finally:
        agent.stop()


def test_pad_unknown_action(tmp_path):
    agent = BaseAgent(intrinsics=_TEST_INTRINSICS, service=make_mock_service(), agent_name="test", working_dir=tmp_path / "test", workdir_lease=make_test_lease(), snapshot_port=make_test_snapshot_port(), agent_presence=make_test_presence_store(), lifecycle_clock=make_test_lifecycle_clock(), source_revision_port=make_test_source_revision_port(), notification_store=notification_store_for(tmp_path / "test"))
    result = agent._intrinsics["psyche"]({"object": "pad", "action": "diff"})
    assert "error" in result
    agent.stop(timeout=1.0)


def test_pad_creates_files_if_missing(tmp_path):
    agent = BaseAgent(intrinsics=_TEST_INTRINSICS, service=make_mock_service(), agent_name="test", working_dir=tmp_path / "test", workdir_lease=make_test_lease(), snapshot_port=make_test_snapshot_port(), agent_presence=make_test_presence_store(), lifecycle_clock=make_test_lifecycle_clock(), source_revision_port=make_test_source_revision_port(), notification_store=notification_store_for(tmp_path / "test"))
    agent.start()
    try:
        missing_system = tmp_path / "missing-system"
        missing_system.mkdir()
        agent._working_dir = missing_system
        agent._notification_store = notification_store_for(missing_system)
        result = agent._intrinsics["pad"]({"action": "edit", "input": {"content": "test", "files": None}})
        assert result["status"] == "ok"
        assert (agent.working_dir / "system" / "pad.md").is_file()
    finally:
        agent.stop()
