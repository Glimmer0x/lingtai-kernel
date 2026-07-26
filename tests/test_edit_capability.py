"""Independent public action/input contract tests for the edit capability.

These tests deliberately exercise the handler directly as well as the schema
surfaces. They are edit-owned; shared file-capability compatibility tests are
not changed by this migration.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from lingtai.agent import Agent
from lingtai.llm.anthropic.adapter import _build_tools as build_anthropic_tools
from lingtai.llm.openai.adapter import (
    _build_responses_tools,
    _build_tools as build_chat_tools,
)
from lingtai.tools.edit import get_description, get_schema
from tests._service_helpers import make_gemini_mock_service as make_mock_service



def _agent(tmp_path: Path) -> Agent:
    return Agent(
        service=make_mock_service(),
        agent_name="edit-contract-test",
        working_dir=tmp_path / "agent",
        capabilities=["edit"],
    )


def _edit_call(agent: Agent, **payload):
    return agent._tool_handlers["edit"](payload)


def _explicit(path: str, old: str, new: str, replace_all=None) -> dict:
    input_value = {"file_path": path, "old_string": old, "new_string": new}
    if replace_all is not ...:
        input_value["replace_all"] = replace_all
    return {"action": "edit", "input": input_value}


def _without_setting(value: dict) -> dict:
    return {key: item for key, item in value.items() if key != "current_setting"}


def test_raw_schema_is_closed_action_input():
    schema = get_schema()
    assert set(schema) == {"type", "properties", "required", "additionalProperties"}
    assert set(schema["properties"]) == {"action", "input"}
    assert schema["required"] == ["action", "input"]
    assert schema["additionalProperties"] is False

    branches = schema["properties"]["input"]["anyOf"]
    edit_branch = next(branch for branch in branches if branch["title"] == "edit input")
    manual_branch = next(branch for branch in branches if branch["title"] == "manual input")
    assert set(edit_branch["properties"]) == {
        "file_path", "old_string", "new_string", "replace_all"
    }
    assert edit_branch["required"] == [
        "file_path", "old_string", "new_string", "replace_all"
    ]
    assert edit_branch["additionalProperties"] is False
    assert edit_branch["properties"]["replace_all"]["type"] == ["boolean", "null"]
    assert manual_branch["properties"] == {}
    assert manual_branch["required"] == []
    assert manual_branch["additionalProperties"] is False


def test_agent_schema_has_only_action_input_reasoning(tmp_path):
    agent = _agent(tmp_path)
    try:
        schema = next(item for item in agent._build_tool_schemas() if item.name == "edit")
        assert set(schema.parameters["properties"]) == {"action", "input", "reasoning"}
        assert schema.parameters["required"] == ["action", "input"]
        assert schema.parameters["additionalProperties"] is False
        for branch in schema.parameters["properties"]["input"]["anyOf"]:
            assert "reasoning" not in branch.get("properties", {})
    finally:
        agent.stop(timeout=1.0)


def test_provider_envelopes_keep_public_fields(tmp_path):
    agent = _agent(tmp_path)
    try:
        schema = next(item for item in agent._build_tool_schemas() if item.name == "edit")
        chat = build_chat_tools([schema])[0]
        responses = _build_responses_tools([schema])[0]
        anthropic = build_anthropic_tools([schema], cache_tools=False)[0]

        assert set(chat) == {"type", "function"}
        assert set(chat["function"]) == {"name", "description", "parameters"}
        assert set(responses) == {"type", "name", "description", "parameters"}
        assert set(anthropic) == {"name", "description", "input_schema"}
        for parameters in (
            chat["function"]["parameters"],
            responses["parameters"],
            anthropic["input_schema"],
        ):
            assert set(parameters["properties"]) == {"action", "input", "reasoning"}
            assert parameters["required"] == ["action", "input"]
            assert parameters["additionalProperties"] is False
    finally:
        agent.stop(timeout=1.0)


def test_prompt_batches_and_canonical_description(tmp_path):
    agent = _agent(tmp_path)
    try:
        prompt = agent._build_system_prompt()
        batches = agent._build_system_prompt_batches()
        joined = "\n\n".join(batch for batch in batches if batch)
        assert prompt == joined
        assert "### edit" in prompt
        assert "action='edit'" in prompt
        assert "nested input" in prompt
        assert "omit action for the legacy" not in prompt
        assert "action='edit'" in joined
    finally:
        agent.stop(timeout=1.0)


def test_edit_replacement_and_defaults(tmp_path):
    agent = _agent(tmp_path)
    try:
        target = agent.working_dir / "replace.txt"
        target.write_text("alpha beta alpha", encoding="utf-8")

        ambiguous = _edit_call(agent, **_explicit(str(target), "alpha", "omega", None))
        assert ambiguous["status"] == "error"
        assert "2 times" in ambiguous["message"]
        assert "current_setting" in ambiguous
        assert target.read_text(encoding="utf-8") == "alpha beta alpha"

        all_result = _edit_call(agent, **_explicit(str(target), "alpha", "omega", True))
        assert _without_setting(all_result) == {"status": "ok", "replacements": 2}
        assert target.read_text(encoding="utf-8") == "omega beta omega"

        target.write_text("one two", encoding="utf-8")
        omitted = _edit_call(agent, **_explicit(str(target), "one", "ONE", ...))
        assert _without_setting(omitted) == {"status": "ok", "replacements": 1}
        assert target.read_text(encoding="utf-8") == "ONE two"
    finally:
        agent.stop(timeout=1.0)


def test_null_replace_all_preserves_false_and_reasoning_is_metadata(tmp_path):
    agent = _agent(tmp_path)
    try:
        target = agent.working_dir / "null.txt"
        target.write_text("x x", encoding="utf-8")
        result = _edit_call(
            agent,
            **_explicit(str(target), "x", "y", None),
            reasoning="public explanation",
            _reasoning="executor explanation",
        )
        assert result["status"] == "error"
        assert "2 times" in result["message"]
        assert target.read_text(encoding="utf-8") == "x x"
    finally:
        agent.stop(timeout=1.0)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"file_path": "x", "old_string": "a", "new_string": "b"},
        {"action": "edit", "input": {"file_path": "x", "old_string": "a", "new_string": "b"}, "extra": 1},
    ],
)
def test_missing_flat_and_unknown_root_calls_are_rejected(tmp_path, payload):
    agent = _agent(tmp_path)
    try:
        result = _edit_call(agent, **payload)
        assert result["status"] == "error"
        assert "current_setting" in result
    finally:
        agent.stop(timeout=1.0)


@pytest.mark.parametrize("bad_root", [None, [], "edit", 3])
def test_nonmapping_root_is_structured_error(tmp_path, bad_root):
    agent = _agent(tmp_path)
    try:
        result = agent._tool_handlers["edit"](bad_root)
        assert result["status"] == "error"
        assert "current_setting" in result
    finally:
        agent.stop(timeout=1.0)


@pytest.mark.parametrize(
    "payload",
    [
        {"action": "edit", "input": []},
        {"action": "edit", "input": {"file_path": 4, "old_string": "a", "new_string": "b", "replace_all": None}},
        {"action": "edit", "input": {"file_path": "x", "old_string": "a", "new_string": "b", "replace_all": "yes"}},
        {"action": "manual", "input": {"unexpected": True}},
    ],
)
def test_wrong_input_types_and_closed_branches_are_rejected(tmp_path, payload):
    agent = _agent(tmp_path)
    try:
        result = _edit_call(agent, **payload)
        assert result["status"] == "error"
        assert "current_setting" in result
    finally:
        agent.stop(timeout=1.0)


@pytest.mark.parametrize("action", ["write", "", 4, [], {}])
def test_unknown_and_unhashable_actions_are_safe(tmp_path, action):
    agent = _agent(tmp_path)
    try:
        result = _edit_call(agent, action=action, input={})
        assert result["status"] == "error"
        assert "Unsupported action for edit" in result["message"]
        assert "current_setting" in result
    finally:
        agent.stop(timeout=1.0)


def test_manual_returns_installed_body(tmp_path):
    agent = _agent(tmp_path)
    try:
        result = _edit_call(agent, action="manual", input={})
        assert result["status"] == "ok"
        assert result["manual"]
        assert "# File Manual" in result["manual"]
        assert "The `edit` action/input contract" in result["manual"]
        assert result["manual_path"].endswith("capabilities/file-manual/SKILL.md")
        assert "current_setting" in result
    finally:
        agent.stop(timeout=1.0)


def test_settings_are_attached_and_invariant(tmp_path):
    agent = _agent(tmp_path)
    try:
        target = agent.working_dir / "settings.txt"
        target.write_text("old", encoding="utf-8")
        settings = agent.working_dir / "settings" / "edit.json"
        settings.parent.mkdir(parents=True, exist_ok=True)

        missing = _edit_call(agent, **_explicit(str(target), "old", "missing", True))
        assert missing["current_setting"]["source"] == "missing"

        settings.write_text(json.dumps({"schema_version": 1}), encoding="utf-8")
        valid = _edit_call(agent, **_explicit(str(target), "missing", "valid", True))
        assert valid["current_setting"]["source"] == "settings/edit.json"
        assert _without_setting(valid) == {"status": "ok", "replacements": 1}

        settings.write_text(json.dumps({"schema_version": 1, "extra": False}), encoding="utf-8")
        invalid = _edit_call(agent, **_explicit(str(target), "valid", "invalid", True))
        assert invalid["current_setting"]["source"] == "settings_error"
        assert invalid["current_setting"]["settings_error"]
        assert _without_setting(invalid) == {"status": "ok", "replacements": 1}
        assert target.read_text(encoding="utf-8") == "invalid"
    finally:
        agent.stop(timeout=1.0)


def test_file_io_delegation_and_structured_failures(tmp_path):
    agent = _agent(tmp_path)
    try:
        calls = []
        target = agent.working_dir / "delegated.txt"
        target.write_text("old", encoding="utf-8")
        real_io = agent._file_io

        class SpyIO:
            def read(self, path):
                calls.append(("read", path))
                return real_io.read(path)

            def write(self, path, content):
                calls.append(("write", path, content))
                return real_io.write(path, content)

        agent._file_io = SpyIO()
        result = _edit_call(agent, **_explicit("delegated.txt", "old", "new", False))
        assert result["status"] == "ok"
        assert [call[0] for call in calls] == ["read", "write"]
        assert calls[0][1] == agent.working_dir / "delegated.txt"

        missing = _edit_call(agent, **_explicit("missing.txt", "old", "new", False))
        assert missing["status"] == "error"
        assert missing["message"].startswith("File not found:")
    finally:
        agent.stop(timeout=1.0)
