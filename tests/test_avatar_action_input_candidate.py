"""Focused avatar canonical-contract checks with no live avatar/rules effects.

Run directly with ``python tests/test_avatar_action_input_candidate.py``.  The
candidate source is inserted at sys.path[0] before any LingTai import.  Each run
uses a new retained candidate-owned artifact directory and never cleans it up.
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
import lingtai.tools.avatar as avatar_module  # noqa: E402
from lingtai.agent import Agent  # noqa: E402
from lingtai.kernel.llm.base import FunctionSchema, WIRE_TOOL_DESCRIPTION  # noqa: E402
from lingtai.llm.anthropic.adapter import _build_tools as build_anthropic_tools  # noqa: E402
from lingtai.llm.openai.adapter import (  # noqa: E402
    _build_responses_tools,
    _build_tools as build_chat_tools,
)
from lingtai.tools.avatar import AvatarManager  # noqa: E402
from lingtai.tools.avatar._launcher import AvatarLaunchReceipt  # noqa: E402


ARTIFACT_ROOT = ROOT / "artifacts" / "avatar-action-input-worker"


class _Service:
    provider = "gemini"
    model = "candidate-test"

    def get_adapter(self):
        return object()


class _FakeLauncher:
    def __init__(self):
        self.launch_calls = []
        self.release_calls = []

    def launch(self, request):
        self.launch_calls.append(request)
        return AvatarLaunchReceipt(42000 + len(self.launch_calls), object())

    def poll(self, handle):
        return None

    def terminate(self, handle):
        raise AssertionError("test must not terminate a fake avatar")

    def force_terminate(self, handle):
        raise AssertionError("test must not force-terminate a fake avatar")

    def release(self, handle):
        self.release_calls.append(handle)


class _UnhashableKeys(Mapping):
    def __getitem__(self, key):
        return None

    def __iter__(self):
        return iter(([],))

    def __len__(self):
        return 1

    def keys(self):
        return [[]]


class _RootWithUnhashableInput(Mapping):
    def __init__(self):
        self.values = {"action": "manual", "input": _UnhashableKeys()}

    def __getitem__(self, key):
        return self.values[key]

    def __iter__(self):
        return iter(self.values)

    def __len__(self):
        return len(self.values)


class AvatarActionInputCandidate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # PID names avoid collisions while keeping all evidence under the
        # explicitly retained candidate artifact directory.
        cls.workdir = ARTIFACT_ROOT / f"fresh-agent-{os.getpid()}"
        cls.workdir.mkdir(parents=True, exist_ok=False)
        cls.settings_dir = cls.workdir / "settings"
        cls.settings_dir.mkdir(parents=True, exist_ok=True)
        cls.agent = Agent(
            service=_Service(),
            agent_name="avatar-contract-agent",
            working_dir=cls.workdir,
            capabilities=["avatar"],
            admin={"karma": True},
        )
        cls.manager = cls.agent.get_capability("avatar")
        cls.fake_launcher = _FakeLauncher()
        cls.manager._launcher = cls.fake_launcher
        # Spawn's parent-init precondition is deliberately satisfied in this
        # fresh candidate-owned agent; no production spawn is ever attempted.
        (cls.workdir / "init.json").write_text(
            json.dumps({"manifest": {"agent_name": "avatar-contract-agent"}, "lingtai": ""}),
            encoding="utf-8",
        )

    def test_import_identity_and_raw_schema(self):
        self.assertEqual(Path(lingtai.__file__).resolve(), (SRC / "lingtai" / "__init__.py").resolve())
        self.assertEqual(Path(avatar_module.__file__).resolve(), (SRC / "lingtai" / "tools" / "avatar" / "__init__.py").resolve())
        raw = avatar_module.get_schema()
        self.assertEqual(set(raw), {"type", "properties", "required", "additionalProperties"})
        self.assertEqual(set(raw["properties"]), {"action", "input"})
        self.assertEqual(raw["required"], ["action", "input"])
        self.assertFalse(raw["additionalProperties"])
        branches = raw["properties"]["input"]["anyOf"]
        self.assertEqual([b["title"] for b in branches], ["spawn input", "rules input", "manual input"])
        self.assertEqual(branches[0]["required"], ["name"])
        self.assertEqual(set(branches[0]["properties"]), {"name", "type", "comment", "dry_run", "confirm"})
        self.assertEqual(branches[1]["required"], ["rules_content"])
        self.assertEqual(set(branches[1]["properties"]), {"rules_content"})
        self.assertEqual(branches[2]["properties"], {})

    def test_agent_schema_prompt_handler_and_provider_envelopes(self):
        facing = next(s for s in self.agent._build_tool_schemas() if s.name == "avatar")
        self.assertEqual(facing.parameters["required"], ["action", "input"])
        self.assertEqual(set(facing.parameters["properties"]), {"action", "input", "reasoning"})
        self.assertFalse(facing.parameters["additionalProperties"])
        self.assertNotIn("reasoning", avatar_module.get_schema()["properties"])
        self.assertTrue(
            all(
                "reasoning" not in branch.get("properties", {})
                for branch in facing.parameters["properties"]["input"]["anyOf"]
            )
        )
        prompt_tools = self.agent._prompt_manager.read_section("tools")
        avatar_section = prompt_tools.split("### avatar\n", 1)[1].split("\n\n### ", 1)[0]
        self.assertIn("avatar(action='spawn', input={'name': 'researcher'", avatar_section)
        self.assertIn("reasoning", avatar_section)
        self.assertIn("action and input are always explicit", avatar_section)
        self.assertNotIn("omit `action`", avatar_section)
        handler_filename = Path(self.agent._tool_handlers["avatar"].__code__.co_filename).resolve()
        self.assertEqual(handler_filename, (SRC / "lingtai" / "tools" / "avatar" / "__init__.py").resolve())
        self.assertIs(inspect.getmodule(self.agent._tool_handlers["avatar"]), avatar_module)

        function_schema = next(s for s in self.agent._build_tool_schemas() if s.name == "avatar")
        self.assertEqual(function_schema.parameters, facing.parameters)
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
        self.assertEqual(chat["function"]["name"], responses["name"])
        self.assertEqual(chat["function"]["name"], anthropic["name"])

    def test_manual_is_installed_and_settings_are_evidence_only(self):
        prompt_before = self.agent._prompt_manager.read_section("tools")
        manual = self.manager.handle({"action": "manual", "input": {}, "reasoning": "load guidance"})
        self.assertEqual(manual["status"], "ok")
        installed = self.workdir / ".library" / "intrinsic" / "capabilities" / "avatar" / "SKILL.md"
        self.assertEqual(Path(manual["manual_path"]).resolve(), installed.resolve())
        self.assertEqual(manual["manual"], installed.read_text(encoding="utf-8"))
        self.assertIn(
            'avatar(action="spawn", input={"name": "researcher"}, reasoning="...mission briefing...")',
            manual["manual"],
        )
        self.assertIn(
            'avatar(action="rules", input={"rules_content": "Always report findings."}, reasoning="distribute the reviewed rule")',
            manual["manual"],
        )
        self.assertIn(
            'avatar(action="manual", input={}, reasoning="load the installed avatar manual")',
            manual["manual"],
        )
        self.assertIn("Do not omit `action`, flatten nested", manual["manual"])
        self.assertIn("uses no flat or\nomitted-action compatibility form", manual["manual"])
        self.assertEqual(manual["current_setting"]["source"], "missing")

        settings = self.settings_dir / "avatar.json"
        settings.write_bytes(b'{"schema_version":1}')
        valid = self.manager.handle({"action": "manual", "input": {}, "reasoning": "load guidance"})
        self.assertEqual(valid["current_setting"]["source"], "settings/avatar.json")
        settings.write_bytes(b'{ "schema_version" : 1 }\n')
        hot = self.manager.handle({"action": "manual", "input": {}, "reasoning": "load guidance"})
        self.assertEqual(hot["current_setting"]["source"], "settings/avatar.json")
        self.assertNotEqual(
            valid["current_setting"]["settings_revision"],
            hot["current_setting"]["settings_revision"],
        )
        self.assertNotEqual(
            valid["current_setting"]["settings_hash"],
            hot["current_setting"]["settings_hash"],
        )
        self.assertEqual(valid["manual"], hot["manual"])

        sentinel = "AVATAR_SECRET_SENTINEL"
        settings.write_text(
            json.dumps({"schema_version": 1, "secret": sentinel}), encoding="utf-8"
        )
        invalid = self.manager.handle({"action": "manual", "input": {}, "reasoning": "load guidance"})
        self.assertEqual(invalid["current_setting"]["source"], "settings_error")
        self.assertTrue(invalid["current_setting"]["settings_error"])
        self.assertNotIn(sentinel, json.dumps(invalid, sort_keys=True))
        self.assertNotIn(sentinel, self.agent._prompt_manager.read_section("tools"))
        self.assertEqual(prompt_before, self.agent._prompt_manager.read_section("tools"))
        self.assertEqual(valid["manual"], invalid["manual"])

    def test_malformed_calls_are_strict_and_do_not_reach_services(self):
        before_launch = len(self.fake_launcher.launch_calls)
        malformed = [
            None,
            {},
            {"action": "spawn", "input": {"name": "x", "rules_content": "wrong"}},
            {"action": "rules", "input": {"rules_content": "x", "dry_run": True}},
            {"action": "manual", "input": {"name": "wrong"}},
            {"action": [], "input": {}},
            {"action": "manual"},
            {"action": "manual", "input": []},
            {"action": "manual", "input": _UnhashableKeys()},
            {"action": "spawn", "input": {"name": "x"}, "_reasoning": []},
            _RootWithUnhashableInput(),
            {1: "manual", "input": {}},
        ]
        for args in malformed:
            result = self.manager.handle(args)
            self.assertIn("current_setting", result)
            self.assertIn("error", result)
        self.assertEqual(len(self.fake_launcher.launch_calls), before_launch)

    def test_spawn_gate_dry_run_success_boot_error_and_no_live_process(self):
        gate = self.manager.handle({
            "action": "spawn",
            "input": {"name": "gated"},
            "_reasoning": "short",
        })
        self.assertEqual(gate["status"], "confirmation_needed")
        self.assertEqual(len(self.fake_launcher.launch_calls), 0)

        dry = self.manager.handle({
            "action": "spawn",
            "input": {"name": "preview", "dry_run": True},
            "_reasoning": "short preview",
        })
        self.assertEqual(dry["status"], "dry_run")
        self.assertEqual(len(self.fake_launcher.launch_calls), 0)

        self.manager._launch = lambda working_dir: (
            AvatarLaunchReceipt(43001, object()), working_dir / "spawn.stderr"
        )
        self.manager._wait_for_boot = lambda working_dir, proc, stderr: ("ok", None)
        success_name = f"fake-success-{os.getpid()}"
        success = self.manager.handle({
            "action": "spawn",
            "input": {"name": success_name, "type": "shallow", "comment": "", "confirm": True},
            "_reasoning": "A reviewed mission that is intentionally long enough.",
        })
        self.assertEqual(success["status"], "ok")
        self.assertEqual(success["type"], "shallow")
        self.assertEqual(len(self.fake_launcher.release_calls), 1)

        self.manager._wait_for_boot = lambda working_dir, proc, stderr: ("failed", "fake boot failure")
        failed_name = f"fake-failed-{os.getpid()}"
        failed = self.manager.handle({
            "action": "spawn",
            "input": {"name": failed_name, "confirm": True},
            "_reasoning": "A reviewed mission that is intentionally long enough.",
        })
        self.assertIn("error", failed)
        self.assertIn("current_setting", failed)
        self.assertEqual(len(self.fake_launcher.release_calls), 2)

    def test_rules_success_and_admin_error_are_owned_by_rules(self):
        self.manager._distribute_rules_to_descendants = lambda content, root: ["fake-child"]
        success = self.manager.handle({
            "action": "rules",
            "input": {"rules_content": "Always report findings."},
            "_reasoning": "distribute reviewed rule",
        })
        self.assertEqual(success["status"], "ok")
        self.assertEqual(success["distributed_to"], [self.workdir.name, "fake-child"])

        old_admin = self.agent._admin
        self.agent._admin = {}
        denied = self.manager.handle({
            "action": "rules",
            "input": {"rules_content": "No live distribution."},
            "_reasoning": "test admin gate",
        })
        self.agent._admin = old_admin
        self.assertIn("error", denied)
        self.assertIn("current_setting", denied)

    def test_unexpected_service_errors_are_bounded_and_keep_settings(self):
        with patch.object(self.manager, "_spawn", side_effect=RuntimeError("PRIVATE-SPAWN-DETAIL")):
            failed_spawn = self.manager.handle({
                "action": "spawn",
                "input": {"name": "bounded", "confirm": True},
                "reasoning": "A reviewed mission that is intentionally long enough.",
            })
        self.assertEqual(failed_spawn["error"], "avatar service failed")
        self.assertIn("current_setting", failed_spawn)
        self.assertNotIn("PRIVATE-SPAWN-DETAIL", repr(failed_spawn))

        with patch.object(self.manager, "_rules", side_effect=RuntimeError("PRIVATE-RULES-DETAIL")):
            failed_rules = self.manager.handle({
                "action": "rules",
                "input": {"rules_content": "Bound unexpected errors."},
                "reasoning": "exercise the bounded rules error path",
            })
        self.assertEqual(failed_rules["error"], "avatar service failed")
        self.assertIn("current_setting", failed_rules)
        self.assertNotIn("PRIVATE-RULES-DETAIL", repr(failed_rules))


if __name__ == "__main__":
    unittest.main(verbosity=2)
