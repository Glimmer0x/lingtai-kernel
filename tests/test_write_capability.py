"""Focused contract coverage for the migrated public ``write`` capability.

These tests intentionally use persistent unique directories. They do not remove
anything, matching the repository's no-cleanup validation policy.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from lingtai.agent import Agent
from lingtai.kernel.llm.base import FunctionSchema, WIRE_TOOL_DESCRIPTION
from lingtai.llm.anthropic.adapter import _build_tools as build_anthropic_tools
from lingtai.llm.openai.adapter import (
    _build_responses_tools,
    _build_tools as build_chat_tools,
)
from lingtai.tools import write as write_tool
from tests._service_helpers import make_gemini_mock_service as make_mock_service


_ARTIFACT_ROOT = Path("artifacts/write-action-input-worker/pytest")


def _root(label: str) -> Path:
    path = _ARTIFACT_ROOT / f"{label}-{uuid.uuid4().hex}"
    path.mkdir(parents=True, exist_ok=False)
    return path


class _FileIO:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.calls: list[tuple[str, str]] = []

    def write(self, path: str, content: str) -> None:
        self.calls.append((path, content))
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


class _Agent:
    def __init__(self, root: Path, file_io: _FileIO | None = None) -> None:
        self._working_dir = root
        self._file_io = file_io or _FileIO(root)
        self.handlers: dict[str, object] = {}
        self._tool_schemas: list[FunctionSchema] = []
        self._intrinsics = {}
        self._intrinsic_modules = {}

    def add_tool(self, name: str, *, schema=None, handler=None, **kwargs) -> None:
        self.handlers[name] = handler
        self._tool_schemas.append(
            FunctionSchema(
                name=name,
                description=kwargs.get("description", ""),
                parameters=schema,
                glossary_package=kwargs.get("glossary_package"),
            )
        )


def _handler(root: Path, file_io: _FileIO | None = None):
    agent = _Agent(root, file_io)
    write_tool.setup(agent)
    return agent, agent.handlers["write"]


def test_write_schema_is_closed_nested_action_input():
    schema = write_tool.get_schema()
    assert schema["type"] == "object"
    assert set(schema["properties"]) == {"action", "input"}
    assert schema["required"] == ["action", "input"]
    assert schema["additionalProperties"] is False
    assert "reasoning" not in schema["properties"]

    write_input, manual_input = schema["properties"]["input"]["anyOf"]
    assert write_input["title"] == "write input"
    assert set(write_input["properties"]) == {"file_path", "content"}
    assert write_input["required"] == ["file_path", "content"]
    assert write_input["additionalProperties"] is False
    assert manual_input["title"] == "manual input"
    assert manual_input["properties"] == {}
    assert manual_input["required"] == []
    assert manual_input["additionalProperties"] is False


def test_write_round_trip_and_settings():
    root = _root("round-trip")
    agent, handler = _handler(root)
    result = handler(
        {
            "action": "write",
            "input": {"file_path": "nested/result.txt", "content": "héllo"},
            "reasoning": "persist the result",
        }
    )
    assert result["status"] == "ok"
    assert result["bytes"] == len("héllo".encode("utf-8"))
    assert result["path"] == str(root / "nested/result.txt")
    assert result["current_setting"]["source"] == "missing"
    assert (root / "nested/result.txt").read_text(encoding="utf-8") == "héllo"


def test_write_relative_path_and_parent_creation():
    root = _root("relative")
    agent, handler = _handler(root)
    result = handler({"action": "write", "input": {"file_path": "a/b/c.txt", "content": "x"}})
    assert result["status"] == "ok"
    assert (root / "a/b/c.txt").read_text(encoding="utf-8") == "x"
    assert agent._file_io.calls == [(str(root / "a/b/c.txt"), "x")]


def test_write_delegates_to_injected_file_io():
    root = _root("injected")
    file_io = _FileIO(root)
    _agent, handler = _handler(root, file_io)
    result = handler({"action": "write", "input": {"file_path": "one.txt", "content": "via io"}})
    assert result["status"] == "ok"
    assert file_io.calls == [(str(root / "one.txt"), "via io")]


def test_write_error_shape_and_current_setting():
    root = _root("errors")
    _agent, handler = _handler(root)
    for args in (
        {},
        {"file_path": "flat.txt", "content": "flat"},
        {"action": "write"},
        {"action": "write", "input": {}},
        {"action": "write", "input": {"file_path": "x"}},
        {"action": "write", "input": {"file_path": "x", "content": 1}},
        {"action": "write", "input": {"file_path": "x", "content": "x", "extra": True}},
    ):
        result = handler(args)
        assert result["status"] == "error", result
        assert "current_setting" in result

    for action in ("unsupported", [], {}):
        result = handler({"action": action, "input": {}})
        assert result["status"] == "error"
        assert "current_setting" in result


def test_write_reasoning_metadata_never_enters_dispatch_input():
    root = _root("reasoning")
    file_io = _FileIO(root)
    _agent, handler = _handler(root, file_io)
    for key in ("reasoning", "_reasoning"):
        result = handler(
            {
                "action": "write",
                "input": {"file_path": f"{key}.txt", "content": key},
                key: "metadata only",
            }
        )
        assert result["status"] == "ok"
    assert [content for _path, content in file_io.calls] == ["reasoning", "_reasoning"]


def test_write_manual_uses_installed_canonical_body():
    root = _root("manual")
    manual_path = root / ".library/intrinsic/capabilities/file-manual/SKILL.md"
    manual_path.parent.mkdir(parents=True, exist_ok=True)
    body = "---\nname: file-manual\n---\ncanonical sentinel\n"
    manual_path.write_text(body, encoding="utf-8")
    _agent, handler = _handler(root)
    result = handler({"action": "manual", "input": {}})
    assert result["status"] == "ok"
    assert result["action"] == "manual"
    assert result["manual"] == body
    assert result["manual_path"] == str(manual_path)
    assert result["current_setting"]["source"] == "missing"


def test_write_settings_hot_valid_invalid_and_sentinel_nonleakage():
    root = _root("settings")
    settings_path = root / "settings/write.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text('{"schema_version": 1}', encoding="utf-8")
    _agent, handler = _handler(root)
    first = handler({"action": "write", "input": {"file_path": "first", "content": "x"}})
    assert first["current_setting"]["source"] == "settings/write.json"
    settings_path.write_text('{"schema_version": 1, "sentinel": "do-not-leak"}', encoding="utf-8")
    second = handler({"action": "write", "input": {"file_path": "second", "content": "y"}})
    assert second["current_setting"]["source"] == "settings_error"
    assert "do-not-leak" not in json.dumps(second, ensure_ascii=False)
    assert (root / "second").read_text(encoding="utf-8") == "y"


def test_write_error_shape_and_current_setting_for_fileio_runtime_error():
    root = _root("runtime")
    file_io = MagicMock()
    file_io.write.side_effect = RuntimeError("backend unavailable")
    _agent, handler = _handler(root, file_io)
    result = handler({"action": "write", "input": {"file_path": "runtime.txt", "content": "x"}})
    assert result["status"] == "error"
    assert "Cannot write" in result["message"]
    assert "current_setting" in result


def test_actual_agent_schema_provider_wires_and_prompt():
    root = _root("actual-agent")
    agent = Agent(
        service=make_mock_service(),
        agent_name="write-contract-test",
        working_dir=root / "agent",
        capabilities=["write"],
    )
    try:
        schema = next(item for item in agent._build_tool_schemas() if item.name == "write")
        assert set(schema.parameters["properties"]) == {"action", "input", "reasoning"}
        assert schema.parameters["required"] == ["action", "input"]
        assert schema.parameters["additionalProperties"] is False
        assert "reasoning" not in schema.parameters["properties"]["input"]

        chat = build_chat_tools([schema])[0]
        responses = _build_responses_tools([schema])[0]
        anthropic = build_anthropic_tools([schema], cache_tools=False)[0]
        assert set(chat) == {"type", "function"}
        assert set(chat["function"]) == {"name", "description", "parameters"}
        assert set(responses) == {"type", "name", "description", "parameters"}
        assert set(anthropic) == {"name", "description", "input_schema"}
        assert chat["function"]["parameters"] == schema.parameters
        assert responses["parameters"] == schema.parameters
        assert anthropic["input_schema"] == schema.parameters
        assert chat["function"]["description"] == WIRE_TOOL_DESCRIPTION
        assert responses["description"] == WIRE_TOOL_DESCRIPTION
        assert anthropic["description"] == WIRE_TOOL_DESCRIPTION

        prompt = agent._build_system_prompt()
        batches = agent._build_system_prompt_batches()
        assert prompt == "\n\n".join(batch for batch in batches if batch)
        description = write_tool.get_description()
        assert "### write" in prompt
        assert description in prompt
        assert "action='write'" in description
        assert "input=" in description
        assert "omit action for the legacy" not in description
    finally:
        agent.stop(timeout=1.0)


def test_description_documents_only_canonical_calls():
    description = write_tool.get_description()
    assert "action='write'" in description
    assert "input=" in description
    assert "omit action" not in description
    assert "flat" not in description
