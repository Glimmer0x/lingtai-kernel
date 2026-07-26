"""Independent candidate contract tests for the canonical ``shell`` tool.

The suite exercises the raw schema, actual Agent/provider surfaces, real manual
and settings readers, strict direct-call validation, and ToolExecutor's nested
summary boundary. Run/poll/cancel implementation seams are always patched: this
module never launches a child, supervisor, timer, scheduler, or notification.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

_ROOT = Path(__file__).resolve().parents[1]
_CANDIDATE_SRC = (_ROOT / "src").resolve()
sys.path.insert(0, str(_CANDIDATE_SRC))
for _module_name in tuple(sys.modules):
    if _module_name == "lingtai" or _module_name.startswith("lingtai."):
        del sys.modules[_module_name]

from lingtai.agent import Agent
from lingtai.kernel.llm.base import WIRE_TOOL_DESCRIPTION, ToolCall
from lingtai.kernel.loop_guard import LoopGuard
from lingtai.kernel.tool_executor import ToolExecutor
from lingtai.llm.anthropic.adapter import _build_tools as build_anthropic_tools
from lingtai.llm.openai.adapter import (
    _build_responses_tools,
    _build_tools as build_chat_tools,
)
from lingtai.tools import registry as tool_registry
from lingtai.tools.bash import ShellManager, get_description, get_schema
from tests._service_helpers import make_gemini_mock_service


_ARTIFACT_ROOT = _ROOT / "artifacts" / "shell-action-input-parent" / "committed-test-runs"


def _persistent_root(label: str) -> Path:
    root = _ARTIFACT_ROOT / f"{label}-{uuid4().hex}"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _agent(label: str) -> Agent:
    root = _persistent_root(label)
    return Agent(
        service=make_gemini_mock_service(),
        agent_name="shell-action-input-test",
        working_dir=root / "agent",
        capabilities={"shell": {"yolo": True}},
    )


def _manager(agent: Agent) -> ShellManager:
    manager = agent.get_capability("shell")
    assert isinstance(manager, ShellManager)
    return manager


def _write_manual(agent: Agent, marker: str = "# Shell Manual\ncanonical-shell-manual-marker\n") -> Path:
    path = agent.working_dir / ".library" / "intrinsic" / "capabilities" / "shell" / "SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(marker, encoding="utf-8")
    return path


def _write_settings(agent: Agent, text: str) -> Path:
    path = agent.working_dir / "settings" / "shell.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _without_setting(value: dict) -> dict:
    return {key: item for key, item in value.items() if key != "current_setting"}


def _make_executor(agent: Agent, *, events, summarizer):
    def logger(event_type, **fields):
        events.append((event_type, fields))

    def make_tool_result(name, result, **kwargs):
        return {"role": "tool", "name": name, "content": result, **kwargs}

    return ToolExecutor(
        dispatch_fn=agent._dispatch_tool,
        make_tool_result_fn=make_tool_result,
        guard=LoopGuard(),
        known_tools={"shell"},
        logger_fn=logger,
        working_dir=agent.working_dir,
        summarizer_fn=summarizer,
        parallel_safe_tools=set(),
    )


def _event_index(events, event_type: str, call_id: str) -> int | None:
    for index, (kind, fields) in enumerate(events):
        if kind == event_type and fields.get("tool_call_id") == call_id:
            return index
    return None


class TestShellActionInputCandidate(unittest.TestCase):
    def test_raw_schema_is_closed_and_preserves_nested_summary(self):
        schema = get_schema()
        self.assertEqual(set(schema), {"type", "properties", "required", "additionalProperties"})
        self.assertEqual(set(schema["properties"]), {"action", "input"})
        self.assertEqual(schema["required"], ["action", "input"])
        self.assertIs(schema["additionalProperties"], False)
        self.assertEqual(schema["properties"]["action"]["enum"], ["run", "poll", "cancel", "manual"])
        self.assertNotIn("reasoning", schema["properties"])
        self.assertNotIn("summary", schema["properties"])

        branches = {branch["title"]: branch for branch in schema["properties"]["input"]["anyOf"]}
        self.assertEqual(set(branches), {"run input", "poll input", "cancel input", "manual input"})
        run = branches["run input"]
        self.assertEqual(
            set(run["properties"]),
            {"command", "timeout", "working_dir", "async", "reminder", "summary"},
        )
        self.assertEqual(run["required"], ["command"])
        self.assertIs(run["additionalProperties"], False)
        self.assertEqual(run["properties"]["summary"]["type"], "boolean")
        self.assertIs(run["properties"]["summary"]["default"], False)
        self.assertEqual(branches["poll input"]["required"], ["job_id"])
        self.assertEqual(branches["cancel input"]["required"], ["job_id"])
        self.assertEqual(branches["manual input"]["properties"], {})
        for branch in branches.values():
            self.assertIs(branch["additionalProperties"], False)

    def test_actual_agent_origin_schema_prompt_and_provider_envelopes(self):
        agent = _agent("agent-surface")
        try:
            manager = _manager(agent)
            schema = next(item for item in agent._build_tool_schemas() if item.name == "shell")
            self.assertEqual(tool_registry.BUILTIN_TOOLS["shell"], "lingtai.tools.bash")
            self.assertEqual(set(schema.parameters["properties"]), {"action", "input", "reasoning"})
            self.assertEqual(schema.parameters["required"], ["action", "input"])
            self.assertIs(schema.parameters["additionalProperties"], False)
            self.assertEqual(Path(sys.modules["lingtai.tools.bash"].__file__).resolve(), (_ROOT / "src/lingtai/tools/bash/__init__.py").resolve())
            self.assertEqual(manager.handle.__code__.co_filename, str((_ROOT / "src/lingtai/tools/bash/__init__.py").resolve()))

            prompt = agent._build_system_prompt()
            self.assertIn("### shell", prompt)
            self.assertIn("Execute a shell command and return stdout/stderr.", prompt)
            self.assertIn("input.summary=true", prompt)
            self.assertIn("input.summary=true", get_description())

            chat = build_chat_tools([schema])[0]
            responses = _build_responses_tools([schema])[0]
            anthropic = build_anthropic_tools([schema], cache_tools=False)[0]
            self.assertEqual(chat["function"]["name"], "shell")
            self.assertEqual(responses["name"], "shell")
            self.assertEqual(anthropic["name"], "shell")
            self.assertEqual(chat["function"]["description"], WIRE_TOOL_DESCRIPTION)
            self.assertEqual(responses["description"], WIRE_TOOL_DESCRIPTION)
            self.assertEqual(anthropic["description"], WIRE_TOOL_DESCRIPTION)
            for parameters in (
                chat["function"]["parameters"],
                responses["parameters"],
                anthropic["input_schema"],
            ):
                self.assertEqual(set(parameters["properties"]), {"action", "input", "reasoning"})
                self.assertEqual(parameters["required"], ["action", "input"])
                self.assertIs(parameters["additionalProperties"], False)
        finally:
            agent.stop(timeout=1.0)

    def test_real_manual_fake_routes_and_authoritative_current_setting(self):
        agent = _agent("routes")
        try:
            manager = _manager(agent)
            manual_path = _write_manual(agent)
            manual = manager.handle({"action": "manual", "input": {}})
            self.assertEqual(manual["status"], "ok")
            self.assertIn("canonical-shell-manual-marker", manual["manual"])
            self.assertEqual(Path(manual["manual_path"]).resolve(), manual_path.resolve())
            self.assertEqual(manual["current_setting"]["source"], "missing")

            with (
                patch.object(manager, "_handle_run", return_value={"status": "ok", "route": "run", "current_setting": {"source": "forged"}}) as run,
                patch.object(manager, "_handle_poll", return_value={"status": "running", "route": "poll"}) as poll,
                patch.object(manager, "_handle_cancel", return_value={"status": "cancelled", "route": "cancel"}) as cancel,
            ):
                run_result = manager.handle({"action": "run", "input": {"command": "not-executed", "summary": True}})
                poll_result = manager.handle({"action": "poll", "input": {"job_id": "job-12345678"}})
                cancel_result = manager.handle({"action": "cancel", "input": {"job_id": "job-12345678"}})
                self.assertEqual(run_result["route"], "run")
                self.assertEqual(run_result["current_setting"]["source"], "missing")
                self.assertEqual(poll_result["route"], "poll")
                self.assertEqual(cancel_result["route"], "cancel")
                run.assert_called_once_with({"command": "not-executed", "summary": True})
                poll.assert_called_once_with({"job_id": "job-12345678"})
                cancel.assert_called_once_with({"job_id": "job-12345678"})
        finally:
            agent.stop(timeout=1.0)

    def test_strict_malformed_calls_never_reach_execution_routes(self):
        agent = _agent("reject")
        try:
            manager = _manager(agent)
            bad_calls = [
                None,
                [],
                {},
                {"command": "flat"},
                {"action": ["run"], "input": {}},
                {"action": "run", "input": {"command": 3}},
                {"action": "run", "input": {"command": "x", "timeout": "3"}},
                {"action": "run", "input": {"command": "x", "working_dir": 3}},
                {"action": "run", "input": {"command": "x", "async": 1}},
                {"action": "run", "input": {"command": "x", "async": True, "reminder": "3"}},
                {"action": "run", "input": {"command": "x", "summary": 1}},
                {"action": "run", "input": {"command": "x", "unknown": True}},
                {"action": "poll", "input": {"job_id": "job-12345678", "summary": True}},
                {"action": "manual", "input": {"command": "x"}},
                {"action": "manual", "input": {}, "summary": True},
            ]
            with (
                patch.object(manager, "_handle_run", side_effect=AssertionError("live run route reached")) as run,
                patch.object(manager, "_handle_poll", side_effect=AssertionError("live poll route reached")) as poll,
                patch.object(manager, "_handle_cancel", side_effect=AssertionError("live cancel route reached")) as cancel,
            ):
                for payload in bad_calls:
                    with self.subTest(payload=payload):
                        result = manager.handle(payload)
                        self.assertEqual(result["status"], "error")
                        self.assertIn("current_setting", result)
                run.assert_not_called()
                poll.assert_not_called()
                cancel.assert_not_called()
        finally:
            agent.stop(timeout=1.0)

    def test_settings_missing_valid_hot_invalid_and_behavior_invariance(self):
        agent = _agent("settings")
        try:
            manager = _manager(agent)
            _write_manual(agent)
            prompt_before = agent._build_system_prompt()
            with patch.object(manager, "_handle_run", return_value={"status": "ok", "marker": "same"}):
                missing = manager.handle({"action": "run", "input": {"command": "not-executed"}})
                self.assertEqual(missing["current_setting"]["source"], "missing")
                baseline = _without_setting(missing)

                _write_settings(agent, '{"schema_version": 1}')
                valid = manager.handle({"action": "run", "input": {"command": "not-executed"}})
                self.assertEqual(valid["current_setting"]["source"], "settings/shell.json")
                self.assertEqual(_without_setting(valid), baseline)

                _write_settings(agent, '{ "schema_version": 1 }')
                hot = manager.handle({"action": "run", "input": {"command": "not-executed"}})
                self.assertNotEqual(hot["current_setting"]["settings_revision"], valid["current_setting"]["settings_revision"])
                self.assertEqual(_without_setting(hot), baseline)

                ignored_reminder = manager.handle({
                    "action": "run",
                    "input": {"command": "not-executed", "reminder": float("nan")},
                })
                self.assertEqual(_without_setting(ignored_reminder), baseline)

                _write_settings(agent, '{"schema_version": 1, "future": true}')
                invalid = manager.handle({"action": "run", "input": {"command": "not-executed"}})
                self.assertEqual(invalid["current_setting"]["source"], "settings_error")
                self.assertTrue(invalid["current_setting"]["settings_error"])
                self.assertEqual(_without_setting(invalid), baseline)
                self.assertEqual(agent._build_system_prompt(), prompt_before)

                valid["current_setting"]["source"] = "tampered"
                again = manager.handle({"action": "run", "input": {"command": "not-executed"}})
                self.assertEqual(again["current_setting"]["source"], "settings_error")
        finally:
            agent.stop(timeout=1.0)

    def test_nested_summary_true_uses_fake_handler_and_logs_raw_first(self):
        agent = _agent("summary")
        try:
            manager = _manager(agent)
            events = []
            seen = {}

            def summarizer(system_prompt, user_prompt, tool_name, tool_call_id):
                seen["prompt"] = user_prompt
                return "SHELL-GENERATED-SUMMARY"

            executor = _make_executor(agent, events=events, summarizer=summarizer)
            raw_result = {
                "status": "ok",
                "exit_code": 0,
                "stdout": "raw-shell-marker",
                "stderr": "",
                "ok": True,
                "command_status": "success",
            }
            with patch.object(manager, "_handle_run", return_value=raw_result) as run:
                results, intercepted, _ = executor.execute([
                    ToolCall(
                        name="shell",
                        args={
                            "action": "run",
                            "input": {"command": "not-executed", "summary": True},
                            "reasoning": "retain the raw shell marker",
                        },
                        id="shell-summary",
                    )
                ])
            self.assertIs(intercepted, False)
            run.assert_called_once_with({"command": "not-executed", "summary": True})
            content = results[0]["content"]
            self.assertEqual(content["summary_kind"], "apriori_generated")
            self.assertEqual(content["generated_summary"], "SHELL-GENERATED-SUMMARY")
            self.assertIn("raw-shell-marker", seen["prompt"])
            raw_index = _event_index(events, "tool_result", "shell-summary")
            generated_index = _event_index(events, "apriori_summary_generated", "shell-summary")
            visible_index = _event_index(events, "tool_result_model_visible", "shell-summary")
            self.assertIsNotNone(raw_index)
            self.assertIsNotNone(generated_index)
            self.assertIsNotNone(visible_index)
            self.assertLess(raw_index, generated_index)
            self.assertLess(generated_index, visible_index)
            self.assertIn("raw-shell-marker", str(events[raw_index][1]["result"]))
        finally:
            agent.stop(timeout=1.0)


if __name__ == "__main__":
    unittest.main()
