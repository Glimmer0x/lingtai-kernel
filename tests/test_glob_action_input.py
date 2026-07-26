"""Independent coverage for the canonical ``glob`` action/input migration.

This module intentionally uses persistent, unique workspaces under the task's
artifact directory. It does not delete test state, invoke pytest, or rely on a
temporary-file lifecycle; the parent validation harness runs the equivalent
checks with retained direct Python calls.
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path
from unittest import TestCase
from unittest.mock import MagicMock

_WORKTREE = Path(__file__).resolve().parents[1]
_SRC = _WORKTREE / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from lingtai.agent import Agent  # noqa: E402
from lingtai.kernel.llm.base import ToolCall, WIRE_TOOL_DESCRIPTION  # noqa: E402
from lingtai.kernel.loop_guard import LoopGuard  # noqa: E402
from lingtai.kernel.tool_executor import ToolExecutor  # noqa: E402
from lingtai.kernel.tool_result_summary import summary_requested  # noqa: E402
from lingtai.llm.anthropic.adapter import _build_tools as anthropic_tools  # noqa: E402
from lingtai.llm.openai.adapter import (  # noqa: E402
    _build_responses_tools,
    _build_tools,
)
from lingtai.services.file_io import LocalFileIOService  # noqa: E402
from lingtai.tools import glob as glob_tool  # noqa: E402

_ARTIFACT_ROOT = _WORKTREE / "artifacts" / "glob-action-input-worker"


def _workspace(label: str) -> Path:
    path = _ARTIFACT_ROOT / f"{label}-{uuid.uuid4().hex}"
    path.mkdir(parents=True, exist_ok=False)
    return path


def _install_manual(workdir: Path) -> tuple[str, Path]:
    path = workdir / ".library" / "intrinsic" / "capabilities" / "file-manual" / "SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "---\nname: file-manual\n---\n\n# retained glob manual\n"
    path.write_text(body, encoding="utf-8")
    return body, path


def _actual_agent(label: str) -> Agent:
    service = MagicMock()
    service.provider = "gemini"
    service.model = "glob-action-input-test"
    service.get_adapter.return_value = MagicMock()
    return Agent(
        service=service,
        agent_name="glob-surface",
        working_dir=_workspace(label),
        capabilities=["glob"],
    )


class _Stats:
    truncated_reason = None
    visited = 0
    elapsed_ms = 0
    dirs_pruned = 0


class _RecordingFileIO:
    def __init__(self, result: list[str] | None = None):
        self.calls: list[tuple[str, str]] = []
        self.result = result if result is not None else []
        self.last_traversal = _Stats()
        self.error: Exception | None = None

    def glob(self, pattern: str, root: str | None = None) -> list[str]:
        if self.error is not None:
            raise self.error
        self.calls.append((pattern, str(root)))
        return list(self.result)


class _StubAgent:
    def __init__(self, workdir: Path, file_io: object | None = None):
        self._working_dir = workdir
        self._file_io = file_io or _RecordingFileIO(["b", "a"])
        self.handler = None
        self.schema = None
        self.description = None

    def add_tool(self, name: str, *, handler=None, schema=None, description="", **_kwargs):
        self.handler = handler
        self.schema = schema
        self.description = description


class GlobActionInputTests(TestCase):
    def setUp(self) -> None:
        self.workdir = _workspace("handler")
        _install_manual(self.workdir)
        self.file_io = _RecordingFileIO(["b", "a"])
        agent = _StubAgent(self.workdir, self.file_io)
        glob_tool.setup(agent)
        self.agent = agent
        self.handle = agent.handler

    def test_raw_schema_is_canonical_closed_and_nested(self) -> None:
        schema = glob_tool.get_schema()
        self.assertEqual(schema["type"], "object")
        self.assertEqual(set(schema["properties"]), {"action", "input"})
        self.assertEqual(schema["required"], ["action", "input"])
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(schema["properties"]["action"]["enum"], ["glob", "manual"])
        input_schema = schema["properties"]["input"]
        self.assertEqual(len(input_schema["anyOf"]), 2)
        ordinary, manual = input_schema["anyOf"]
        self.assertEqual(set(ordinary["properties"]), {"pattern", "path", "summary"})
        self.assertEqual(ordinary["required"], ["pattern"])
        self.assertFalse(ordinary["additionalProperties"])
        self.assertEqual(ordinary["properties"]["pattern"]["type"], "string")
        self.assertEqual(ordinary["properties"]["path"]["type"], "string")
        self.assertEqual(ordinary["properties"]["summary"]["type"], "boolean")
        self.assertIs(ordinary["properties"]["summary"]["default"], False)
        self.assertEqual(manual["properties"], {})
        self.assertEqual(manual["required"], [])
        self.assertFalse(manual["additionalProperties"])

    def test_description_and_prompt_owned_glob_prose_are_migrated(self) -> None:
        description = glob_tool.get_description()
        self.assertNotIn("omit action", description)
        self.assertNotIn("legacy ordinary", description)
        self.assertIn("glob(action='glob'", description)
        self.assertIn("input={'pattern':", description)
        self.assertIn("reasoning='...'", description)
        self.assertIn("glob(action='manual'", description)

    def test_handler_accepts_both_reasoning_metadata_paths_without_mutation(self) -> None:
        first = {"action": "glob", "input": {"pattern": "*.py", "summary": True}, "reasoning": "retain paths"}
        second = {"action": "glob", "input": {"pattern": "*.md"}, "_reasoning": "retain names"}
        first_snapshot = {"action": "glob", "input": dict(first["input"]), "reasoning": first["reasoning"]}
        second_snapshot = {"action": "glob", "input": dict(second["input"]), "_reasoning": second["_reasoning"]}
        self.assertEqual(self.handle(first)["matches"], ["b", "a"])
        self.assertEqual(self.handle(second)["matches"], ["b", "a"])
        self.assertEqual(first, first_snapshot)
        self.assertEqual(second, second_snapshot)
        self.assertEqual(self.file_io.calls, [("*.py", str(self.workdir)), ("*.md", str(self.workdir))])

    def test_manual_is_empty_nested_input_and_returns_installed_body_path_setting(self) -> None:
        body, path = _install_manual(self.workdir)
        result = self.handle({"action": "manual", "input": {}})
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["manual"], body)
        self.assertEqual(result["manual_path"], str(path))
        self.assertIn("current_setting", result)
        self.assertFalse(self.file_io.calls)
        self.assertEqual(self.handle({"action": "manual", "input": {"pattern": "*.py"}})["status"], "error")
        self.assertFalse(self.file_io.calls)

    def test_strict_bad_nonmapping_unhashable_and_flat_inputs_never_call_fileio(self) -> None:
        invalid = [
            None,
            [],
            {"action": "glob"},
            {"action": "glob", "pattern": "*.py"},
            {"action": "glob", "input": []},
            {"action": ["glob"], "input": {"pattern": "*.py"}},
            {"action": "glob", "input": {"pattern": "*.py", "extra": 1}},
            {"action": "glob", "input": {"pattern": "*.py", "reasoning": "nested"}},
            {"action": "glob", "input": {"pattern": "*.py", "summary": 1}},
            {"action": "glob", "input": {"pattern": []}},
            {"action": "glob", "input": {"pattern": "*.py"}, "summary": True},
        ]
        for args in invalid:
            with self.subTest(args=args):
                result = self.handle(args)
                self.assertEqual(result["status"], "error")
                self.assertIn("current_setting", result)
        self.assertFalse(self.file_io.calls)

    def test_real_fileio_preserves_recursive_exclusion_sorting_and_path_resolution(self) -> None:
        (self.workdir / "z.py").write_text("z", encoding="utf-8")
        (self.workdir / "a.py").write_text("a", encoding="utf-8")
        (self.workdir / "nested").mkdir()
        (self.workdir / "nested" / "m.py").write_text("m", encoding="utf-8")
        (self.workdir / ".git").mkdir()
        (self.workdir / ".git" / "hidden.py").write_text("hidden", encoding="utf-8")
        real = _StubAgent(self.workdir, LocalFileIOService(root=self.workdir))
        glob_tool.setup(real)
        recursive = real.handler({"action": "glob", "input": {"pattern": "**/*.py", "path": "."}})
        flat = real.handler({"action": "glob", "input": {"pattern": "*.py", "path": "."}})
        self.assertEqual(recursive["status"] if "status" in recursive else "ok", "ok")
        self.assertEqual(recursive["matches"], [str(self.workdir / "nested" / "m.py")])
        self.assertEqual(flat["matches"], sorted(flat["matches"]))
        self.assertEqual(set(flat["matches"]), {str(self.workdir / "a.py"), str(self.workdir / "z.py"), str(self.workdir / "nested" / "m.py")})
        self.assertNotIn("hidden.py", " ".join(recursive["matches"] + flat["matches"]))
        self.assertEqual(recursive["count"], 1)
        self.assertEqual(flat["count"], 3)

    def test_runtime_fileio_errors_keep_source_error_and_setting(self) -> None:
        self.file_io.error = RuntimeError("walk failed")
        result = self.handle({"action": "glob", "input": {"pattern": "*.py"}})
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["message"], "Glob failed: walk failed")
        self.assertIn("current_setting", result)

    def test_missing_valid_hot_and_invalid_settings_are_behavior_inert(self) -> None:
        missing = self.handle({"action": "glob", "input": {"pattern": "*.py"}})
        settings = self.workdir / "settings" / "glob.json"
        settings.parent.mkdir(parents=True, exist_ok=True)
        settings.write_text('{"schema_version": 1}', encoding="utf-8")
        valid = self.handle({"action": "glob", "input": {"pattern": "*.py"}})
        settings.write_text('{ "schema_version": 1 }', encoding="utf-8")
        hot = self.handle({"action": "glob", "input": {"pattern": "*.py"}})
        secret = "DO-NOT-LEAK-GLOB-SECRET"
        settings.write_text(
            '{"schema_version": 2, "future": "DO-NOT-LEAK-GLOB-SECRET"}',
            encoding="utf-8",
        )
        invalid = self.handle({"action": "glob", "input": {"pattern": "*.py"}})
        self.assertEqual(missing["matches"], valid["matches"])
        self.assertEqual(valid["matches"], hot["matches"])
        self.assertEqual(hot["matches"], invalid["matches"])
        self.assertEqual(missing["current_setting"]["source"], "missing")
        self.assertEqual(valid["current_setting"]["source"], "settings/glob.json")
        self.assertEqual(hot["current_setting"]["source"], "settings/glob.json")
        self.assertNotEqual(
            hot["current_setting"]["settings_revision"],
            valid["current_setting"]["settings_revision"],
        )
        self.assertEqual(invalid["current_setting"]["source"], "settings_error")
        self.assertIn("settings_error", invalid["current_setting"])
        self.assertNotIn(secret, repr(invalid["current_setting"]))
        invalid["current_setting"]["source"] = "tampered"
        reread = self.handle({"action": "glob", "input": {"pattern": "*.py"}})
        self.assertEqual(reread["current_setting"]["source"], "settings_error")


class ActualAgentGlobSurfaceTests(TestCase):
    def _agent(self) -> Agent:
        return _actual_agent("actual-agent")

    @staticmethod
    def _release(agent: Agent) -> None:
        agent.stop(timeout=1.0)

    def test_actual_agent_provider_envelopes_prompt_and_real_manual(self) -> None:
        agent = self._agent()
        try:
            schema = next(item for item in agent._build_tool_schemas() if item.name == "glob")
            self.assertEqual(
                set(schema.parameters["properties"]),
                {"action", "input", "reasoning"},
            )
            self.assertEqual(schema.parameters["required"], ["action", "input"])
            self.assertFalse(schema.parameters["additionalProperties"])
            self.assertTrue(
                all(
                    "reasoning" not in branch.get("properties", {})
                    for branch in schema.parameters["properties"]["input"]["anyOf"]
                )
            )
            envelopes = (
                _build_tools([schema]),
                _build_responses_tools([schema]),
                anthropic_tools([schema]),
            )
            for envelope in envelopes:
                self.assertEqual(len(envelope), 1)
                self.assertEqual(
                    envelope[0].get("name") or envelope[0]["function"]["name"],
                    "glob",
                )
                provider_schema = (
                    envelope[0].get("parameters")
                    or envelope[0].get("input_schema")
                    or envelope[0]["function"]["parameters"]
                )
                self.assertEqual(
                    set(provider_schema["properties"]),
                    {"action", "input", "reasoning"},
                )
                self.assertEqual(provider_schema["required"], ["action", "input"])
                self.assertFalse(provider_schema["additionalProperties"])
                provider_description = (
                    envelope[0].get("description")
                    or envelope[0]["function"]["description"]
                )
                self.assertEqual(provider_description, WIRE_TOOL_DESCRIPTION)
            batches = agent._build_system_prompt_batches()
            prompt = agent._build_system_prompt()
            self.assertEqual(prompt, "\n\n".join(filter(None, batches)))
            glob_section = prompt.split("### glob\n", 1)[1].split("\n\n### ", 1)[0]
            self.assertNotIn("omit action", glob_section)
            self.assertIn("glob(action='glob'", glob_section)
            self.assertIn("reasoning='...'", glob_section)
            manual = agent._tool_handlers["glob"](
                {
                    "action": "manual",
                    "input": {},
                    "reasoning": "load the installed file guide",
                }
            )
            self.assertEqual(manual["status"], "ok")
            self.assertIn("# File Manual", manual["manual"])
            self.assertIn('"reasoning": "discover Python files"', manual["manual"])
            self.assertIn(
                '"reasoning":"load the installed file guide"',
                manual["manual"],
            )
            self.assertTrue(
                manual["manual_path"].endswith(
                    "capabilities/file-manual/SKILL.md"
                )
            )
            self.assertEqual(manual["current_setting"]["source"], "missing")
            self.assertEqual(
                Path(glob_tool.__file__).resolve(),
                (_SRC / "lingtai" / "tools" / "glob" / "__init__.py").resolve(),
            )
            self.assertEqual(
                Path(agent._tool_handlers["glob"].__code__.co_filename).resolve(),
                (_SRC / "lingtai" / "tools" / "glob" / "__init__.py").resolve(),
            )
        finally:
            self._release(agent)


class NestedSummaryExecutorTests(TestCase):
    def _executor(self, workdir: Path, events: list[tuple[str, dict]], calls: list[str]) -> ToolExecutor:
        def logger(event_type, **fields):
            events.append((event_type, fields))

        def make_result(name, result, **kwargs):
            return {"role": "tool", "name": name, "content": result, **kwargs}

        def summarize(_system, _user, _tool, _call_id):
            calls.append("summary")
            self.assertTrue(any(event == "tool_result" for event, _fields in events))
            return "summary-body"

        return ToolExecutor(
            dispatch_fn=lambda _tc: {"matches": ["b", "a"], "count": 2},
            make_tool_result_fn=make_result,
            guard=LoopGuard(),
            known_tools={"glob"},
            parallel_safe_tools={"glob"},
            logger_fn=logger,
            working_dir=workdir,
            summarizer_fn=summarize,
        )

    def test_actual_handler_serial_summary_and_root_summary_rejection(self) -> None:
        agent = _actual_agent("summary-actual")
        try:
            (agent.working_dir / "actual-marker.py").write_text(
                "actual marker\n",
                encoding="utf-8",
            )
            events: list[tuple[str, dict]] = []
            prompts: list[str] = []

            def logger(event_type, **fields):
                events.append((event_type, fields))

            def summarize(_system, user_prompt, _tool, _call_id):
                prompts.append(user_prompt)
                return "actual-summary"

            executor = ToolExecutor(
                dispatch_fn=agent._dispatch_tool,
                make_tool_result_fn=lambda name, result, **kwargs: {
                    "role": "tool",
                    "name": name,
                    "content": result,
                    **kwargs,
                },
                guard=LoopGuard(),
                known_tools={"glob"},
                logger_fn=logger,
                working_dir=agent.working_dir,
                summarizer_fn=summarize,
            )
            result, intercepted, _ = executor.execute(
                [
                    ToolCall(
                        name="glob",
                        args={
                            "action": "glob",
                            "input": {
                                "pattern": "actual-marker.py",
                                "summary": True,
                            },
                            "reasoning": "retain the marker path",
                        },
                        id="actual-summary",
                    )
                ]
            )
            self.assertFalse(intercepted)
            self.assertEqual(
                result[0]["content"]["generated_summary"],
                "actual-summary",
            )
            self.assertEqual(len(prompts), 1)
            self.assertIn("actual-marker.py", prompts[0])
            raw_index = next(
                index
                for index, (event, fields) in enumerate(events)
                if event == "tool_result"
                and fields.get("tool_call_id") == "actual-summary"
            )
            generated_index = next(
                index
                for index, (event, fields) in enumerate(events)
                if event == "apriori_summary_generated"
                and fields.get("tool_call_id") == "actual-summary"
            )
            visible_index = next(
                index
                for index, (event, fields) in enumerate(events)
                if event == "tool_result_model_visible"
                and fields.get("tool_call_id") == "actual-summary"
            )
            self.assertLess(raw_index, generated_index)
            self.assertLess(generated_index, visible_index)
            self.assertIn(
                "current_setting",
                events[raw_index][1]["result"],
            )

            root_result, _, _ = executor.execute(
                [
                    ToolCall(
                        name="glob",
                        args={
                            "action": "glob",
                            "input": {
                                "pattern": "actual-marker.py",
                                "summary": False,
                            },
                            "summary": True,
                        },
                        id="actual-root-rejected",
                    )
                ]
            )
            self.assertEqual(root_result[0]["content"]["status"], "error")
            self.assertEqual(len(prompts), 1)
        finally:
            agent.stop(timeout=1.0)

    def test_serial_nested_summary_is_raw_first_and_root_is_ignored(self) -> None:
        workdir = _workspace("summary-serial")
        events: list[tuple[str, dict]] = []
        calls: list[str] = []
        executor = self._executor(workdir, events, calls)
        raw_first = {"action": "glob", "input": {"pattern": "*.py", "summary": True}, "_reasoning": "paths"}
        result, intercepted, _ = executor.execute([ToolCall(name="glob", args=raw_first, id="serial")])
        self.assertFalse(intercepted)
        self.assertEqual(result[0]["content"]["generated_summary"], "summary-body")
        self.assertEqual(calls, ["summary"])
        raw_index = next(i for i, (event, fields) in enumerate(events) if event == "tool_result" and fields.get("tool_call_id") == "serial")
        summary_index = next(i for i, (event, fields) in enumerate(events) if event == "apriori_summary_generated" and fields.get("tool_call_id") == "serial")
        self.assertLess(raw_index, summary_index)

        events.clear()
        calls.clear()
        root_only = {"action": "glob", "input": {"pattern": "*.py", "summary": False}, "summary": True}
        result, _, _ = executor.execute([ToolCall(name="glob", args=root_only, id="root-ignored")])
        self.assertNotEqual(result[0]["content"], "summary-body")
        self.assertEqual(calls, [])

    def test_parallel_nested_summary_replaces_each_after_raw_logging(self) -> None:
        workdir = _workspace("summary-parallel")
        events: list[tuple[str, dict]] = []
        calls: list[str] = []
        executor = self._executor(workdir, events, calls)
        tool_calls = [
            ToolCall(name="glob", args={"action": "glob", "input": {"pattern": "a", "summary": True}}, id="p1"),
            ToolCall(name="glob", args={"action": "glob", "input": {"pattern": "b", "summary": True}}, id="p2"),
        ]
        result, intercepted, _ = executor.execute(tool_calls)
        self.assertFalse(intercepted)
        self.assertEqual([item["content"]["generated_summary"] for item in result], ["summary-body", "summary-body"])
        self.assertEqual(sorted(calls), ["summary", "summary"])
        for call_id in ("p1", "p2"):
            raw_index = next(i for i, (event, fields) in enumerate(events) if event == "tool_result" and fields.get("tool_call_id") == call_id)
            summary_index = next(i for i, (event, fields) in enumerate(events) if event == "apriori_summary_generated" and fields.get("tool_call_id") == call_id)
            self.assertLess(raw_index, summary_index)

    def test_summary_foundation_uses_nested_presence_and_exact_true(self) -> None:
        self.assertTrue(summary_requested({"input": {"summary": True}, "summary": False}))
        self.assertFalse(summary_requested({"input": {"summary": False}, "summary": True}))
        self.assertFalse(summary_requested({"input": {"summary": 1}, "summary": True}))
        self.assertFalse(summary_requested({"input": [], "summary": True}))
        self.assertTrue(summary_requested({"summary": True}))
