"""Pad durable-source and append-list tests.

Generic body mutation is covered by the file family. Pad's public ownership is
limited to append-list persistence plus its manual signpost.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

from lingtai.kernel.base_agent import BaseAgent
from lingtai.tools.registry import INTRINSICS as _TEST_INTRINSICS
from tests._agent_presence_helpers import make_test_presence_store
from tests._lifecycle_clock_helpers import make_test_lifecycle_clock
from tests._notification_store_helpers import notification_store_for
from tests._snapshot_helpers import make_test_snapshot_port, make_test_source_revision_port
from tests._workdir_lease_helpers import make_test_lease


def make_mock_service():
    svc = MagicMock()
    svc.get_adapter.return_value = MagicMock()
    svc.provider = "gemini"
    svc.model = "gemini-test"
    return svc


def _agent(tmp_path, name="test", **kwargs):
    workdir = tmp_path / name
    return BaseAgent(
        intrinsics=_TEST_INTRINSICS,
        service=make_mock_service(),
        agent_name=name,
        working_dir=workdir,
        workdir_lease=make_test_lease(),
        snapshot_port=make_test_snapshot_port(),
        source_revision_port=make_test_source_revision_port(),
        agent_presence=make_test_presence_store(),
        lifecycle_clock=make_test_lifecycle_clock(),
        notification_store=notification_store_for(workdir),
        **kwargs,
    )


def test_registered_pad_inventory_is_append_and_manual_only():
    from lingtai.tools.registry import INTRINSICS

    module = INTRINSICS["pad"]["module"]
    assert module.get_schema()["properties"]["action"]["enum"] == ["append", "manual"]
    assert module.ACTION_ORDER == ("append", "manual")
    assert "psyche" not in INTRINSICS


def test_context_pad_and_lingtai_are_wired(tmp_path):
    agent = _agent(tmp_path)
    try:
        assert {"context", "pad", "lingtai"} <= set(agent._intrinsics)
    finally:
        agent.stop(timeout=1.0)


def test_covenant_constructor_arg_writes_protected_section(tmp_path):
    agent = _agent(tmp_path, covenant="You are a helpful agent")
    try:
        path = agent.working_dir / "system" / "covenant.md"
        assert path.read_text() == "You are a helpful agent"
        section = next(s for s in agent._prompt_manager.list_sections() if s["name"] == "covenant")
        assert section["protected"] is True
    finally:
        agent.stop(timeout=1.0)


def test_pad_constructor_arg_seeds_disk_and_prompt(tmp_path):
    agent = _agent(tmp_path, pad="initial pad")
    try:
        assert (agent.working_dir / "system" / "pad.md").read_text() == "initial pad"
        assert agent._prompt_manager.read_section("pad") == "initial pad"
    finally:
        agent.stop(timeout=1.0)


def test_pad_append_query_does_not_create_or_load_a_list(tmp_path):
    agent = _agent(tmp_path)
    try:
        agent._prompt_manager.write_section("pad", "CURRENT")
        result = agent._intrinsics["pad"]({"action": "append", "input": {"files": None}})
        assert result["status"] == "ok"
        assert result["files"] == []
        assert result["prompt_reload"] is False
        assert agent._prompt_manager.read_section("pad") == "CURRENT"
        assert not (agent.working_dir / "system" / "pad_append.json").exists()
    finally:
        agent.stop(timeout=1.0)


def test_pad_append_set_and_clear_only_persist(tmp_path):
    agent = _agent(tmp_path)
    try:
        ref = agent.working_dir / "ref.md"
        ref.write_text("reference", encoding="utf-8")
        agent._prompt_manager.write_section("pad", "CURRENT")

        result = agent._intrinsics["pad"]({
            "action": "append", "input": {"files": ["ref.md"]},
        })
        assert result["action"] == "set"
        assert result["prompt_reload"] is False
        assert "context.rebuild" in result["takes_effect"]
        append_path = agent.working_dir / "system" / "pad_append.json"
        assert json.loads(append_path.read_text()) == ["ref.md"]
        assert agent._prompt_manager.read_section("pad") == "CURRENT"

        result = agent._intrinsics["pad"]({"action": "append", "input": {"files": []}})
        assert result["action"] == "cleared"
        assert json.loads(append_path.read_text()) == []
        assert agent._prompt_manager.read_section("pad") == "CURRENT"
    finally:
        agent.stop(timeout=1.0)


def test_pad_append_rejects_missing_or_binary_files(tmp_path):
    agent = _agent(tmp_path)
    try:
        result = agent._intrinsics["pad"]({
            "action": "append", "input": {"files": ["missing.md"]},
        })
        assert "missing.md" in result["error"]
        binary = agent.working_dir / "binary.dat"
        binary.write_bytes(b"a\x00b")
        result = agent._intrinsics["pad"]({
            "action": "append", "input": {"files": ["binary.dat"]},
        })
        assert "Binary files" in result["error"]
    finally:
        agent.stop(timeout=1.0)


def test_retired_pad_edit_and_load_fail_without_mutation(tmp_path):
    agent = _agent(tmp_path, pad="keep")
    try:
        for action in ("edit", "load"):
            result = agent._intrinsics["pad"]({"action": action, "input": {}})
            assert "Unknown pad action" in result["error"]
        assert (agent.working_dir / "system" / "pad.md").read_text() == "keep"
    finally:
        agent.stop(timeout=1.0)


def test_stop_does_not_overwrite_pad_md(tmp_path):
    agent = _agent(tmp_path)
    path = agent.working_dir / "system" / "pad.md"
    path.write_text("previous session pad")
    agent.stop()
    assert path.read_text() == "previous session pad"
