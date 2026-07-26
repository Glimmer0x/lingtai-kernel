"""Focused canonical grep action/input tests.

This module is intentionally self-contained and imports the exact candidate
source tree before any LingTai import. It uses retained work directories under
artifacts/grep-action-input-worker/test-work; tests never remove them.
"""
from __future__ import annotations

import copy
import json
import sys
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

CANDIDATE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CANDIDATE / "src"))

import lingtai  # noqa: E402
from lingtai.agent import Agent  # noqa: E402
from lingtai.kernel.llm.base import FunctionSchema, ToolCall  # noqa: E402
from lingtai.kernel.loop_guard import LoopGuard  # noqa: E402
from lingtai.kernel.tool_executor import ToolExecutor  # noqa: E402
from lingtai.kernel.tool_result_summary import (  # noqa: E402
    APRIORI_SUMMARY_CAP,
    APRIORI_SUMMARY_MARKER,
    summary_requested,
)
from lingtai.llm.anthropic.adapter import _build_tools as build_anthropic_tools  # noqa: E402
from lingtai.llm.openai.adapter import (  # noqa: E402
    _build_responses_tools,
    _build_tools as build_chat_tools,
)
from lingtai.services.file_io import GrepMatch, LocalFileIOService, TraversalStats  # noqa: E402
from lingtai.tools import grep as grep_module  # noqa: E402


WORK_ROOT = CANDIDATE / "artifacts" / "grep-action-input-worker" / "test-work"
WORK_ROOT.mkdir(parents=True, exist_ok=True)


class RecordingFileIO:
    """Recording service used to prove malformed calls never reach FileIO."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.last_traversal = TraversalStats()

    def grep(self, pattern, *, path, max_results, glob_filter):
        self.calls.append((pattern, path, max_results, glob_filter))
        return [GrepMatch(path=str(path) + "/hit.py", line_number=1, line="needle")]


def _new_workdir(label: str) -> Path:
    path = WORK_ROOT / f"{label}-{time.time_ns()}"
    path.mkdir(parents=True, exist_ok=False)
    return path


def _service() -> MagicMock:
    service = MagicMock()
    service.provider = "gemini"
    service.model = "grep-test"
    service.get_adapter.return_value = MagicMock()
    return service


def _agent(label: str, *, file_io=None) -> Agent:
    return Agent(
        service=_service(),
        agent_name=f"grep-{label}",
        working_dir=_new_workdir(label),
        capabilities=["grep"],
        disable=["read", "write", "edit", "glob"],
        file_io=file_io,
    )


def _handler(agent: Agent):
    handler = agent._tool_handlers["grep"]
    candidate_source = CANDIDATE / "src"
    assert Path(lingtai.__file__).resolve().is_relative_to(candidate_source)
    assert Path(grep_module.__file__).resolve().is_relative_to(candidate_source)
    assert Path(handler.__code__.co_filename).resolve() == candidate_source / "lingtai/tools/grep/__init__.py"
    return handler


class GrepActionInputTests(unittest.TestCase):
    def test_raw_agent_schema_provider_envelopes_and_prompt(self):
        agent = _agent("schema")
        try:
            handler = _handler(agent)
            raw = grep_module.get_schema()
            self.assertEqual(raw["required"], ["action", "input"])
            self.assertFalse(raw["additionalProperties"])
            self.assertEqual(set(raw["properties"]), {"action", "input"})
            self.assertNotIn("reasoning", raw["properties"])

            model_schema = next(s for s in agent._build_tool_schemas() if s.name == "grep")
            self.assertEqual(model_schema.parameters["required"], ["action", "input"])
            self.assertEqual(
                set(model_schema.parameters["properties"]), {"action", "input", "reasoning"}
            )
            self.assertFalse(model_schema.parameters["additionalProperties"])
            branches = model_schema.parameters["properties"]["input"]["anyOf"]
            self.assertEqual(branches[0]["required"], ["pattern"])
            self.assertEqual(branches[1]["required"], [])
            self.assertTrue(
                all("reasoning" not in branch.get("properties", {}) for branch in branches)
            )

            schema = FunctionSchema("grep", grep_module.get_description(), model_schema.parameters)
            chat = build_chat_tools([schema])
            responses = _build_responses_tools([schema])
            anthropic = build_anthropic_tools([schema])
            self.assertEqual(chat[0]["function"]["parameters"], model_schema.parameters)
            self.assertEqual(responses[0]["parameters"], model_schema.parameters)
            self.assertEqual(anthropic[0]["input_schema"], model_schema.parameters)
            self.assertEqual(schema.to_dict()["parameters"], model_schema.parameters)

            prompt = agent._build_system_prompt()
            self.assertIn("### grep", prompt)
            grep_section = prompt.split("### grep\n", 1)[1].split("\n\n### ", 1)[0]
            self.assertNotIn("omit action", grep_section)
            self.assertIn("grep(action='grep'", grep_section)
            self.assertIn("reasoning='...')", grep_section)

            manual = handler({"action": "manual", "input": {}, "reasoning": "load the guide"})
            self.assertEqual(manual["status"], "ok")
            self.assertIn(
                'grep({"action": "grep", "input": {"pattern": "class Agent|def handle"',
                manual["manual"],
            )
            self.assertIn('"reasoning": "locate the handler before reading it"', manual["manual"])
            self.assertIn(
                '{"action":"manual","input":{},"reasoning":"load the installed file guide"}',
                manual["manual"],
            )
            self.assertNotIn(
                'tool name: `action="read"`, `"write"`, `"edit"`, `"glob"`, or `"grep"`',
                manual["manual"],
            )
            self.assertTrue(manual["manual_path"].endswith("capabilities/file-manual/SKILL.md"))
            self.assertEqual(manual["current_setting"]["source"], "missing")
            self.assertTrue(Path(manual["manual_path"]).is_file())
        finally:
            agent.stop(timeout=1.0)

    def test_strict_malformed_and_unhashable_calls_precede_file_io(self):
        recording = RecordingFileIO()
        agent = _agent("strict", file_io=recording)
        try:
            handler = _handler(agent)
            malformed = [
                None,
                [],
                {},
                {"action": "grep"},
                {"input": {"pattern": "needle"}},
                {"action": [], "input": {}},
                {1: "root-key", "action": "grep", "input": {"pattern": "needle"}},
                {"action": "grep", "input": []},
                {"action": "grep", "input": {1: "input-key"}},
                {"action": "grep", "input": {"pattern": "needle", "summary": 1}},
                {"action": "grep", "input": {"pattern": "needle", "unknown": []}},
                {"action": "grep", "input": {"pattern": "needle"}, "summary": True},
                {"action": "manual", "input": {"pattern": "needle"}},
            ]
            for args in malformed:
                result = handler(args)
                self.assertEqual(result["status"], "error", args)
                self.assertIn("current_setting", result)
            self.assertEqual(recording.calls, [])

            result = handler({"action": "grep", "input": {"pattern": "needle"}, "reasoning": "find it"})
            self.assertEqual(result["count"], 1)
            self.assertEqual(len(recording.calls), 1)
            self.assertIsNone(recording.calls[0][3])
        finally:
            agent.stop(timeout=1.0)

    def test_local_file_io_semantics_and_error_paths(self):
        root = _new_workdir("local")
        service = LocalFileIOService(root=root)
        agent = Agent(
            service=_service(), agent_name="grep-local", working_dir=root,
            capabilities=["grep"], disable=["read", "write", "edit", "glob"], file_io=service,
        )
        try:
            handler = _handler(agent)
            (root / "one.py").write_text("needle\nother\n", encoding="utf-8")
            (root / "two.txt").write_text("needle\n", encoding="utf-8")
            (root / "broken.py").write_bytes(bytes([255, 254, 0]))
            # A non-capped service call reaches the invalid UTF-8 file and records
            # the binary skip; the public cap is checked separately below.
            all_matches = service.grep("needle", path=str(root), max_results=200, glob_filter="*.py")
            self.assertEqual(len(all_matches), 1)
            self.assertEqual(service.last_traversal.files_skipped_binary, 1)

            result = handler({
                "action": "grep",
                "input": {"pattern": "needle", "path": ".", "glob": "*.py", "max_matches": 1, "summary": False},
                "reasoning": "find one Python match",
            })
            self.assertEqual(result["count"], 1)
            self.assertTrue(all(match["file"].endswith(".py") for match in result["matches"]))
            self.assertTrue(result["truncated"])

            invalid = handler({"action": "grep", "input": {"pattern": "[", "path": "."}})
            self.assertEqual(invalid["status"], "error")
            self.assertIn("Grep failed", invalid["message"])
        finally:
            agent.stop(timeout=1.0)

    def test_settings_missing_valid_hot_reload_invalid_secret_free_and_inert(self):
        agent = _agent("settings")
        try:
            handler = _handler(agent)
            target = agent.working_dir / "settings"
            target.mkdir(parents=True, exist_ok=True)
            (agent.working_dir / "match.py").write_text("needle\n", encoding="utf-8")
            args = {"action": "grep", "input": {"pattern": "needle", "path": "."}}
            missing = handler(args)
            self.assertEqual(missing["current_setting"]["source"], "missing")
            baseline = dict(missing)
            baseline.pop("current_setting")
            prompt = agent._build_system_prompt()
            schema = copy.deepcopy(grep_module.get_schema())

            settings_file = target / "grep.json"
            settings_file.write_bytes(b'{"schema_version":1}')
            valid = handler(args)
            self.assertEqual(valid["current_setting"]["source"], "settings/grep.json")
            self.assertNotEqual(missing["current_setting"]["settings_hash"], valid["current_setting"]["settings_hash"])
            value = dict(valid)
            value.pop("current_setting")
            self.assertEqual(value, baseline)
            self.assertEqual(agent._build_system_prompt(), prompt)
            self.assertEqual(grep_module.get_schema(), schema)

            settings_file.write_bytes(b'{ "schema_version" : 1 }\n')
            hot = handler(args)
            self.assertNotEqual(valid["current_setting"]["settings_hash"], hot["current_setting"]["settings_hash"])
            self.assertNotEqual(
                valid["current_setting"]["settings_revision"],
                hot["current_setting"]["settings_revision"],
            )
            hot_value = dict(hot)
            hot_value.pop("current_setting")
            self.assertEqual(hot_value, baseline)
            self.assertEqual(agent._build_system_prompt(), prompt)

            sentinel = "SECRET-GREP-SENTINEL"
            settings_file.write_text(json.dumps({"schema_version": 1, "secret": sentinel}), encoding="utf-8")
            invalid = handler(args)
            self.assertEqual(invalid["current_setting"]["source"], "settings_error")
            self.assertIn("settings_error", invalid["current_setting"])
            self.assertNotIn(sentinel, json.dumps(invalid, sort_keys=True))
            self.assertNotIn(sentinel, agent._build_system_prompt())
            invalid_value = dict(invalid)
            invalid_value.pop("current_setting")
            self.assertEqual(invalid_value, baseline)
            self.assertEqual(agent._build_system_prompt(), prompt)
        finally:
            agent.stop(timeout=1.0)

    def test_actual_handler_executor_serial_parallel_and_root_rejection(self):
        recording = RecordingFileIO()
        agent = _agent("summary-actual", file_io=recording)
        events: list[tuple[str, dict]] = []
        prompts: list[tuple[str, str]] = []

        def logger(event_type, **fields):
            events.append((event_type, fields))

        def make_tool_result(name, result, **fields):
            return {"role": "tool", "name": name, "content": result, **fields}

        def summarizer(_system, prompt, _tool_name, tool_call_id):
            prompts.append((tool_call_id, prompt))
            return f"actual-summary-{tool_call_id}"

        try:
            _handler(agent)
            executor = ToolExecutor(
                dispatch_fn=agent._dispatch_tool,
                make_tool_result_fn=make_tool_result,
                guard=LoopGuard(),
                known_tools={"grep"},
                parallel_safe_tools={"grep"},
                logger_fn=logger,
                working_dir=agent.working_dir,
                summarizer_fn=summarizer,
            )
            serial, intercepted, _ = executor.execute([
                ToolCall(
                    name="grep",
                    args={
                        "action": "grep",
                        "input": {"pattern": "needle", "summary": True},
                        "reasoning": "retain the exact grep hit",
                    },
                    id="actual-serial",
                )
            ])
            self.assertFalse(intercepted)
            self.assertEqual(
                serial[0]["content"]["generated_summary"],
                "actual-summary-actual-serial",
            )
            self.assertEqual(prompts[0][0], "actual-serial")
            self.assertIn("hit.py", prompts[0][1])
            serial_raw = next(
                i for i, (kind, fields) in enumerate(events)
                if kind == "tool_result" and fields.get("tool_call_id") == "actual-serial"
            )
            serial_generated = next(
                i for i, (kind, fields) in enumerate(events)
                if kind == "apriori_summary_generated" and fields.get("tool_call_id") == "actual-serial"
            )
            serial_visible = next(
                i for i, (kind, fields) in enumerate(events)
                if kind == "tool_result_model_visible" and fields.get("tool_call_id") == "actual-serial"
            )
            self.assertLess(serial_raw, serial_generated)
            self.assertLess(serial_generated, serial_visible)
            self.assertIn("current_setting", events[serial_raw][1]["result"])

            parallel, intercepted, _ = executor.execute([
                ToolCall(
                    name="grep",
                    args={
                        "action": "grep",
                        "input": {"pattern": "one", "summary": True},
                        "reasoning": "retain parallel one",
                    },
                    id="actual-parallel-1",
                ),
                ToolCall(
                    name="grep",
                    args={
                        "action": "grep",
                        "input": {"pattern": "two", "summary": True},
                        "reasoning": "retain parallel two",
                    },
                    id="actual-parallel-2",
                ),
            ])
            self.assertFalse(intercepted)
            self.assertEqual(
                [item["content"]["generated_summary"] for item in parallel],
                [
                    "actual-summary-actual-parallel-1",
                    "actual-summary-actual-parallel-2",
                ],
            )
            for call_id in ("actual-parallel-1", "actual-parallel-2"):
                raw_index = next(
                    i for i, (kind, fields) in enumerate(events)
                    if kind == "tool_result" and fields.get("tool_call_id") == call_id
                )
                generated_index = next(
                    i for i, (kind, fields) in enumerate(events)
                    if kind == "apriori_summary_generated" and fields.get("tool_call_id") == call_id
                )
                visible_index = next(
                    i for i, (kind, fields) in enumerate(events)
                    if kind == "tool_result_model_visible" and fields.get("tool_call_id") == call_id
                )
                self.assertLess(raw_index, generated_index)
                self.assertLess(generated_index, visible_index)
                self.assertIn("current_setting", events[raw_index][1]["result"])

            prompt_count = len(prompts)
            rejected, _, _ = executor.execute([
                ToolCall(
                    name="grep",
                    args={
                        "action": "grep",
                        "input": {"pattern": "needle", "summary": False},
                        "summary": True,
                    },
                    id="actual-root-rejected",
                )
            ])
            self.assertEqual(rejected[0]["content"]["status"], "error")
            self.assertIn("only root action, input", rejected[0]["content"]["message"])
            self.assertEqual(len(prompts), prompt_count)
        finally:
            agent.stop(timeout=1.0)

    def test_summary_executor_serial_parallel_raw_first_and_strict_nested_true(self):
        events: list[tuple[str, dict]] = []

        def logger(event_type, **fields):
            events.append((event_type, fields))

        def make_tool_result(name, result, **fields):
            return {"role": "tool", "name": name, "content": result, **fields}

        raw_by_id = {
            "serial": {"matches": [{"file": "serial.py"}]},
            "parallel-1": {"matches": [{"file": "one.py"}]},
            "parallel-2": {"matches": [{"file": "two.py"}]},
        }
        seen: list[str] = []

        def summarizer(_system, prompt, _tool_name, tool_call_id):
            seen.append(prompt)
            return f"summary-{tool_call_id}"

        executor = ToolExecutor(
            dispatch_fn=lambda tc: raw_by_id[tc.id],
            make_tool_result_fn=make_tool_result,
            guard=LoopGuard(), known_tools={"grep"}, logger_fn=logger,
            working_dir=WORK_ROOT, summarizer_fn=summarizer,
            parallel_safe_tools={"grep"},
        )
        serial_results, _, _ = executor.execute([ToolCall(
            name="grep",
            args={"action": "grep", "input": {"pattern": "x", "summary": True}, "reasoning": "retain serial"},
            id="serial",
        )])
        self.assertEqual(serial_results[0]["content"]["artifact"], APRIORI_SUMMARY_MARKER)
        self.assertIn("retain serial", seen[0])
        serial_raw = next(i for i, (kind, fields) in enumerate(events) if kind == "tool_result" and fields.get("tool_call_id") == "serial")
        serial_visible = next(i for i, (kind, fields) in enumerate(events) if kind == "tool_result_model_visible" and fields.get("tool_call_id") == "serial")
        self.assertLess(serial_raw, serial_visible)

        parallel_results, _, _ = executor.execute([
            ToolCall(name="grep", args={"action": "grep", "input": {"pattern": "x", "summary": True}, "reasoning": "retain one"}, id="parallel-1"),
            ToolCall(name="grep", args={"action": "grep", "input": {"pattern": "x", "summary": True}, "reasoning": "retain two"}, id="parallel-2"),
        ])
        self.assertEqual([r["content"]["generated_summary"] for r in parallel_results], ["summary-parallel-1", "summary-parallel-2"])
        for call_id in ("parallel-1", "parallel-2"):
            raw_index = next(i for i, (kind, fields) in enumerate(events) if kind == "tool_result" and fields.get("tool_call_id") == call_id)
            visible_index = next(i for i, (kind, fields) in enumerate(events) if kind == "tool_result_model_visible" and fields.get("tool_call_id") == call_id)
            self.assertLess(raw_index, visible_index)

        self.assertTrue(summary_requested({"input": {"summary": True}, "summary": False}))
        self.assertFalse(summary_requested({"input": {"summary": False}, "summary": True}))
        self.assertFalse(summary_requested({"input": {"summary": 1}, "summary": True}))
        self.assertFalse(summary_requested({"input": None, "summary": True}))

        errors = []
        no_gateway = ToolExecutor(
            dispatch_fn=lambda _tc: {"status": "error", "message": "EXACT-ERROR"},
            make_tool_result_fn=make_tool_result,
            guard=LoopGuard(), known_tools={"grep"}, logger_fn=lambda e, **f: errors.append((e, f)),
            working_dir=WORK_ROOT, summarizer_fn=summarizer,
        )
        error_result, _, _ = no_gateway.execute([ToolCall(
            name="grep", args={"action": "grep", "input": {"pattern": "x", "summary": True}}, id="error",
        )])
        self.assertEqual(error_result[0]["content"]["message"], "EXACT-ERROR")
        self.assertNotIn(APRIORI_SUMMARY_MARKER, error_result[0]["content"])

        closed = ToolExecutor(
            dispatch_fn=lambda _tc: {"matches": []}, make_tool_result_fn=make_tool_result,
            guard=LoopGuard(), known_tools={"grep"}, logger_fn=lambda *_a, **_k: None,
            working_dir=WORK_ROOT, summarizer_fn=None,
        )
        no_gateway_result, _, _ = closed.execute([ToolCall(
            name="grep", args={"action": "grep", "input": {"pattern": "x", "summary": True}}, id="nogateway",
        )])
        self.assertEqual(no_gateway_result[0]["content"]["summary_kind"], "apriori_error")

        too_big = ToolExecutor(
            dispatch_fn=lambda _tc: {"matches": "z" * (APRIORI_SUMMARY_CAP + 1)}, make_tool_result_fn=make_tool_result,
            guard=LoopGuard(), known_tools={"grep"}, logger_fn=lambda *_a, **_k: None,
            working_dir=WORK_ROOT, summarizer_fn=summarizer,
        )
        cap_result, _, _ = too_big.execute([ToolCall(
            name="grep", args={"action": "grep", "input": {"pattern": "x", "summary": True}}, id="cap",
        )])
        self.assertEqual(cap_result[0]["content"]["summary_kind"], "apriori_cap_refused")


if __name__ == "__main__":
    unittest.main()
