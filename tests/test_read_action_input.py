"""Independent public action/input contract tests for the ``read`` capability.

This module is read-owned. It deliberately tests the raw capability schema, the
actual Agent/provider surfaces, direct handler validation, settings evidence,
read semantics, and the executor's nested a-priori summary boundary. Shared
legacy file-tool tests are intentionally not rewritten here during rollout.
"""
from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from pathlib import Path
from uuid import uuid4

import pytest

from lingtai.agent import Agent
from lingtai.kernel.llm.base import WIRE_TOOL_DESCRIPTION, ToolCall
from lingtai.kernel.loop_guard import LoopGuard
from lingtai.kernel.tool_executor import ToolExecutor
from lingtai.llm.anthropic.adapter import _build_tools as build_anthropic_tools
from lingtai.llm.openai.adapter import (
    _build_responses_tools,
    _build_tools as build_chat_tools,
)
from lingtai.tools.read import get_description, get_schema
from tests._service_helpers import make_gemini_mock_service


class _UnhashableMapping(Mapping):
    """Mapping-shaped bad input whose key cannot be hashed."""

    def keys(self):
        return [[]]

    def __iter__(self):
        return iter([[]])

    def __len__(self):
        return 1

    def __getitem__(self, key):
        raise KeyError(key)


_ROOT = Path(__file__).resolve().parents[1]
_ARTIFACT_ROOT = _ROOT / "artifacts" / "read-action-input-worker" / "tests"


def _persistent_root(label: str) -> Path:
    """Return a unique retained test root; this suite never auto-cleans it."""
    root = _ARTIFACT_ROOT / f"{label}-{uuid4().hex}"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _agent(label: str = "agent") -> Agent:
    root = _persistent_root(label)
    return Agent(
        service=make_gemini_mock_service(),
        agent_name="read-contract-test",
        working_dir=root / "agent",
        capabilities=["read"],
    )


def _read_call(agent: Agent, **payload):
    return agent._tool_handlers["read"](payload)


def _explicit(path: str, **options) -> dict:
    value = {"file_path": path}
    value.update(options)
    return {"action": "read", "input": value}


def _without_setting(value: dict) -> dict:
    return {key: item for key, item in value.items() if key != "current_setting"}


def _write_settings(agent: Agent, value: str) -> Path:
    path = agent.working_dir / "settings" / "read.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")
    return path


def _make_executor(agent: Agent, *, events, summarizer, parallel_safe_tools=None):
    def logger(event_type, **fields):
        events.append((event_type, fields))

    def make_tool_result(name, result, **kwargs):
        return {"role": "tool", "name": name, "content": result, **kwargs}

    return ToolExecutor(
        dispatch_fn=agent._dispatch_tool,
        make_tool_result_fn=make_tool_result,
        guard=LoopGuard(),
        known_tools={"read"},
        logger_fn=logger,
        working_dir=agent.working_dir,
        summarizer_fn=summarizer,
        parallel_safe_tools=parallel_safe_tools or set(),
    )


def _wire_content(result_message):
    return result_message["content"]


def _event_index(events, event_type: str, call_id: str) -> int | None:
    for index, (kind, fields) in enumerate(events):
        if kind == event_type and fields.get("tool_call_id") == call_id:
            return index
    return None


def test_raw_schema_is_closed_action_input():
    schema = get_schema()
    assert set(schema) == {"type", "properties", "required", "additionalProperties"}
    assert set(schema["properties"]) == {"action", "input"}
    assert schema["required"] == ["action", "input"]
    assert schema["additionalProperties"] is False
    assert schema["properties"]["action"]["enum"] == ["read", "manual"]

    branches = schema["properties"]["input"]["anyOf"]
    read_branch = next(branch for branch in branches if branch["title"] == "read input")
    manual_branch = next(branch for branch in branches if branch["title"] == "manual input")
    assert set(read_branch["properties"]) == {
        "file_path", "offset", "limit", "max_chars", "summary"
    }
    assert read_branch["required"] == ["file_path"]
    assert read_branch["additionalProperties"] is False
    assert read_branch["properties"]["offset"]["type"] == "integer"
    assert read_branch["properties"]["offset"]["default"] == 1
    assert read_branch["properties"]["limit"]["type"] == "integer"
    assert read_branch["properties"]["limit"]["default"] == 2000
    assert read_branch["properties"]["max_chars"]["type"] == "integer"
    assert "default" not in read_branch["properties"]["max_chars"]
    assert read_branch["properties"]["summary"]["type"] == "boolean"
    assert read_branch["properties"]["summary"]["default"] is False
    assert "reasoning" not in read_branch["properties"]
    assert manual_branch["properties"] == {}
    assert manual_branch["required"] == []
    assert manual_branch["additionalProperties"] is False


def test_agent_schema_has_only_action_input_reasoning_and_real_origin():
    agent = _agent("schema")
    try:
        schema = next(item for item in agent._build_tool_schemas() if item.name == "read")
        assert set(schema.parameters["properties"]) == {"action", "input", "reasoning"}
        assert schema.parameters["required"] == ["action", "input"]
        assert schema.parameters["additionalProperties"] is False
        for branch in schema.parameters["properties"]["input"]["anyOf"]:
            assert "reasoning" not in branch.get("properties", {})
        assert Path(sys.modules["lingtai.tools.read"].__file__).resolve() == (
            _ROOT / "src/lingtai/tools/read/__init__.py"
        ).resolve()
        assert agent._tool_handlers["read"].__code__.co_filename == str(
            _ROOT / "src/lingtai/tools/read/__init__.py"
        )
    finally:
        agent.stop(timeout=1.0)


def test_provider_envelopes_keep_public_fields_and_wire_description():
    agent = _agent("envelopes")
    try:
        schema = next(item for item in agent._build_tool_schemas() if item.name == "read")
        chat = build_chat_tools([schema])[0]
        responses = _build_responses_tools([schema])[0]
        anthropic = build_anthropic_tools([schema], cache_tools=False)[0]

        assert set(chat) == {"type", "function"}
        assert set(chat["function"]) == {"name", "description", "parameters"}
        assert set(responses) == {"type", "name", "description", "parameters"}
        assert set(anthropic) == {"name", "description", "input_schema"}
        assert chat["function"]["description"] == WIRE_TOOL_DESCRIPTION
        assert responses["description"] == WIRE_TOOL_DESCRIPTION
        assert anthropic["description"] == WIRE_TOOL_DESCRIPTION
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


def test_prompt_batches_and_tool_owned_description_only():
    agent = _agent("prompt")
    try:
        prompt = agent._build_system_prompt()
        batches = agent._build_system_prompt_batches()
        joined = "\n\n".join(batch for batch in batches if batch)
        description = get_description()
        assert prompt == joined
        assert "### read" in prompt
        assert description in prompt
        assert "action='read'" in description
        assert "input={'file_path':" in description
        assert "reasoning='...'" in description
        assert "nested input" in description
        assert "omit action for the legacy" not in description
        assert "flat" not in description
        # The resident prompt also contains unmigrated sibling prose; only the
        # read-owned section is canonicalized by this test.
        read_section = prompt.split("### read", 1)[1]
        assert description in read_section
    finally:
        agent.stop(timeout=1.0)


def test_canonical_handler_calls_and_direct_metadata_reasoning():
    agent = _agent("canonical")
    try:
        target = agent.working_dir / "canonical.txt"
        target.write_text("one\ntwo\n", encoding="utf-8")
        direct = _read_call(agent, **_explicit("canonical.txt"), reasoning="why direct")
        normalized = _read_call(agent, **_explicit("canonical.txt"), _reasoning="why executor")
        assert _without_setting(direct)["content"] == _without_setting(normalized)["content"]
        assert direct["total_lines"] == 2
        assert direct["current_setting"]["source"] == "missing"

        flat = _read_call(agent, file_path="canonical.txt")
        assert flat["status"] == "error"
        assert "current_setting" in flat
    finally:
        agent.stop(timeout=1.0)


def test_file_io_delegation_uses_relative_workdir_path():
    agent = _agent("delegation")
    try:
        target = agent.working_dir / "delegated.txt"
        target.write_text("delegated\n", encoding="utf-8")
        calls = []
        real_io = agent._file_io

        class SpyIO:
            def read(self, path):
                calls.append(path)
                return real_io.read(path)

        agent._file_io = SpyIO()
        result = _read_call(agent, **_explicit("delegated.txt"))
        assert result.get("status") != "error"
        assert calls == [str(agent.working_dir / "delegated.txt")]
        assert result["content"].startswith("1\tdelegated")
    finally:
        agent.stop(timeout=1.0)


def test_manual_returns_real_installed_body_and_current_setting():
    agent = _agent("manual")
    try:
        result = _read_call(agent, action="manual", input={})
        assert result["status"] == "ok"
        assert result["manual"]
        assert "# Read Manual" in result["manual"]
        assert '"action": "read"' in result["manual"]
        assert '"reasoning": "inspect the requested source window"' in result["manual"]
        assert '"action": "manual"' in result["manual"]
        assert '"reasoning": "load the installed read guide"' in result["manual"]
        assert "omit" in result["manual"]
        assert result["manual_path"].endswith("capabilities/read-manual/SKILL.md")
        assert result["current_setting"]["source"] == "missing"
    finally:
        agent.stop(timeout=1.0)


def test_pagination_max_chars_and_truncation_metadata():
    agent = _agent("pagination")
    try:
        target = agent.working_dir / "pages.txt"
        target.write_text("".join(f"line-{i:03d}-xxxxxxxxxxxxxxxx\n" for i in range(1, 40)), encoding="utf-8")
        first = _read_call(agent, **_explicit("pages.txt", limit=39, max_chars=90))
        assert first["truncated"] is True
        assert first["cap_chars"] == 90
        assert first["returned_chars"] <= 90
        assert first["requested_offset"] == 1
        assert first["requested_limit"] == 39
        assert first["last_returned_line"] >= 1
        assert first["next_offset"] == first["last_returned_line"] + 1
        assert first["remaining_lines_estimate"] > 0
        second = _read_call(
            agent,
            **_explicit("pages.txt", offset=first["next_offset"], limit=39, max_chars=90),
        )
        assert int(second["content"].split("\t", 1)[0]) == first["next_offset"]
        assert second["current_setting"]["source"] == "missing"
    finally:
        agent.stop(timeout=1.0)


def test_line_truncated_is_bounded_and_advances_to_next_line():
    agent = _agent("line-truncated")
    try:
        target = agent.working_dir / "long-line.txt"
        target.write_text("A" * 500 + "\nsecond\n", encoding="utf-8")
        result = _read_call(agent, **_explicit("long-line.txt", limit=2, max_chars=40))
        assert result["truncated"] is True
        assert result["line_truncated"] is True
        assert result["returned_chars"] <= 40
        assert result["last_returned_line"] == 1
        assert result["next_offset"] == 2
        assert "A" in result["content"]
    finally:
        agent.stop(timeout=1.0)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"file_path": "x"},
        {"action": "read", "input": {"file_path": "x"}, "extra": 1},
        {"action": "read", "input": {"file_path": "x", "unknown": 1}},
        {"action": "manual", "input": {"unknown": 1}},
        {"action": "read", "input": {"file_path": "x", "summary": 1}},
        {"action": "read", "input": {"file_path": "x", "offset": "1"}},
        {"action": "read", "input": {"file_path": "x", "limit": False}},
        {"action": "read", "input": {"file_path": "x", "max_chars": None}},
    ],
)
def test_strict_flat_unknown_and_malformed_calls_do_not_read_target(payload):
    agent = _agent("reject")
    try:
        calls = []
        real_io = agent._file_io

        class SpyIO:
            def read(self, path):
                calls.append(path)
                return real_io.read(path)

        agent._file_io = SpyIO()
        result = _read_call(agent, **payload)
        assert result["status"] == "error"
        assert "current_setting" in result
        assert calls == []
    finally:
        agent.stop(timeout=1.0)


@pytest.mark.parametrize("bad_root", [None, [], "read", 3, _UnhashableMapping()])
def test_nonmapping_and_unhashable_roots_are_structured_rejections(bad_root):
    agent = _agent("bad-root")
    try:
        calls = []
        real_io = agent._file_io

        class SpyIO:
            def read(self, path):
                calls.append(path)
                return real_io.read(path)

        agent._file_io = SpyIO()
        result = agent._tool_handlers["read"](bad_root)
        assert result["status"] == "error"
        assert "current_setting" in result
        assert calls == []
    finally:
        agent.stop(timeout=1.0)


@pytest.mark.parametrize("bad_action", ["write", "", 4, [], {}])
def test_unknown_and_unhashable_actions_are_safe(bad_action):
    agent = _agent("bad-action")
    try:
        result = _read_call(agent, action=bad_action, input={})
        assert result["status"] == "error"
        assert "Unsupported action for read" in result["message"]
        assert "current_setting" in result
    finally:
        agent.stop(timeout=1.0)


def test_settings_missing_valid_hot_invalid_and_behavior_prompt_invariance():
    agent = _agent("settings")
    try:
        target = agent.working_dir / "settings-target.txt"
        target.write_text("a\nb\nc\n", encoding="utf-8")
        prompt_before = agent._build_system_prompt()

        missing = _read_call(agent, **_explicit("settings-target.txt", limit=2))
        assert missing["current_setting"]["source"] == "missing"
        baseline = _without_setting(missing)

        _write_settings(agent, '{"schema_version": 1}')
        valid = _read_call(agent, **_explicit("settings-target.txt", limit=2))
        assert valid["current_setting"]["source"] == "settings/read.json"
        assert valid["current_setting"]["settings_hash"]
        assert _without_setting(valid) == baseline

        _write_settings(agent, '{ "schema_version": 1 }')
        hot = _read_call(agent, **_explicit("settings-target.txt", limit=2))
        assert hot["current_setting"]["source"] == "settings/read.json"
        assert hot["current_setting"]["settings_revision"] != valid["current_setting"]["settings_revision"]
        assert _without_setting(hot) == baseline

        _write_settings(agent, '{"schema_version": 1, "future": true}')
        invalid = _read_call(agent, **_explicit("settings-target.txt", limit=2))
        assert invalid["current_setting"]["source"] == "settings_error"
        assert invalid["current_setting"]["settings_error"]
        assert _without_setting(invalid) == baseline
        assert agent._build_system_prompt() == prompt_before

        # A caller mutation cannot alter a later immutable snapshot.
        valid["current_setting"]["source"] = "tampered"
        again = _read_call(agent, **_explicit("settings-target.txt", limit=2))
        assert again["current_setting"]["source"] == "settings_error"
    finally:
        agent.stop(timeout=1.0)


def test_file_io_and_runtime_errors_are_text_only_and_setting_bearing():
    agent = _agent("errors")
    try:
        missing = _read_call(agent, **_explicit("missing.txt"))
        assert missing["status"] == "error"
        assert missing["message"].startswith("File not found:")
        assert missing["current_setting"]["source"] == "missing"

        class BrokenIO:
            def read(self, path):
                raise RuntimeError("backend exploded")

        agent._file_io = BrokenIO()
        failed = _read_call(agent, **_explicit("anything.txt"))
        assert failed["status"] == "error"
        assert failed["message"].startswith("Cannot read")
        assert "backend exploded" in failed["message"]
        assert failed["current_setting"]["source"] == "missing"
    finally:
        agent.stop(timeout=1.0)


def test_nested_summary_true_serial_uses_actual_handler_and_logs_raw_first():
    agent = _agent("summary-serial")
    try:
        target = agent.working_dir / "summary.txt"
        target.write_text("raw-file-marker\n", encoding="utf-8")
        events = []
        seen = {}

        def summarizer(system_prompt, user_prompt, tool_name, tool_call_id):
            seen["prompt"] = user_prompt
            return "SERIAL-READ-SUMMARY"

        executor = _make_executor(agent, events=events, summarizer=summarizer)
        results, intercepted, _ = executor.execute([
            ToolCall(
                name="read",
                args={
                    "action": "read",
                    "input": {"file_path": "summary.txt", "summary": True},
                    "reasoning": "retain the file marker",
                },
                id="read-serial",
            )
        ])
        assert intercepted is False
        content = _wire_content(results[0])
        assert content["summary_kind"] == "apriori_generated"
        assert content["generated_summary"] == "SERIAL-READ-SUMMARY"
        assert "raw-file-marker" in seen["prompt"]
        raw_index = _event_index(events, "tool_result", "read-serial")
        generated_index = _event_index(events, "apriori_summary_generated", "read-serial")
        visible_index = _event_index(events, "tool_result_model_visible", "read-serial")
        assert raw_index is not None and generated_index is not None and visible_index is not None
        assert raw_index < generated_index < visible_index
        assert "raw-file-marker" in str(events[raw_index][1]["result"])
    finally:
        agent.stop(timeout=1.0)


def test_nested_summary_true_parallel_reads_replace_after_each_raw_log():
    agent = _agent("summary-parallel")
    try:
        (agent.working_dir / "one.txt").write_text("parallel-one-marker\n", encoding="utf-8")
        (agent.working_dir / "two.txt").write_text("parallel-two-marker\n", encoding="utf-8")
        events = []
        seen = []

        def summarizer(system_prompt, user_prompt, tool_name, tool_call_id):
            seen.append((tool_call_id, user_prompt))
            return f"PARALLEL-SUMMARY-{tool_call_id}"

        executor = _make_executor(
            agent,
            events=events,
            summarizer=summarizer,
            parallel_safe_tools={"read"},
        )
        results, intercepted, _ = executor.execute([
            ToolCall(
                name="read",
                args={"action": "read", "input": {"file_path": "one.txt", "summary": True}},
                id="read-parallel-1",
            ),
            ToolCall(
                name="read",
                args={"action": "read", "input": {"file_path": "two.txt", "summary": True}},
                id="read-parallel-2",
            ),
        ])
        assert intercepted is False
        assert len(seen) == 2
        for result_message, call_id in zip(results, ("read-parallel-1", "read-parallel-2")):
            content = _wire_content(result_message)
            assert content["generated_summary"] == f"PARALLEL-SUMMARY-{call_id}"
            raw_index = _event_index(events, "tool_result", call_id)
            generated_index = _event_index(events, "apriori_summary_generated", call_id)
            visible_index = _event_index(events, "tool_result_model_visible", call_id)
            assert raw_index is not None and generated_index is not None and visible_index is not None
            assert raw_index < generated_index < visible_index
    finally:
        agent.stop(timeout=1.0)


def test_nested_input_summary_false_ignores_root_summary_without_replacement():
    """The shared canonical predicate never falls back to root summary."""
    from lingtai.kernel.tool_result_summary import APRIORI_SUMMARY_MARKER

    events = []
    called = []

    def logger(event_type, **fields):
        events.append((event_type, fields))

    def dispatch(_tool_call):
        return {"stdout": "ROOT-IGNORED-RAW"}

    def summarizer(*args):
        called.append(args)
        return "SHOULD-NOT-RUN"

    executor = ToolExecutor(
        dispatch_fn=dispatch,
        make_tool_result_fn=lambda name, result, **kw: {"name": name, "content": result, **kw},
        guard=LoopGuard(),
        known_tools={"read"},
        logger_fn=logger,
        working_dir=_persistent_root("summary-root"),
        summarizer_fn=summarizer,
    )
    results, _, _ = executor.execute([
        ToolCall(
            name="read",
            args={
                "input": {"file_path": "unused", "summary": False},
                "summary": True,
            },
            id="read-root-ignored",
        )
    ])
    content = _wire_content(results[0])
    assert "ROOT-IGNORED-RAW" in str(content)
    assert not (isinstance(content, dict) and content.get("artifact") == APRIORI_SUMMARY_MARKER)
    assert called == []


def test_no_summary_root_fallback_when_nested_summary_is_absent():
    from lingtai.kernel.tool_result_summary import summary_requested

    assert summary_requested({"input": {"file_path": "x"}, "summary": True}) is False
    assert summary_requested({"input": {"file_path": "x", "summary": False}, "summary": True}) is False
