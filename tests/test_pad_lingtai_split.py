"""Focused LTP v2 evidence for the final Pad/LingTai public split."""
from __future__ import annotations

import json

import pytest

from lingtai.agent import Agent
from lingtai.tools import context as context_tool
from lingtai.tools import lingtai as lingtai_tool
from lingtai.tools import pad as pad_tool
from tests._service_helpers import make_gemini_mock_service as make_mock_service


def _agent(tmp_path, **kwargs):
    return Agent(
        service=make_mock_service(), agent_name="test",
        working_dir=tmp_path / "test", **kwargs,
    )


def _call(agent, root, action, action_input):
    return agent._intrinsics[root]({"action": action, "input": action_input})


def test_exact_final_action_inventories_and_no_context_aliases():
    assert pad_tool.ACTION_ORDER == ("append", "manual")
    assert pad_tool.get_schema()["properties"]["action"]["enum"] == ["append", "manual"]
    assert lingtai_tool.ACTION_ORDER == ("manual",)
    assert lingtai_tool.get_schema()["properties"]["action"]["enum"] == ["manual"]
    assert context_tool.ACTION_ORDER == ("molt", "summarize", "rebuild", "manual")
    actions = context_tool.get_schema()["properties"]["action"]["enum"]
    for retired in (
        "pad_edit", "pad_load", "pad_append", "lingtai_update", "lingtai_load",
    ):
        assert retired not in actions


def test_each_root_registered_once_and_wired_once(tmp_path):
    from lingtai.tools.registry import BUILTIN_TOOLS, INTRINSICS

    assert INTRINSICS["pad"]["module"] is pad_tool
    assert INTRINSICS["lingtai"]["module"] is lingtai_tool
    assert INTRINSICS["context"]["module"] is context_tool
    assert len({id(pad_tool), id(lingtai_tool), id(context_tool)}) == 3
    for name in ("pad", "lingtai", "context"):
        assert name not in BUILTIN_TOOLS

    agent = _agent(tmp_path)
    try:
        schema_names = [s.name for s in agent._build_tool_schemas()]
        for name in ("pad", "lingtai", "context"):
            assert schema_names.count(name) == 1
    finally:
        agent.stop(timeout=1.0)


@pytest.mark.parametrize("module", [pad_tool, lingtai_tool])
def test_roots_use_the_closed_strict_ltp_v2_envelope(module):
    schema = module.get_schema()
    assert set(schema["properties"]) == {"action", "input", "reasoning", "summarize"}
    assert schema["required"] == ["action", "input", "reasoning"]
    assert schema["additionalProperties"] is False
    assert schema["properties"]["summarize"]["type"] == "boolean"
    advertised = schema["properties"]["action"]["enum"]
    correlated = [c["if"]["properties"]["action"]["const"] for c in schema["allOf"]]
    assert advertised == list(module.ACTION_ORDER) == correlated
    for cond in schema["allOf"]:
        assert cond["then"]["properties"]["input"]["additionalProperties"] is False


def test_each_action_advertises_only_its_owned_input():
    pad_props = {
        c["if"]["properties"]["action"]["const"]:
            set(c["then"]["properties"]["input"]["properties"])
        for c in pad_tool.get_schema()["allOf"]
    }
    assert pad_props == {"append": {"files"}, "manual": set()}
    lingtai_props = {
        c["if"]["properties"]["action"]["const"]:
            set(c["then"]["properties"]["input"]["properties"])
        for c in lingtai_tool.get_schema()["allOf"]
    }
    assert lingtai_props == {"manual": set()}


def test_retired_actions_are_strictly_rejected_before_io(tmp_path):
    agent = _agent(tmp_path)
    try:
        before_pad = (agent._working_dir / "system" / "pad.md").read_text()
        for root, action in (
            ("pad", "edit"), ("pad", "load"),
            ("lingtai", "update"), ("lingtai", "load"),
        ):
            result = _call(agent, root, action, {})
            assert "error" in result
            assert f"Unknown {root} action" in result["error"]
        assert (agent._working_dir / "system" / "pad.md").read_text() == before_pad
        assert not (agent._working_dir / "system" / "lingtai.md").exists()
    finally:
        agent.stop(timeout=1.0)


@pytest.mark.parametrize(
    "root,action,action_input",
    [("pad", "append", {"files": None}), ("pad", "manual", {}), ("lingtai", "manual", {})],
)
def test_valid_actions_reject_unknown_envelope_fields_and_nonbool_summarize(
    tmp_path, root, action, action_input
):
    agent = _agent(tmp_path)
    try:
        call = agent._intrinsics[root]
        result = call({"action": action, "input": action_input, "mystery": 1})
        assert result["status"] == "failed"
        assert result["error_code"] == "INVALID_ARGUMENT"
        result = call({"action": action, "input": action_input, "summarize": "yes"})
        assert result["status"] == "failed"
        assert result["error_code"] == "INVALID_ARGUMENT"
    finally:
        agent.stop(timeout=1.0)


@pytest.mark.parametrize("root", ["pad", "lingtai"])
def test_manual_rejects_nonobject_or_nonempty_input(tmp_path, root):
    agent = _agent(tmp_path)
    try:
        result = agent._intrinsics[root]({"action": "manual", "input": "bad"})
        assert result["status"] == "failed"
        assert result["error_code"] == "INVALID_ARGUMENT"
        result = agent._intrinsics[root]({"action": "manual", "input": {"content": "x"}})
        assert result["status"] == "failed"
        assert result["error_code"] == "INVALID_ARGUMENT"
    finally:
        agent.stop(timeout=1.0)


def test_pad_append_persists_without_loading_then_rebuild_composes(tmp_path):
    agent = _agent(tmp_path)
    try:
        (agent._working_dir / "system" / "pad.md").write_text("pad body", encoding="utf-8")
        (agent._working_dir / "ref.txt").write_text("pinned reference", encoding="utf-8")
        agent._prompt_manager.write_section("pad", "CURRENT")

        query = _call(agent, "pad", "append", {"files": None})
        assert query["files"] == []
        assert query["prompt_reload"] is False

        result = _call(agent, "pad", "append", {"files": ["ref.txt"]})
        assert result["status"] == "ok"
        assert result["action"] == "set"
        assert result["prompt_reload"] is False
        assert "context.rebuild" in result["takes_effect"]
        assert json.loads(
            (agent._working_dir / "system" / "pad_append.json").read_text()
        ) == ["ref.txt"]
        assert agent._prompt_manager.read_section("pad") == "CURRENT"

        agent._reconstruct_context()
        assert "pad body" in agent._prompt_manager.read_section("pad")
        assert "pinned reference" in agent._prompt_manager.read_section("pad")
    finally:
        agent.stop(timeout=1.0)


def test_pad_append_rejects_missing_and_binary_without_persisting(tmp_path):
    agent = _agent(tmp_path)
    try:
        result = _call(agent, "pad", "append", {"files": ["missing.txt"]})
        assert "Files not found" in result["error"]
        binary = agent._working_dir / "blob.bin"
        binary.write_bytes(b"\x00\x01")
        result = _call(agent, "pad", "append", {"files": ["blob.bin"]})
        assert "Only text files" in result["error"]
        assert not (agent._working_dir / "system" / "pad_append.json").exists()
    finally:
        agent.stop(timeout=1.0)


def _install_manual(workdir, skill_name):
    path = workdir / ".library" / "intrinsic" / "capabilities" / skill_name / "SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    body = f"---\nname: {skill_name}\n---\n\n# {skill_name}\n"
    path.write_text(body, encoding="utf-8")
    return body, path


@pytest.mark.parametrize(
    "root,skill", [("pad", "pad-manual"), ("lingtai", "lingtai-manual"), ("context", "context-manual")],
)
def test_reserved_manual_is_family_correct_and_flattened_once(tmp_path, root, skill):
    agent = _agent(tmp_path)
    try:
        body, path = _install_manual(agent._working_dir, skill)
        result = _call(agent, root, "manual", {})
        assert result == {"status": "ok", "manual": body, "manual_path": str(path)}
    finally:
        agent.stop(timeout=1.0)


def test_lingtai_manual_only_survives_both_provider_wires(tmp_path):
    from lingtai.llm.openai.adapter import _scrub_responses_schema

    agent = _agent(tmp_path)
    try:
        schema = next(s.parameters for s in agent._build_tool_schemas() if s.name == "lingtai")
        for wire in (schema, _scrub_responses_schema(schema)):
            assert wire["properties"]["action"]["enum"] == ["manual"]
            assert wire["required"] == ["action", "input", "reasoning"]
            assert wire["additionalProperties"] is False
    finally:
        agent.stop(timeout=1.0)


def test_allowlist_blacklist_and_glossary_boundaries():
    from lingtai.kernel.tool_result_summary import _LTP_V2_MIGRATED_FAMILIES
    from lingtai.tools.daemon import EMANATION_BLACKLIST
    from lingtai.tools.glossary_validator import validate_package

    for root in ("pad", "lingtai", "context"):
        assert root in _LTP_V2_MIGRATED_FAMILIES
        assert root in EMANATION_BLACKLIST
    for package in ("pad", "lingtai"):
        assert validate_package(package) == []


def test_one_post_molt_hook_reconstructs_both_internal_sections(tmp_path):
    agent = _agent(tmp_path)
    try:
        system = agent._working_dir / "system"
        system.mkdir(exist_ok=True)
        (system / "pad.md").write_text("pad body", encoding="utf-8")
        (system / "lingtai.md").write_text("who I am", encoding="utf-8")
        agent._prompt_manager.delete_section("pad")
        agent._prompt_manager.delete_section("character")
        assert agent._post_molt_hooks == [agent._reconstruct_context]
        agent._post_molt_hooks[0]()
        assert "pad body" in agent._prompt_manager.read_section("pad")
        assert "who I am" in agent._prompt_manager.read_section("character")
        assert not hasattr(context_tool, "_pad_load")
        assert not hasattr(context_tool, "_lingtai_load")
    finally:
        agent.stop(timeout=1.0)
