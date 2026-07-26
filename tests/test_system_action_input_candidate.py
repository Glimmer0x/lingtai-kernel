"""Safe focused checks for the canonical system action/input contract.

Run directly with the project runtime interpreter:

    python tests/test_system_action_input_candidate.py

The candidate source is inserted at ``sys.path[0]`` before LingTai imports. One
real candidate Agent proves registration, prompt, provider, and initialized
read-only manual provenance. Every other system action is replaced by a fake
handler before dispatch; this harness never refreshes, sleeps, signals, clears,
summarizes, probes preset connectivity, or invokes nirvana.
"""
from __future__ import annotations

import inspect
import json
import os
import sys
import unittest
from collections.abc import Mapping
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))
assert Path(sys.path[0]).resolve() == SRC.resolve()

import lingtai  # noqa: E402
import lingtai.tools.system as system  # noqa: E402
from lingtai.agent import Agent  # noqa: E402
from lingtai.kernel.llm.base import FunctionSchema, WIRE_TOOL_DESCRIPTION  # noqa: E402
from lingtai.llm.anthropic.adapter import _build_tools as build_anthropic_tools  # noqa: E402
from lingtai.llm.openai.adapter import (  # noqa: E402
    _build_responses_tools,
    _build_tools as build_chat_tools,
)

ARTIFACT_ROOT = ROOT / "artifacts" / "system-action-input-test"
ACTIONS = (
    "refresh",
    "sleep",
    "lull",
    "interrupt",
    "suspend",
    "cpr",
    "clear",
    "nirvana",
    "presets",
    "summarize",
    "manual",
)


class _Service:
    provider = "gemini"
    model = "system-candidate"

    def get_adapter(self):
        return object()


class _FakeAgent:
    def __init__(self, workdir: Path) -> None:
        self._working_dir = workdir


class _OddKeys(Mapping):
    def __init__(self, key) -> None:
        self.key = key

    def __getitem__(self, key):
        return None

    def __iter__(self):
        return iter((self.key,))

    def __len__(self) -> int:
        return 1

    def keys(self):
        return [self.key]


class _ExplodingMapping(Mapping):
    def __getitem__(self, key):
        raise RuntimeError("PRIVATE_MAPPING_SENTINEL")

    def __iter__(self):
        raise RuntimeError("PRIVATE_MAPPING_SENTINEL")

    def __len__(self) -> int:
        return 1


class SystemActionInputCandidate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
        cls.fake_workdir = cls._fresh_dir("fake-agent")
        cls.fake = _FakeAgent(cls.fake_workdir)

        cls.actual_workdir = cls._fresh_dir("actual-agent")
        cls.actual_agent = Agent(
            service=_Service(),
            agent_name="system-candidate-agent",
            working_dir=cls.actual_workdir,
            capabilities=["system"],
        )
        # A plain function class attribute would be rebound by unittest's
        # descriptor protocol, so preserve the registered closure as data.
        cls.actual_handler = staticmethod(cls.actual_agent._intrinsics["system"])
        cls.installed_manual = (
            cls.actual_workdir
            / ".library"
            / "intrinsic"
            / "capabilities"
            / "system-manual"
            / "SKILL.md"
        )

    @classmethod
    def _fresh_dir(cls, stem: str) -> Path:
        candidate = ARTIFACT_ROOT / f"{stem}-{os.getpid()}"
        suffix = 0
        while candidate.exists():
            suffix += 1
            candidate = ARTIFACT_ROOT / f"{stem}-{os.getpid()}-{suffix}"
        candidate.mkdir(parents=True)
        return candidate

    def _setting(self, result: dict, source: str | None) -> dict:
        self.assertIn("current_setting", result)
        value = result["current_setting"]
        if source is not None:
            self.assertEqual(value["source"], source)
        self.assertFalse(value["configurable"])
        self.assertEqual(value["placeholder"], "no-op")
        self.assertIn("settings_revision", value)
        self.assertIn("settings_hash", value)
        self.assertIn("settings/system.json", value["change_hint"])
        return value

    @staticmethod
    def _without_setting(result: dict) -> dict:
        value = dict(result)
        value.pop("current_setting")
        return value

    @staticmethod
    def _valid_calls() -> dict[str, dict]:
        return {
            "refresh": {
                "action": "refresh",
                "input": {"reason": "fake", "preset": "allowed.json", "revert_preset": False},
            },
            "sleep": {"action": "sleep", "input": {"reason": "fake", "force": True}},
            "lull": {"action": "lull", "input": {"address": "peer-lull"}},
            "interrupt": {"action": "interrupt", "input": {"address": "peer-interrupt"}},
            "suspend": {"action": "suspend", "input": {"address": "peer-suspend"}},
            "cpr": {"action": "cpr", "input": {"address": "peer-cpr"}},
            "clear": {
                "action": "clear",
                "input": {"address": "peer-clear", "reason": "fake"},
            },
            "nirvana": {"action": "nirvana", "input": {"address": "peer-nirvana"}},
            "presets": {"action": "presets", "input": {}},
            "summarize": {
                "action": "summarize",
                "input": {
                    "items": [{"tool_call_id": "tc-fake", "summary": "fake summary"}],
                    "rebuild": True,
                },
            },
            "manual": {"action": "manual", "input": {}},
        }

    @staticmethod
    def _fake_handlers(calls: list[tuple]) -> dict[str, object]:
        handlers = {}
        for action in ACTIONS:
            def fake_handler(agent, args, *, _action=action):
                captured = dict(args)
                calls.append((_action, agent, captured))
                return {
                    "status": "fake-ok",
                    "handled": _action,
                    "received": captured,
                    "current_setting": {"spoofed": True},
                }

            handlers[action] = fake_handler
        return handlers

    def test_candidate_origins_intrinsic_closure_and_schemas(self):
        self.assertEqual(
            Path(lingtai.__file__).resolve(),
            (SRC / "lingtai" / "__init__.py").resolve(),
        )
        self.assertEqual(
            Path(system.__file__).resolve(),
            (SRC / "lingtai/tools/system/__init__.py").resolve(),
        )
        self.assertIs(inspect.getmodule(system.handle), system)
        self.assertIs(self.actual_agent._intrinsic_modules["system"], system)
        closure = self.actual_agent._intrinsics["system"]
        self.assertTrue(closure.__defaults__)
        self.assertIs(closure.__defaults__[0], system.handle)

        raw = system.get_schema()
        self.assertEqual(set(raw), {"type", "properties", "required", "additionalProperties"})
        self.assertEqual(set(raw["properties"]), {"action", "input"})
        self.assertEqual(raw["required"], ["action", "input"])
        self.assertFalse(raw["additionalProperties"])
        self.assertNotIn("reasoning", raw["properties"])
        self.assertEqual(tuple(raw["properties"]["action"]["enum"]), ACTIONS)

        branches = raw["properties"]["input"]["anyOf"]
        self.assertEqual(
            [branch["title"] for branch in branches],
            [f"{action} input" for action in ACTIONS],
        )
        expected_properties = {
            "refresh": {"reason", "preset", "revert_preset"},
            "sleep": {"reason", "force"},
            "lull": {"address"},
            "interrupt": {"address"},
            "suspend": {"address"},
            "cpr": {"address"},
            "clear": {"address", "reason"},
            "nirvana": {"address"},
            "presets": set(),
            "summarize": {"items", "rebuild"},
            "manual": set(),
        }
        for action, branch in zip(ACTIONS, branches):
            self.assertFalse(branch["additionalProperties"])
            self.assertEqual(set(branch["properties"]), expected_properties[action])
            self.assertNotIn("reasoning", branch["properties"])
        for action in ("lull", "interrupt", "suspend", "cpr", "clear", "nirvana"):
            branch = branches[ACTIONS.index(action)]
            self.assertEqual(branch["required"], ["address"])
        self.assertEqual(branches[ACTIONS.index("presets")]["required"], [])
        self.assertEqual(branches[ACTIONS.index("manual")]["required"], [])
        summarize = branches[ACTIONS.index("summarize")]
        self.assertEqual(
            summarize["anyOf"],
            [
                {"required": ["items"]},
                {
                    "properties": {
                        "rebuild": {
                            "enum": [True],
                            "description": "Rebuild pending summaries.",
                        }
                    },
                    "required": ["rebuild"],
                },
            ],
        )
        item = summarize["properties"]["items"]["items"]
        self.assertEqual(set(item["properties"]), {"tool_call_id", "summary"})
        self.assertEqual(item["required"], ["tool_call_id", "summary"])
        self.assertFalse(item["additionalProperties"])

        facing = next(
            schema
            for schema in self.actual_agent._build_tool_schemas()
            if schema.name == "system"
        )
        self.assertIsInstance(facing, FunctionSchema)
        self.assertEqual(set(facing.parameters["properties"]), {"action", "input", "reasoning"})
        self.assertEqual(facing.parameters["required"], ["action", "input"])
        self.assertFalse(facing.parameters["additionalProperties"])
        self.assertTrue(
            all(
                "reasoning" not in branch["properties"]
                for branch in facing.parameters["properties"]["input"]["anyOf"]
            )
        )

    def test_prompt_provider_envelopes_and_real_initialized_manual(self):
        prompt = self.actual_agent._prompt_manager.read_section("tools")
        section = prompt.split("### system\n", 1)[1].split("\n\n### ", 1)[0]
        self.assertIn("system(action=..., input={...})", section)
        self.assertIn("strict input object", section)
        self.assertIn("standalone notification tool", section)

        facing = next(
            schema
            for schema in self.actual_agent._build_tool_schemas()
            if schema.name == "system"
        )
        self.assertEqual(facing.description, system.get_description())
        chat = build_chat_tools([facing])[0]
        responses = _build_responses_tools([facing])[0]
        anthropic = build_anthropic_tools([facing])[0]
        self.assertEqual(set(chat), {"type", "function"})
        self.assertEqual(set(chat["function"]), {"name", "description", "parameters"})
        self.assertEqual(set(responses), {"type", "name", "description", "parameters"})
        self.assertEqual(set(anthropic), {"name", "description", "input_schema"})
        for name, description, parameters in (
            (
                chat["function"]["name"],
                chat["function"]["description"],
                chat["function"]["parameters"],
            ),
            (responses["name"], responses["description"], responses["parameters"]),
            (anthropic["name"], anthropic["description"], anthropic["input_schema"]),
        ):
            self.assertEqual(name, "system")
            self.assertEqual(description, WIRE_TOOL_DESCRIPTION)
            self.assertEqual(parameters, facing.parameters)

        init_path = self.actual_workdir / "init.json"
        init_before = init_path.read_bytes() if init_path.is_file() else None
        forbidden = [
            self.actual_workdir / ".sleep",
            self.actual_workdir / ".suspend",
            self.actual_workdir / ".interrupt",
            self.actual_workdir / ".clear",
        ]
        before_forbidden = [path.exists() for path in forbidden]
        real_manual = system._HANDLERS["manual"]

        def forbidden_handler(_agent, _args):
            raise AssertionError("non-manual system handler reached")

        handlers = {action: forbidden_handler for action in ACTIONS}
        handlers["manual"] = real_manual
        with patch.dict(system._HANDLERS, handlers, clear=True):
            result = self.actual_handler(
                {
                    "action": "manual",
                    "input": {},
                    "reasoning": "verify the initialized read-only system manual",
                }
            )

        self.assertEqual(result["status"], "ok")
        self.assertTrue(self.installed_manual.is_file())
        self.assertEqual(Path(result["manual_path"]).resolve(), self.installed_manual.resolve())
        self.assertEqual(result["manual"], self.installed_manual.read_text(encoding="utf-8"))
        self.assertIn("# System Manual", result["manual"])
        self._setting(result, "missing")
        self.assertEqual(before_forbidden, [path.exists() for path in forbidden])
        init_after = init_path.read_bytes() if init_path.is_file() else None
        self.assertEqual(init_before, init_after)

    def test_malformed_calls_reach_zero_patched_handlers(self):
        malformed = [
            None,
            [],
            {},
            {"action": "manual"},
            {"input": {}},
            {"action": "manual", "input": []},
            {"action": "unknown", "input": {}},
            {"action": "check", "input": {}},
            {"action": 1, "input": {}},
            {"action": "manual", "input": {"force": True}},
            {"action": "presets", "input": {"reason": "flat"}},
            {"action": "sleep", "input": {"force": 1}},
            {"action": "refresh", "input": {"reason": 1}},
            {"action": "refresh", "input": {"preset": []}},
            {"action": "refresh", "input": {"revert_preset": "yes"}},
            {"action": "lull", "input": {}},
            {"action": "lull", "input": {"address": ""}},
            {"action": "lull", "input": {"address": 2}},
            {"action": "clear", "input": {"address": "peer", "reason": []}},
            {"action": "summarize", "input": {}},
            {"action": "summarize", "input": {"rebuild": False}},
            {"action": "summarize", "input": {"rebuild": 1}},
            {"action": "summarize", "input": {"items": []}},
            {"action": "summarize", "input": {"items": {}}},
            {"action": "summarize", "input": {"items": [{}]}},
            {
                "action": "summarize",
                "input": {"items": [{"tool_call_id": "", "summary": "x"}]},
            },
            {
                "action": "summarize",
                "input": {"items": [{"tool_call_id": "tc", "summary": 3}]},
            },
            {
                "action": "summarize",
                "input": {
                    "items": [{"tool_call_id": "tc", "summary": "x", "extra": True}]
                },
            },
            {"action": "manual", "input": {}, "reason": "flat"},
            {"action": "manual", "input": {}, "reasoning": None},
            {"action": "manual", "input": {}, "_reasoning": []},
            {"action": "manual", "input": {}, "_tc_id": 5},
            {"action": "manual", "input": _OddKeys([])},
            {"action": "manual", "input": _OddKeys(1)},
            {"action": "manual", "input": _ExplodingMapping()},
            _OddKeys([]),
            _OddKeys(1),
            _ExplodingMapping(),
            {1: "manual", "input": {}},
            {
                "action": "summarize",
                "input": {"items": [_ExplodingMapping()]},
            },
        ]
        calls: list[tuple] = []
        with patch.dict(system._HANDLERS, self._fake_handlers(calls), clear=True):
            for args in malformed:
                with self.subTest(args=repr(args)):
                    result = system.handle(self.fake, args)
                    self.assertEqual(result["status"], "error")
                    self._setting(result, None)
                    self.assertNotIn(
                        "PRIVATE_MAPPING_SENTINEL",
                        json.dumps(result, sort_keys=True),
                    )
        self.assertEqual(calls, [])

    def test_settings_missing_valid_hot_invalid_nonleakage_and_invariance(self):
        workdir = self._fresh_dir("settings-agent")
        fake = _FakeAgent(workdir)
        settings = workdir / "settings" / "system.json"
        settings.parent.mkdir(parents=True, exist_ok=True)
        prompt_before = self.actual_agent._prompt_manager.read_section("tools")
        raw_schema = system.get_schema()
        args = {"action": "presets", "input": {}, "reasoning": "settings evidence"}
        calls: list[tuple] = []

        with patch.dict(system._HANDLERS, self._fake_handlers(calls), clear=True):
            missing = system.handle(fake, args)
            missing_setting = self._setting(missing, "missing")
            self.assertEqual(missing_setting["settings_revision"], "missing")
            self.assertIsNone(missing_setting["settings_hash"])
            missing_body = self._without_setting(missing)

            settings.write_bytes(b'{"schema_version":1}')
            valid = system.handle(fake, args)
            valid_setting = self._setting(valid, "settings/system.json")
            self.assertEqual(len(valid_setting["settings_hash"]), 32)
            self.assertEqual(valid_setting["settings_revision"], valid_setting["settings_hash"])
            self.assertEqual(self._without_setting(valid), missing_body)

            settings.write_bytes(b'{ "schema_version" : 1 }\n')
            hot = system.handle(fake, args)
            hot_setting = self._setting(hot, "settings/system.json")
            self.assertNotEqual(hot_setting["settings_revision"], valid_setting["settings_revision"])
            self.assertNotEqual(hot_setting["settings_hash"], valid_setting["settings_hash"])
            self.assertEqual(self._without_setting(hot), missing_body)

            secret = "SYSTEM_SETTINGS_PRIVATE_SENTINEL"
            private_path = str(settings.resolve())
            invalid_values = [
                '{"schema_version":2}',
                '{"schema_version":"1"}',
                '{"schema_version":1,"secret":"' + secret + '"}',
                json.dumps({"schema_version": 1, "private_path": private_path}),
                '{"schema_version":1,"schema_version":1}',
                "not-json",
            ]
            for text in invalid_values:
                settings.write_text(text, encoding="utf-8")
                invalid = system.handle(fake, args)
                setting = self._setting(invalid, "settings_error")
                self.assertIn("settings_error", setting)
                rendered = json.dumps(invalid, sort_keys=True)
                self.assertNotIn(secret, rendered)
                self.assertNotIn(private_path, rendered)
                self.assertEqual(self._without_setting(invalid), missing_body)

        self.assertEqual(len(calls), 3 + len(invalid_values))
        self.assertTrue(all(call[0] == "presets" for call in calls))
        self.assertEqual(prompt_before, self.actual_agent._prompt_manager.read_section("tools"))
        self.assertNotIn(secret, self.actual_agent._prompt_manager.read_section("tools"))
        self.assertNotIn(private_path, self.actual_agent._prompt_manager.read_section("tools"))
        self.assertEqual(system.get_schema(), raw_schema)

    def test_all_eleven_actions_route_only_to_deterministic_fake_handlers(self):
        calls: list[tuple] = []
        valid = self._valid_calls()
        with patch.dict(system._HANDLERS, self._fake_handlers(calls), clear=True):
            for action in ACTIONS:
                args = json.loads(json.dumps(valid[action]))
                args["_reasoning"] = f"internal-{action}"
                args["_tc_id"] = f"tc-{action}"
                result = system.handle(self.fake, args)
                with self.subTest(action=action):
                    self.assertEqual(result["status"], "fake-ok")
                    self.assertEqual(result["handled"], action)
                    self.assertEqual(result["received"]["action"], action)
                    self.assertEqual(result["received"]["_reasoning"], f"internal-{action}")
                    self.assertEqual(result["received"]["_tc_id"], f"tc-{action}")
                    self.assertNotIn("spoofed", result["current_setting"])
                    self._setting(result, "missing")

            public = {"action": "presets", "input": {}, "reasoning": "public-reason"}
            public_result = system.handle(self.fake, public)
            self.assertEqual(public_result["received"]["_reasoning"], "public-reason")
            self.assertNotIn("reasoning", public_result["received"])

            both = {
                "action": "manual",
                "input": {},
                "reasoning": "public-reason",
                "_reasoning": "internal-reason",
                "_tc_id": "tc-both",
            }
            both_result = system.handle(self.fake, both)
            self.assertEqual(both_result["received"]["_reasoning"], "internal-reason")
            self.assertEqual(both_result["received"]["_tc_id"], "tc-both")

        self.assertEqual([call[0] for call in calls[: len(ACTIONS)]], list(ACTIONS))
        self.assertEqual(len(calls), len(ACTIONS) + 2)
        for action, agent, captured in calls:
            self.assertIs(agent, self.fake)
            self.assertEqual(captured["action"], action)

    def test_all_eleven_action_exceptions_and_invalid_results_are_bounded(self):
        sentinel = "SYSTEM_PRIVATE_ACTION_SENTINEL"
        valid = self._valid_calls()
        for action in ACTIONS:
            calls: list[tuple] = []
            handlers = self._fake_handlers(calls)
            count = [0]

            def boom(_agent, _args):
                count[0] += 1
                raise RuntimeError("/private/system/" + sentinel)

            handlers[action] = boom
            with self.subTest(action=action), patch.dict(
                system._HANDLERS,
                handlers,
                clear=True,
            ):
                result = system.handle(self.fake, valid[action])
                self.assertEqual(count[0], 1)
                self.assertEqual(calls, [])
                self.assertEqual(result["status"], "error")
                self.assertEqual(result["action"], action)
                self.assertEqual(result["message"], "system action failed safely")
                self.assertEqual(result["error_type"], "RuntimeError")
                self._setting(result, "missing")
                self.assertNotIn(sentinel, json.dumps(result, sort_keys=True))
                self.assertNotIn("/private/system", json.dumps(result, sort_keys=True))

        for invalid_result in (None, [], "bad"):
            calls: list[tuple] = []
            handlers = self._fake_handlers(calls)
            handlers["presets"] = lambda _agent, _args, _value=invalid_result: _value
            with self.subTest(invalid_result=repr(invalid_result)), patch.dict(
                system._HANDLERS,
                handlers,
                clear=True,
            ):
                result = system.handle(self.fake, valid["presets"])
                self.assertEqual(result["status"], "error")
                self.assertEqual(result["action"], "presets")
                self.assertEqual(result["message"], "system action returned an invalid result")
                self._setting(result, "missing")
                self.assertEqual(calls, [])

        calls = []
        with patch.object(
            system,
            "read_settings",
            side_effect=OSError("/private/settings/" + sentinel),
        ), patch.dict(system._HANDLERS, self._fake_handlers(calls), clear=True):
            result = system.handle(self.fake, valid["presets"])
        setting = self._setting(result, "settings_error")
        self.assertIn("settings_error", setting)
        rendered = json.dumps(result, sort_keys=True)
        self.assertNotIn(sentinel, rendered)
        self.assertNotIn("/private/settings", rendered)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], "presets")


if __name__ == "__main__":
    unittest.main(verbosity=2)
