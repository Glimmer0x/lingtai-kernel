"""Focused hermetic candidate coverage for the public daemon action/input slice.

All daemon execution handlers are patched.  This module does not launch a
supervisor, process, backend, MCP client, notification, or live daemon run.
"""
from __future__ import annotations

# Candidate-origin eviction and sys.path precedence must run before LingTai imports.
# ruff: noqa: E402

import copy
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

_ROOT = Path(__file__).resolve().parents[1]
_CANDIDATE_SRC = (_ROOT / "src").resolve()
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_CANDIDATE_SRC))
for _module_name in tuple(sys.modules):
    if _module_name == "lingtai" or _module_name.startswith("lingtai."):
        del sys.modules[_module_name]

from lingtai.agent import Agent
from lingtai.kernel.llm.base import ToolCall, WIRE_TOOL_DESCRIPTION
from lingtai.kernel.loop_guard import LoopGuard
from lingtai.kernel.tool_executor import ToolExecutor
from lingtai.kernel.tool_result_summary import (
    APRIORI_SUMMARY_MARKER,
    summary_requested,
)
from lingtai.llm.anthropic.adapter import _build_tools as build_anthropic_tools
from lingtai.llm.openai.adapter import (
    _build_responses_tools,
    _build_tools as build_chat_tools,
)
from lingtai.tools import registry as tool_registry
from lingtai.tools.daemon import DaemonManager, get_schema
from tests._service_helpers import make_gemini_mock_service


_ARTIFACT_ROOT = _ROOT / "artifacts" / "daemon-action-input-parent" / "focused-test-runs"
_SOURCE_MANUAL = _ROOT / "src" / "lingtai" / "tools" / "daemon" / "manual" / "SKILL.md"
_ACTIONS = ("emanate", "list", "ask", "check", "reclaim", "manual")
_EXPECTED_BRANCH_PROPERTIES = {
    "emanate input": {"tasks", "max_turns", "timeout", "backend", "summary"},
    "list input": {"contains", "status", "include_done", "last", "summary"},
    "ask input": {"id", "message", "summary"},
    "check input": {"id", "last", "truncate", "summary"},
    "reclaim input": {"summary"},
    "manual input": {"summary"},
}


def _agent(label: str) -> Agent:
    root = _ARTIFACT_ROOT / f"{label}-{uuid4().hex}"
    root.mkdir(parents=True, exist_ok=True)
    return Agent(
        service=make_gemini_mock_service(),
        agent_name="daemon-action-input-test",
        working_dir=root / "agent",
        capabilities=["daemon"],
    )


def _manager(agent: Agent) -> DaemonManager:
    manager = agent.get_capability("daemon")
    assert isinstance(manager, DaemonManager)
    return manager


def _write_settings(agent: Agent, text: str) -> Path:
    path = agent.working_dir / "settings" / "daemon.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _without_setting(value: dict) -> dict:
    return {key: item for key, item in value.items() if key != "current_setting"}


def _event_index(events: list[tuple[str, dict]], event_type: str, tool_call_id: str) -> int:
    for index, (kind, fields) in enumerate(events):
        if kind == event_type and fields.get("tool_call_id") == tool_call_id:
            return index
    raise AssertionError(f"missing {event_type} for {tool_call_id}")


class TestDaemonActionInputCandidate(unittest.TestCase):
    def test_actual_agent_full_prompt_raw_facing_and_provider_schemas(self):
        agent = _agent("surface")
        try:
            manager = _manager(agent)
            module = sys.modules["lingtai.tools.daemon"]
            self.assertEqual(
                Path(sys.modules["lingtai"].__file__).resolve(),
                _CANDIDATE_SRC / "lingtai" / "__init__.py",
            )
            self.assertEqual(
                Path(sys.modules["lingtai.agent"].__file__).resolve(),
                _CANDIDATE_SRC / "lingtai" / "agent.py",
            )
            self.assertEqual(
                Path(module.__file__).resolve(),
                _CANDIDATE_SRC / "lingtai" / "tools" / "daemon" / "__init__.py",
            )
            self.assertEqual(Path(manager.handle.__code__.co_filename).resolve(), Path(module.__file__).resolve())
            self.assertEqual(tool_registry.BUILTIN_TOOLS["daemon"], "lingtai.tools.daemon")

            full_prompt = agent._build_system_prompt()
            self.assertIsInstance(full_prompt, str)
            self.assertGreater(len(full_prompt), 1_000)
            self.assertIn("daemon(action='emanate', input={'tasks': [...]})", full_prompt)
            self.assertIn("Read daemon-manual before ordinary daemon work", full_prompt)

            raw = get_schema()
            self.assertEqual(set(raw["properties"]), {"action", "input"})
            self.assertEqual(raw["required"], ["action", "input"])
            self.assertIs(raw["additionalProperties"], False)
            self.assertNotIn("reasoning", raw["properties"])
            self.assertEqual(raw["properties"]["action"]["enum"], list(_ACTIONS))
            branches = {
                item["title"]: item
                for item in raw["properties"]["input"]["anyOf"]
            }
            self.assertEqual(set(branches), set(_EXPECTED_BRANCH_PROPERTIES))
            for title, expected_properties in _EXPECTED_BRANCH_PROPERTIES.items():
                self.assertEqual(set(branches[title]["properties"]), expected_properties)
                self.assertIs(branches[title]["additionalProperties"], False)
                self.assertEqual(branches[title]["properties"]["summary"]["type"], "boolean")
                self.assertGreater(len(branches[title]["properties"]["summary"]["description"]), 100)
            self.assertEqual(branches["emanate input"]["required"], ["tasks"])
            self.assertIs(
                branches["emanate input"]["properties"]["tasks"]["items"]["additionalProperties"],
                False,
            )
            self.assertGreater(
                len(branches["emanate input"]["properties"]["tasks"]["description"]),
                500,
            )
            self.assertEqual(branches["ask input"]["required"], ["id", "message"])
            self.assertEqual(branches["check input"]["required"], ["id"])

            summary_nodes = [
                branches[f"{action} input"]["properties"]["summary"]
                for action in _ACTIONS
            ]
            self.assertEqual(len({id(item) for item in summary_nodes}), len(_ACTIONS))
            summary_nodes[0]["description"] = "mutated-local-copy"
            self.assertNotEqual(summary_nodes[1]["description"], "mutated-local-copy")
            self.assertNotEqual(
                get_schema()["properties"]["input"]["anyOf"][0]["properties"]["summary"]["description"],
                "mutated-local-copy",
            )

            facing = next(item for item in agent._build_tool_schemas() if item.name == "daemon")
            self.assertEqual(set(facing.parameters["properties"]), {"action", "input", "reasoning"})
            self.assertEqual(facing.parameters["required"], ["action", "input"])
            self.assertIs(facing.parameters["additionalProperties"], False)
            facing_without_reasoning = copy.deepcopy(facing.parameters)
            facing_without_reasoning["properties"].pop("reasoning")
            self.assertEqual(facing_without_reasoning, get_schema())

            chat = build_chat_tools([facing])[0]
            responses = _build_responses_tools([facing])[0]
            anthropic = build_anthropic_tools([facing], cache_tools=False)[0]
            self.assertEqual(chat["function"]["name"], "daemon")
            self.assertEqual(responses["name"], "daemon")
            self.assertEqual(anthropic["name"], "daemon")
            self.assertEqual(chat["function"]["description"], WIRE_TOOL_DESCRIPTION)
            self.assertEqual(responses["description"], WIRE_TOOL_DESCRIPTION)
            self.assertEqual(anthropic["description"], WIRE_TOOL_DESCRIPTION)
            self.assertEqual(chat["function"]["parameters"], facing.parameters)
            expected_responses = copy.deepcopy(facing.parameters)
            expected_responses["properties"]["input"]["properties"] = {}
            mcp_items = (
                expected_responses["properties"]["input"]["anyOf"][0]
                ["properties"]["tasks"]["items"]["properties"]["mcp"]["items"]
            )
            mcp_items["properties"] = {}
            self.assertEqual(responses["parameters"], expected_responses)
            self.assertEqual(anthropic["input_schema"], facing.parameters)
        finally:
            agent.stop(timeout=1.0)

    def test_real_candidate_manual_and_all_six_routes_are_fake_only(self):
        agent = _agent("routes")
        try:
            manager = _manager(agent)
            installed_path = (
                agent.working_dir
                / ".library"
                / "intrinsic"
                / "capabilities"
                / "daemon"
                / "SKILL.md"
            )
            self.assertTrue(installed_path.is_file())
            self.assertEqual(
                installed_path.read_text(encoding="utf-8"),
                _SOURCE_MANUAL.read_text(encoding="utf-8"),
            )
            manual = manager.handle({"action": "manual", "input": {"summary": True}})
            self.assertEqual(manual["status"], "ok")
            self.assertEqual(manual["manual"], _SOURCE_MANUAL.read_text(encoding="utf-8"))
            self.assertEqual(Path(manual["manual_path"]).resolve(), installed_path.resolve())
            self.assertIn("current_setting", manual)

            with (
                patch.object(manager, "_handle_emanate", return_value={"route": "emanate"}) as emanate,
                patch.object(manager, "_handle_list", return_value={"route": "list"}) as listed,
                patch.object(manager, "_handle_ask", return_value={"route": "ask"}) as ask,
                patch.object(manager, "_handle_check", return_value={"route": "check"}) as check,
                patch.object(manager, "_handle_reclaim", return_value={"route": "reclaim"}) as reclaim,
            ):
                task = {"task": "fake", "tools": []}
                calls = [
                    ("emanate", {"tasks": [task], "summary": True}),
                    ("list", {"summary": True}),
                    ("ask", {"id": "em-1", "message": "fake", "summary": True}),
                    ("check", {"id": "em-1", "summary": True}),
                    ("reclaim", {"summary": True}),
                ]
                for action, payload in calls:
                    with self.subTest(action=action):
                        result = manager.handle({"action": action, "input": payload})
                        self.assertEqual(result["route"], action)
                        self.assertIn("current_setting", result)
                emanate.assert_called_once_with([task], max_turns=None, timeout=None, backend="lingtai")
                listed.assert_called_once_with(
                    contains="",
                    status_filter="all",
                    include_done=True,
                    limit=None,
                )
                ask.assert_called_once_with("em-1", "fake")
                check.assert_called_once_with("em-1", last=20, truncate=500)
                reclaim.assert_called_once_with()
        finally:
            agent.stop(timeout=1.0)

    def test_strict_malformed_calls_are_zero_daemon_seam(self):
        agent = _agent("reject")
        try:
            manager = _manager(agent)
            bad = [
                None,
                {},
                {"action": "list"},
                {"action": "list", "input": []},
                {"action": "unknown", "input": {}},
                {"action": "list", "input": {"id": "x"}},
                {"action": "list", "input": {"summary": 1}},
                {"action": "check", "input": {"id": "x", "last": True}},
                {"action": "check", "input": {"id": "x", "truncate": -1}},
                {"action": "ask", "input": {"id": "x"}},
                {"action": "manual", "input": {"extra": True}},
                {"action": "manual", "input": {"summary": "true"}},
                {"action": "reclaim", "input": {"summary": None}},
                {"action": "emanate", "input": {"tasks": []}},
                {"action": "emanate", "input": {"tasks": [{"task": "x", "tools": [], "extra": 1}]}},
                {"action": "emanate", "input": {"tasks": [{"task": "x", "tools": ["file"]}], "max_turns": True}},
                {"action": "emanate", "input": {"tasks": [{"task": "x", "tools": ["file"]}], "backend": "unknown"}},
                {"action": "list", "input": {}, "summary": True},
                {"action": "list", "input": {}, "reasoning": "ok", "extra": True},
            ]
            with (
                patch.object(manager, "_handle_emanate", side_effect=AssertionError("emanate seam reached")) as emanate,
                patch.object(manager, "_handle_list", side_effect=AssertionError("list seam reached")) as listed,
                patch.object(manager, "_handle_ask", side_effect=AssertionError("ask seam reached")) as ask,
                patch.object(manager, "_handle_check", side_effect=AssertionError("check seam reached")) as check,
                patch.object(manager, "_handle_reclaim", side_effect=AssertionError("reclaim seam reached")) as reclaim,
                patch("lingtai.tools.daemon.load_installed_manual", side_effect=AssertionError("manual seam reached")) as manual,
            ):
                for call in bad:
                    with self.subTest(call=call):
                        result = manager.handle(call)
                        self.assertEqual(result["status"], "error")
                        self.assertIn("current_setting", result)
                emanate.assert_not_called()
                listed.assert_not_called()
                ask.assert_not_called()
                check.assert_not_called()
                reclaim.assert_not_called()
                manual.assert_not_called()
        finally:
            agent.stop(timeout=1.0)

    def test_settings_missing_valid_hot_invalid_is_fresh_copy_safe_and_inert(self):
        agent = _agent("settings")
        try:
            manager = _manager(agent)
            shared_handler_result = {"status": "ok", "marker": "same", "nested": {"stable": True}}
            with patch.object(manager, "_handle_list", return_value=shared_handler_result):
                missing = manager.handle({"action": "list", "input": {}})
                baseline = _without_setting(missing)
                self.assertEqual(missing["current_setting"]["source"], "missing")
                self.assertIs(missing["current_setting"]["configurable"], False)
                self.assertEqual(missing["current_setting"]["placeholder"], "no-op")

                settings_path = _write_settings(agent, '{"schema_version": 1}')
                self.assertEqual(settings_path, agent.working_dir / "settings" / "daemon.json")
                valid = manager.handle({"action": "list", "input": {}})
                self.assertEqual(valid["current_setting"]["source"], "settings/daemon.json")
                self.assertEqual(_without_setting(valid), baseline)

                _write_settings(agent, '{ "schema_version": 1 }')
                hot = manager.handle({"action": "list", "input": {}})
                self.assertNotEqual(
                    hot["current_setting"]["settings_revision"],
                    valid["current_setting"]["settings_revision"],
                )
                self.assertEqual(_without_setting(hot), baseline)

                _write_settings(agent, '{"schema_version": 1, "future": true}')
                invalid = manager.handle({"action": "list", "input": {}})
                self.assertEqual(invalid["current_setting"]["source"], "settings_error")
                self.assertTrue(invalid["current_setting"]["settings_error"])
                self.assertEqual(_without_setting(invalid), baseline)

                valid["current_setting"]["source"] = "tampered"
                valid["marker"] = "tampered"
                again = manager.handle({"action": "list", "input": {}})
                self.assertEqual(again["current_setting"]["source"], "settings_error")
                self.assertEqual(again["marker"], "same")
                self.assertEqual(shared_handler_result["marker"], "same")
        finally:
            agent.stop(timeout=1.0)

    def test_nested_summary_all_actions_and_actual_executor_raw_first_logging(self):
        for action in _ACTIONS:
            payload = {"summary": True}
            if action == "emanate":
                payload["tasks"] = [{"task": "fake", "tools": []}]
            elif action == "ask":
                payload.update({"id": "em-1", "message": "fake"})
            elif action == "check":
                payload["id"] = "em-1"
            call = {"action": action, "input": payload}
            with self.subTest(action=action):
                self.assertTrue(summary_requested(call))
                self.assertFalse(summary_requested({"action": action, "input": {**payload, "summary": 1}}))
        self.assertFalse(summary_requested({"action": "list", "input": {}, "summary": True}))

        agent = _agent("summary-executor")
        try:
            manager = _manager(agent)
            events: list[tuple[str, dict]] = []
            seen: dict[str, str] = {}
            raw_marker = "DAEMON-RAW-FIRST-MARKER"
            tool_call_id = "daemon-summary-candidate-1"

            def logger_fn(event_type, **fields):
                events.append((event_type, fields))

            def make_tool_result_fn(name, result, **kwargs):
                return {"role": "tool", "name": name, "content": result, **kwargs}

            def summarizer(system_prompt, user_prompt, tool_name, call_id):
                seen["system_prompt"] = system_prompt
                seen["user_prompt"] = user_prompt
                seen["tool_name"] = tool_name
                seen["tool_call_id"] = call_id
                return "DAEMON-GENERATED-SUMMARY"

            with patch.object(
                manager,
                "_handle_list",
                return_value={"status": "ok", "events": [raw_marker]},
            ) as listed:
                executor = ToolExecutor(
                    dispatch_fn=lambda tool_call: manager.handle(tool_call.args),
                    make_tool_result_fn=make_tool_result_fn,
                    guard=LoopGuard(),
                    known_tools={"daemon"},
                    logger_fn=logger_fn,
                    working_dir=agent.working_dir,
                    summarizer_fn=summarizer,
                    parallel_safe_tools=set(),
                )
                results, intercepted, _usage = executor.execute(
                    [
                        ToolCall(
                            name="daemon",
                            args={
                                "action": "list",
                                "input": {"summary": True},
                                "reasoning": "Retain the exact raw-first marker.",
                            },
                            id=tool_call_id,
                        )
                    ]
                )
            self.assertFalse(intercepted)
            listed.assert_called_once_with(
                contains="",
                status_filter="all",
                include_done=True,
                limit=None,
            )
            content = results[0]["content"]
            self.assertIsInstance(content, dict)
            self.assertEqual(content["artifact"], APRIORI_SUMMARY_MARKER)
            self.assertEqual(content["generated_summary"], "DAEMON-GENERATED-SUMMARY")
            self.assertNotIn(raw_marker, json.dumps(content, sort_keys=True))
            self.assertEqual(content["raw_locator"]["tool_call_id"], tool_call_id)
            self.assertEqual(content["raw_locator"]["event_type"], "tool_result")
            self.assertEqual(content["raw_locator"]["log"], "logs/events.jsonl")
            self.assertIn(tool_call_id, content["retrieval_hint"])
            self.assertEqual(seen["tool_name"], "daemon")
            self.assertEqual(seen["tool_call_id"], tool_call_id)
            self.assertIn("Retain the exact raw-first marker", seen["user_prompt"])
            self.assertIn(raw_marker, seen["user_prompt"])

            raw_events = [
                fields
                for kind, fields in events
                if kind == "tool_result" and fields.get("tool_call_id") == tool_call_id
            ]
            self.assertEqual(len(raw_events), 1)
            self.assertIn(raw_marker, str(raw_events[0]["result"]))
            generated_events = [
                fields
                for kind, fields in events
                if kind == "apriori_summary_generated" and fields.get("tool_call_id") == tool_call_id
            ]
            self.assertEqual(len(generated_events), 1)
            self.assertEqual(
                generated_events[0]["generated_summary"],
                "DAEMON-GENERATED-SUMMARY",
            )
            self.assertNotIn(raw_marker, json.dumps(generated_events[0], sort_keys=True))
            self.assertLess(
                _event_index(events, "tool_result", tool_call_id),
                _event_index(events, "apriori_summary_generated", tool_call_id),
            )
        finally:
            agent.stop(timeout=1.0)


if __name__ == "__main__":
    unittest.main()
