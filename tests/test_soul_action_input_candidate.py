"""Safe focused candidate checks for the canonical soul action/input contract.

Run directly with the project runtime interpreter:

    python tests/test_soul_action_input_candidate.py

The candidate source is inserted at sys.path[0] before LingTai imports. This
harness initializes one real candidate Agent for registration/prompt/manual
provenance, then uses only fake action/config/service seams, retained artifacts,
and the disabled flow path; it never calls a live soul action or service.
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
import lingtai.tools.soul as soul  # noqa: E402
from lingtai.agent import Agent  # noqa: E402
from lingtai.kernel.llm.base import FunctionSchema, WIRE_TOOL_DESCRIPTION  # noqa: E402
from lingtai.llm.anthropic.adapter import _build_tools as build_anthropic_tools  # noqa: E402
from lingtai.llm.openai.adapter import (  # noqa: E402
    _build_responses_tools,
    _build_tools as build_chat_tools,
)


ARTIFACT_ROOT = ROOT / "artifacts" / "soul-action-input-worker"


class _Config:
    language = "en"
    soul_voice = "inner"
    soul_voice_prompt = ""
    consultation_past_count = 0


class _Service:
    provider = "gemini"
    model = "soul-candidate"

    def get_adapter(self):
        return object()


class _FakeAgent:
    def __init__(self, workdir: Path):
        self._working_dir = workdir
        self._config = _Config()
        self._soul_delay = 120.0
        self._soul_fire_lock = None
        self._idle = None
        self.logs: list[tuple[str, dict]] = []
        self.persisted: list[tuple[object, str]] = []

    def _log(self, event: str, **fields):
        self.logs.append((event, fields))

    def _persist_soul_entry(self, value, mode: str):
        self.persisted.append((value, mode))


class _UnhashableKeyMapping(Mapping):
    def __getitem__(self, key):
        return None

    def __iter__(self):
        return iter(([],))

    def __len__(self):
        return 1

    def keys(self):
        return [[]]


class _NonStringKeyMapping(Mapping):
    def __getitem__(self, key):
        return None

    def __iter__(self):
        return iter((1,))

    def __len__(self):
        return 1

    def keys(self):
        return [1]


class SoulActionInputCandidate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Force the opt-in gate off before either fake or real Agent setup so no
        # timer or voluntary flow can launch from the focused harness.
        os.environ.pop("LINGTAI_SOUL_FLOW_ENABLED", None)
        ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
        cls.workdir = ARTIFACT_ROOT / f"fresh-agent-{os.getpid()}"
        suffix = 0
        while cls.workdir.exists():
            suffix += 1
            cls.workdir = ARTIFACT_ROOT / f"fresh-agent-{os.getpid()}-{suffix}"
        cls.workdir.mkdir(parents=True)
        cls.settings = cls.workdir / "settings" / "soul.json"
        cls.settings.parent.mkdir(parents=True, exist_ok=True)
        cls.agent = _FakeAgent(cls.workdir)

        cls.actual_workdir = ARTIFACT_ROOT / f"actual-agent-{os.getpid()}"
        suffix = 0
        while cls.actual_workdir.exists():
            suffix += 1
            cls.actual_workdir = ARTIFACT_ROOT / f"actual-agent-{os.getpid()}-{suffix}"
        cls.actual_workdir.mkdir(parents=True)
        cls.actual_agent = Agent(
            service=_Service(),
            agent_name="soul-candidate-agent",
            working_dir=cls.actual_workdir,
            capabilities=["soul"],
        )
        # Preserve the bound intrinsic closure as data on the test class.  A
        # plain function class attribute would become a unittest-bound method
        # and bind the call arguments into the closure's ``fn`` default.
        cls.actual_handler = staticmethod(cls.actual_agent._intrinsics["soul"])
        cls.installed_manual = (
            cls.actual_workdir
            / ".library"
            / "intrinsic"
            / "capabilities"
            / "soul-manual"
            / "SKILL.md"
        )

    def setting_result(self, result: dict) -> dict:
        self.assertIn("current_setting", result)
        return result["current_setting"]

    def test_candidate_origins_raw_schema_and_agent_schema(self):
        self.assertEqual(Path(lingtai.__file__).resolve(), (SRC / "lingtai" / "__init__.py").resolve())
        self.assertEqual(Path(soul.__file__).resolve(), (SRC / "lingtai/tools/soul/__init__.py").resolve())
        self.assertIs(inspect.getmodule(soul.handle), soul)

        raw = soul.get_schema()
        self.assertEqual(set(raw), {"type", "properties", "required", "additionalProperties"})
        self.assertEqual(set(raw["properties"]), {"action", "input"})
        self.assertEqual(raw["required"], ["action", "input"])
        self.assertFalse(raw["additionalProperties"])
        self.assertEqual(
            raw["properties"]["action"]["enum"],
            ["inquiry", "flow", "config", "voice", "dismiss", "manual"],
        )
        branches = raw["properties"]["input"]["anyOf"]
        self.assertEqual(
            [branch["title"] for branch in branches],
            ["inquiry input", "flow input", "config input", "voice input", "dismiss input", "manual input"],
        )
        for branch in branches:
            self.assertFalse(branch["additionalProperties"])
            self.assertNotIn("reasoning", branch["properties"])
        self.assertEqual(branches[0]["required"], ["inquiry"])
        self.assertEqual(set(branches[0]["properties"]), {"inquiry"})
        self.assertEqual(set(branches[2]["properties"]), {"delay_seconds", "consultation_past_count"})
        self.assertEqual(set(branches[3]["properties"]), {"set", "prompt"})
        self.assertEqual(branches[5]["properties"], {})

        facing = next(s for s in self.actual_agent._build_tool_schemas() if s.name == "soul")
        self.assertIsInstance(facing, FunctionSchema)
        self.assertEqual(set(facing.parameters["properties"]), {"action", "input", "reasoning"})
        self.assertEqual(facing.parameters["required"], ["action", "input"])
        self.assertFalse(facing.parameters["additionalProperties"])
        self.assertNotIn("reasoning", raw["properties"])
        self.assertTrue(all("reasoning" not in b["properties"] for b in facing.parameters["properties"]["input"]["anyOf"]))
        self.assertEqual(inspect.getmodule(soul.get_schema), soul)

    def test_prompt_handler_origin_and_provider_envelopes(self):
        prompt = self.actual_agent._prompt_manager.read_section("tools")
        self.assertIn("soul(action=..., input={...}", prompt)
        self.assertIn("reasoning is never nested in input", prompt)
        soul_section = prompt.split("### soul\n", 1)[1].split("\n\n### notification", 1)[0]
        self.assertNotIn("omit action", soul_section.lower())
        self.assertIs(self.actual_agent._intrinsic_modules["soul"], soul)
        self.assertEqual(
            Path(soul.handle.__code__.co_filename).resolve(),
            (SRC / "lingtai/tools/soul/__init__.py").resolve(),
        )

        function_schema = next(
            s for s in self.actual_agent._build_tool_schemas() if s.name == "soul"
        )
        self.assertEqual(function_schema.name, "soul")
        self.assertEqual(function_schema.description, soul.get_description())
        chat = build_chat_tools([function_schema])[0]
        responses = _build_responses_tools([function_schema])[0]
        anthropic = build_anthropic_tools([function_schema])[0]
        self.assertEqual(set(chat), {"type", "function"})
        self.assertEqual(set(chat["function"]), {"name", "description", "parameters"})
        self.assertEqual(set(responses), {"type", "name", "description", "parameters"})
        self.assertEqual(set(anthropic), {"name", "description", "input_schema"})
        self.assertEqual(chat["function"]["parameters"], function_schema.parameters)
        self.assertEqual(responses["parameters"], function_schema.parameters)
        self.assertEqual(anthropic["input_schema"], function_schema.parameters)
        self.assertEqual(chat["function"]["description"], WIRE_TOOL_DESCRIPTION)
        self.assertEqual(responses["description"], WIRE_TOOL_DESCRIPTION)
        self.assertEqual(anthropic["description"], WIRE_TOOL_DESCRIPTION)
        self.assertEqual(chat["function"]["name"], "soul")
        self.assertEqual(responses["name"], "soul")
        self.assertEqual(anthropic["name"], "soul")

    def test_manual_reads_real_initialized_copy(self):
        result = self.actual_handler({"action": "manual", "input": {}})
        self.assertEqual(result["status"], "ok")
        self.assertTrue(self.installed_manual.is_file())
        self.assertEqual(Path(result["manual_path"]).resolve(), self.installed_manual.resolve())
        self.assertEqual(result["manual"], self.installed_manual.read_text(encoding="utf-8"))
        self.assertIn('soul(action="flow", input={})', result["manual"])
        self.assertIn('soul(action="manual", input={}, reasoning="load the installed soul manual")', result["manual"])
        self.assertNotIn("flat or omitted-action", result["manual"])
        self.assertEqual(self.setting_result(result)["source"], "missing")

    def test_strict_malformed_calls_have_zero_service_calls(self):
        calls = []
        with patch.object(soul, "soul_inquiry", side_effect=lambda *_a, **_k: calls.append("inquiry")), \
             patch.object(soul, "_handle_config", side_effect=lambda *_a, **_k: calls.append("config")), \
             patch.object(soul, "_handle_voice", side_effect=lambda *_a, **_k: calls.append("voice")), \
             patch("lingtai.kernel.notifications.dismiss_channel", side_effect=lambda *_a, **_k: calls.append("dismiss")):
            malformed = [
                None,
                {},
                {"action": "manual"},
                {"action": "manual", "input": []},
                {"action": "manual", "input": {"inquiry": "crossed"}},
                {"action": "inquiry", "input": {}},
                {"action": "inquiry", "input": {"delay_seconds": 30}},
                {"action": "flow", "input": {"reasoning": "nested"}},
                {"action": "voice", "input": {"delay_seconds": 30}},
                {"action": [], "input": {}},
                {"action": "manual", "input": _UnhashableKeyMapping()},
                {"action": "manual", "input": _NonStringKeyMapping()},
                _UnhashableKeyMapping(),
                {1: "manual", "input": {}},
                {"action": "manual", "input": {}, "surprise": "x"},
            ]
            for args in malformed:
                result = soul.handle(self.agent, args)
                self.assertIn("error", result)
                self.assertIn("current_setting", result)
        self.assertEqual(calls, [])

    def test_settings_evidence_nonleakage_and_prompt_invariance(self):
        prompt_before = self.actual_agent._prompt_manager.read_section("tools")

        missing = soul.handle(self.agent, {"action": "flow", "input": {}})
        self.assertEqual(self.setting_result(missing)["source"], "missing")
        missing_body = dict(missing)
        missing_body.pop("current_setting")

        self.settings.write_bytes(b'{"schema_version":1}')
        valid = soul.handle(self.agent, {"action": "flow", "input": {}})
        valid_setting = self.setting_result(valid)
        self.assertEqual(valid_setting["source"], "settings/soul.json")
        self.assertTrue(valid_setting["settings_hash"])
        self.assertEqual(dict(valid, current_setting=None)["status"], "disabled")

        self.settings.write_bytes(b'{ "schema_version" : 1 }\n')
        hot = soul.handle(self.agent, {"action": "flow", "input": {}})
        hot_setting = self.setting_result(hot)
        self.assertNotEqual(valid_setting["settings_revision"], hot_setting["settings_revision"])
        self.assertNotEqual(valid_setting["settings_hash"], hot_setting["settings_hash"])
        hot_body = dict(hot)
        hot_body.pop("current_setting")
        self.assertEqual(hot_body, missing_body)

        sentinels = [
            '{"schema_version": 2}',
            '{"schema_version":1,"secret":"SOUL_SECRET_SENTINEL"}',
            '{"schema_version":1,"extra":false}',
            '{"schema_version":"1"}',
            "not-json",
        ]
        for raw in sentinels:
            self.settings.write_text(raw, encoding="utf-8")
            invalid = soul.handle(self.agent, {"action": "flow", "input": {}})
            self.assertEqual(self.setting_result(invalid)["source"], "settings_error")
            self.assertNotIn("SOUL_SECRET_SENTINEL", json.dumps(invalid, sort_keys=True))
            self.assertNotIn(
                "SOUL_SECRET_SENTINEL",
                self.actual_agent._prompt_manager.read_section("tools"),
            )
            invalid_body = dict(invalid)
            invalid_body.pop("current_setting")
            self.assertEqual(invalid_body, missing_body)

        self.assertEqual(
            prompt_before,
            self.actual_agent._prompt_manager.read_section("tools"),
        )

    def test_deterministic_fake_paths_for_all_semantic_actions(self):
        # Inquiry: fake mirror result and fake persistence, no provider call.
        with patch.object(soul, "soul_inquiry", return_value={"voice": "fake inquiry"}):
            inquiry = soul.handle(self.agent, {"action": "inquiry", "input": {"inquiry": "What matters?"}})
        self.assertEqual(inquiry["status"], "ok")
        self.assertEqual(inquiry["voice"], "fake inquiry")
        self.assertEqual(self.agent.persisted[-1][1], "inquiry")

        # Flow: only the disabled, env-gated branch is exercised.
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LINGTAI_SOUL_FLOW_ENABLED", None)
            flow = soul.handle(self.agent, {"action": "flow", "input": {}})
        self.assertEqual(flow["status"], "disabled")
        self.assertFalse(flow["enabled"])

        # Config and voice: route through deterministic fake Agent-owned seams.
        with patch.object(soul, "_handle_config", return_value={"status": "ok", "new": {"delay_seconds": 300.0}}) as config:
            configured = soul.handle(self.agent, {"action": "config", "input": {"delay_seconds": 300}})
        config.assert_called_once()
        self.assertEqual(configured["status"], "ok")
        with patch.object(soul, "_handle_voice", return_value={"status": "ok", "current": "inner", "prompt": "fake"}) as voice:
            read_voice = soul.handle(self.agent, {"action": "voice", "input": {}})
        voice.assert_called_once()
        self.assertEqual(read_voice["current"], "inner")

        # Dismiss: shared helper is patched, so no notification is touched.
        with patch("lingtai.kernel.notifications.dismiss_channel", return_value={"status": "ok", "channel": "soul"}) as dismiss:
            dismissed = soul.handle(self.agent, {"action": "dismiss", "input": {}})
        dismiss.assert_called_once_with(self.agent, "soul", invoked_by="soul")
        self.assertEqual(dismissed["channel"], "soul")
        self.assertIn("current_setting", dismissed)

        # Manual uses the separately verified real initialized Agent path.
        manual = self.actual_handler({"action": "manual", "input": {}})
        self.assertEqual(manual["status"], "ok")
        self.assertIn("current_setting", manual)

    def test_service_errors_are_bounded_and_keep_fresh_evidence(self):
        sentinel = "SOUL_PRIVATE_SERVICE_SECRET"
        cases = [
            (
                "inquiry",
                patch.object(soul, "soul_inquiry", side_effect=RuntimeError(sentinel)),
                {"action": "inquiry", "input": {"inquiry": "safe?"}},
            ),
            (
                "flow",
                patch("lingtai.tools.soul.flow._soul_flow_enabled", side_effect=RuntimeError(sentinel)),
                {"action": "flow", "input": {}},
            ),
            (
                "config",
                patch.object(soul, "_handle_config", side_effect=RuntimeError(sentinel)),
                {"action": "config", "input": {"delay_seconds": 300}},
            ),
            (
                "voice",
                patch.object(soul, "_handle_voice", side_effect=RuntimeError(sentinel)),
                {"action": "voice", "input": {}},
            ),
            (
                "dismiss",
                patch(
                    "lingtai.kernel.notifications.dismiss_channel",
                    side_effect=RuntimeError(sentinel),
                ),
                {"action": "dismiss", "input": {}},
            ),
            (
                "manual",
                patch.object(
                    soul,
                    "load_installed_manual",
                    side_effect=RuntimeError(sentinel),
                ),
                {"action": "manual", "input": {}},
            ),
        ]
        for label, seam, args in cases:
            with self.subTest(action=label), seam:
                result = soul.handle(self.agent, args)
                self.assertEqual(result["error"], "soul action failed")
                self.assertIn("current_setting", result)
                self.assertNotIn(sentinel, repr(result))


if __name__ == "__main__":
    unittest.main(verbosity=2)
