"""Focused, fake-only regression coverage for the canonical email contract.

Run directly with ``$LINGTAI_RUNTIME_PYTHON -B``.  The test creates retained
candidate-owned roots under ``artifacts/email-action-input-parent/runtime-evidence/``; it never
uses a real mailbox, mail service, network, or pytest fixtures.
"""
from __future__ import annotations

import json
import os
import sys
import unittest
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
# Evict preloaded package modules so this candidate's origins are authoritative.
for _name in list(sys.modules):
    if _name == "lingtai" or _name.startswith("lingtai."):
        del sys.modules[_name]
sys.path.insert(0, str(SRC))

import lingtai  # noqa: E402
from lingtai.agent import Agent  # noqa: E402
from lingtai.kernel.llm.base import WIRE_TOOL_DESCRIPTION  # noqa: E402
from lingtai.llm.anthropic.adapter import _build_tools as build_anthropic_tools  # noqa: E402
from lingtai.llm.openai.adapter import (  # noqa: E402
    _build_responses_tools,
    _build_tools as build_chat_tools,
)
from lingtai.tools import email  # noqa: E402

ARTIFACT_ROOT = ROOT / "artifacts" / "email-action-input-parent" / "runtime-evidence"


class _OddKeys(Mapping):
    def __init__(self, key):
        self._key = key

    def __getitem__(self, key):
        return None

    def __iter__(self):
        return iter((self._key,))

    def __len__(self):
        return 1

    def keys(self):
        return [self._key]


class _HostileReasoning(Mapping):
    """Mapping whose metadata lookup raises after action/input were readable."""

    def __init__(self):
        self._data = {"action": "check", "input": {}, "reasoning": "hidden"}

    def __getitem__(self, key):
        if key == "reasoning":
            raise RuntimeError("hostile metadata lookup")
        return self._data[key]

    def __iter__(self):
        return iter(self._data)

    def __len__(self):
        return len(self._data)

    def keys(self):
        return self._data.keys()


class _RecordingManager:
    def __init__(self):
        self.calls: list[dict] = []
        self.raise_error = False

    def handle(self, args):
        self.calls.append(dict(args))
        if self.raise_error:
            raise RuntimeError("candidate seam must not leak")
        return {"status": "ok", "action": args["action"], "received": dict(args)}


class _FakeAgent:
    def __init__(self, root: Path):
        self._working_dir = root
        self._email_manager = _RecordingManager()


class _Service:
    provider = "gemini"
    model = "email-action-input-candidate"

    def get_adapter(self):
        return MagicMock()


class _InlineThread:
    """Synchronous fake for manager delivery threads; never starts a child."""

    def __init__(self, *, target, args=(), kwargs=None, **_ignored):
        self._target = target
        self._args = args
        self._kwargs = kwargs or {}

    def start(self):
        self._target(*self._args, **self._kwargs)


class _RuntimeAgent:
    def __init__(self, root: Path):
        self._working_dir = root
        self._config = SimpleNamespace(language="en", time_awareness=False)
        self._agent_id = "candidate-runtime-agent"
        self._mail_service = MagicMock()
        self._mail_service.address = "candidate-runtime-agent"
        self.logs = []
        self._email_manager = email.EmailManager(self)

    def _build_manifest(self):
        return {"agent_name": "candidate-runtime-agent", "agent_id": self._agent_id}

    def _log(self, event, **fields):
        self.logs.append((event, fields))

    def _wake_nap(self, reason):
        self.logs.append(("wake", {"reason": reason}))

    def _enqueue_system_notification(self, **fields):
        self.logs.append(("notification", fields))


class EmailActionInputCandidate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
        cls.fake_root = cls._fresh_root("fake-agent")
        cls.fake = _FakeAgent(cls.fake_root)
        cls.settings = cls.fake_root / "settings" / "email.json"
        cls.settings.parent.mkdir(parents=True, exist_ok=True)

        cls.actual_root = cls._fresh_root("actual-agent")
        cls.actual_agent = Agent(
            service=_Service(),
            agent_name="email-action-input-candidate",
            working_dir=cls.actual_root,
        )

    @classmethod
    def tearDownClass(cls):
        cls.actual_agent.stop(timeout=5.0)

    def setUp(self):
        self.fake_root = self._fresh_root("fake-test")
        self.fake = _FakeAgent(self.fake_root)
        self.settings = self.fake_root / "settings" / "email.json"
        self.settings.parent.mkdir(parents=True, exist_ok=True)

    @classmethod
    def _fresh_root(cls, stem: str) -> Path:
        base = ARTIFACT_ROOT / f"{stem}-{os.getpid()}"
        candidate = base
        index = 0
        while candidate.exists():
            index += 1
            candidate = ARTIFACT_ROOT / f"{stem}-{os.getpid()}-{index}"
        candidate.mkdir(parents=True)
        return candidate

    @staticmethod
    def _without_setting(result: Mapping) -> dict:
        value = dict(result)
        value.pop("current_setting", None)
        return value

    def _assert_setting(self, result: Mapping, source: str | None = None):
        self.assertIn("current_setting", result)
        current = result["current_setting"]
        self.assertFalse(current["configurable"])
        self.assertEqual(current["placeholder"], "no-op")
        self.assertIn("settings_revision", current)
        self.assertIn("settings_hash", current)
        self.assertIn("settings/email.json", current["change_hint"])
        if source is not None:
            self.assertEqual(current["source"], source)
        return current

    def test_candidate_origins_actual_agent_prompt_raw_and_provider_schemas(self):
        self.assertEqual(Path(lingtai.__file__).resolve(), (SRC / "lingtai" / "__init__.py").resolve())
        self.assertEqual(Path(email.__file__).resolve(), (SRC / "lingtai/tools/email/__init__.py").resolve())
        self.assertIs(self.actual_agent._intrinsic_modules["email"], email)

        raw = email.get_schema()
        self.assertEqual(set(raw), {"type", "properties", "required", "additionalProperties"})
        self.assertEqual(set(raw["properties"]), {"action", "input"})
        self.assertEqual(raw["required"], ["action", "input"])
        self.assertFalse(raw["additionalProperties"])
        self.assertNotIn("reasoning", raw["properties"])
        self.assertNotIn("summary", json.dumps(raw))
        self.assertEqual(
            raw["properties"]["action"]["enum"],
            ["send", "check", "read", "dismiss", "reply", "reply_all", "search", "archive", "delete", "contacts", "add_contact", "remove_contact", "edit_contact", "manual"],
        )
        branches = raw["properties"]["input"]["anyOf"]
        self.assertEqual([item["title"] for item in branches], [
            "send input", "check input", "read input", "dismiss input", "reply input",
            "reply_all input", "search input", "archive input", "delete input",
            "contacts input", "add_contact input", "remove_contact input",
            "edit_contact input", "manual input",
        ])
        for branch in branches:
            self.assertFalse(branch["additionalProperties"])
        self.assertEqual(branches[0]["required"], ["address", "message"])
        self.assertEqual(branches[1]["required"], [])
        self.assertEqual(branches[2]["required"], ["email_id"])
        self.assertEqual(branches[4]["required"], ["email_id", "message"])
        self.assertEqual(branches[6]["required"], ["query"])
        self.assertEqual(branches[9]["properties"], {})
        self.assertEqual(branches[-1]["properties"], {})
        self.assertNotIn("summary", {key for branch in branches for key in branch["properties"]})

        schemas = self.actual_agent._build_tool_schemas()
        email_schema = next(schema for schema in schemas if schema.name == "email")
        self.assertEqual(set(email_schema.parameters["properties"]), {"action", "input", "reasoning"})
        self.assertEqual(email_schema.parameters["required"], ["action", "input"])
        self.assertEqual(email_schema.parameters["properties"]["reasoning"]["type"], "string")
        prompt = self.actual_agent._build_system_prompt()
        self.assertIn("### email", prompt)
        self.assertIn("email(action='manual', input={})", prompt)
        self.assertNotIn("email(action='check')", prompt)

        # Serialize the actual Agent-composed FunctionSchema, not a second raw copy.
        chat = build_chat_tools([email_schema])[0]
        responses = _build_responses_tools([email_schema])[0]
        anthropic = build_anthropic_tools([email_schema], cache_tools=False)[0]
        self.assertEqual(chat["function"]["description"], WIRE_TOOL_DESCRIPTION)
        self.assertEqual(responses["description"], WIRE_TOOL_DESCRIPTION)
        self.assertEqual(anthropic["description"], WIRE_TOOL_DESCRIPTION)
        agent_params = email_schema.parameters
        self.assertEqual(chat["function"]["parameters"], agent_params)
        self.assertEqual(anthropic["input_schema"], agent_params)
        # Responses preserves the composed envelope while canonicalizing nested
        # oneOf address/ID unions to its provider-compatible anyOf dialect.
        response_params = responses["parameters"]
        self.assertEqual(response_params["required"], ["action", "input"])
        self.assertFalse(response_params["additionalProperties"])
        self.assertEqual(set(response_params["properties"]), {"action", "input", "reasoning"})
        self.assertEqual(response_params["properties"]["reasoning"]["type"], "string")
        self.assertEqual(
            [branch["title"] for branch in response_params["properties"]["input"]["anyOf"]],
            [branch["title"] for branch in agent_params["properties"]["input"]["anyOf"]],
        )

    def test_all_actions_route_only_through_candidate_fake_manager(self):
        cases = {
            "send": {"address": "self", "message": "m"},
            "check": {},
            "read": {"email_id": ["id"]},
            "dismiss": {"email_id": ["id"]},
            "reply": {"email_id": ["id"], "message": "m"},
            "reply_all": {"email_id": ["id"], "message": "m"},
            "search": {"query": "m"},
            "archive": {"email_id": ["id"]},
            "delete": {"email_id": ["id"]},
            "contacts": {},
            "add_contact": {"address": "alice", "name": "Alice"},
            "remove_contact": {"address": "alice"},
            "edit_contact": {"address": "alice", "note": "updated"},
        }
        before = len(self.fake._email_manager.calls)
        for action, payload in cases.items():
            result = email.handle(self.fake, {"action": action, "input": payload})
            self.assertEqual(result["action"], action)
            self._assert_setting(result, "missing")
        calls = self.fake._email_manager.calls[before:]
        self.assertEqual([call["action"] for call in calls], list(cases))
        self.assertNotIn("input", calls[0])
        self.assertEqual(calls[0]["address"], "self")
        self.assertNotIn("subject", calls[0])

    def test_manual_reads_installed_candidate_manual_only(self):
        manager = self.fake._email_manager
        before = len(manager.calls)
        result = self.actual_agent._intrinsics["email"]({"action": "manual", "input": {}})
        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["manual_path"].endswith(".library/intrinsic/capabilities/email/SKILL.md"))
        manual_path = Path(result["manual_path"])
        self.assertEqual(manual_path, self.actual_root / ".library/intrinsic/capabilities/email/SKILL.md")
        self.assertEqual(result["manual"], manual_path.read_text(encoding="utf-8"))
        self.assertIn("email(action=\"send\", input=", result["manual"])
        self.assertEqual(len(manager.calls), before)

        invalid = email.handle(self.fake, {"action": "manual", "input": {"query": "flat"}})
        self.assertIn("error", invalid)
        self.assertEqual(len(manager.calls), before)

    def test_root_input_and_value_validation_precedes_fake_mailbox_seam(self):
        manager = self.fake._email_manager
        manager.calls.clear()
        invalid = [
            None,
            {"action": "check"},
            {"input": {}},
            {"action": [], "input": {}},
            {"action": "check", "input": None},
            {"action": "check", "input": {"flat": 1}},
            {"action": "send", "input": {"address": "x", "subject": "s", "message": "m"}, "n": 1},
            {"action": "send", "input": {"address": ["x", 4], "subject": "s", "message": "m"}},
            {"action": "check", "input": {"n": True}},
            {"action": "check", "input": {"filter": {"unknown": "secret"}}},
            {"action": "check", "input": _OddKeys([])},
            {"action": "check", "input": {}, "reasoning": []},
            _HostileReasoning(),
            {"action": "check", "input": {"filter": _OddKeys([])}},
            {"action": "contacts", "input": {"summary": True}},
        ]
        for args in invalid:
            result = email.handle(self.fake, args)
            self.assertIn("current_setting", result)
            self.assertIn("error", result)
        self.assertEqual(manager.calls, [])

    def test_established_defaults_results_limits_filters_attachments_and_reply(self):
        runtime_root = self._fresh_root("runtime-mailbox")
        runtime = _RuntimeAgent(runtime_root)
        oversized = email.handle(runtime, {
            "action": "send",
            "input": {"address": "peer", "subject": "too large", "message": "x" * 50001},
        })
        self.assertIn("error", oversized)
        self.assertEqual(oversized["limit_chars"], 50000)
        self.assertEqual(oversized["actual_chars"], 50001)
        self._assert_setting(oversized, "missing")

        attachment = runtime_root / "candidate-attachment.txt"
        attachment.write_text("fake attachment", encoding="utf-8")
        with patch("lingtai.tools.email.manager.threading.Thread", _InlineThread):
            sent = email.handle(runtime, {
                "action": "send",
                "input": {
                    "address": "peer",
                    "cc": ["copy"],
                    "bcc": ["hidden"],
                    "attachments": [str(attachment)],
                    "subject": "subject",
                    "message": "body",
                },
            })
        self.assertEqual(sent["status"], "sent")
        self.assertEqual(sent["to"], ["peer"])
        self.assertEqual(sent["cc"], ["copy"])
        self.assertEqual(sent["bcc"], ["hidden"])
        self.assertEqual(sent["delay"], 0)
        sent_records = list((runtime_root / "mailbox" / "sent").glob("*/message.json"))
        self.assertEqual(len(sent_records), 1)
        sent_payload = json.loads(sent_records[0].read_text(encoding="utf-8"))
        self.assertEqual(sent_payload["attachments"], [str(attachment)])
        self.assertEqual(sent_payload["bcc"], ["hidden"])

        message_id = "candidate-message"
        inbox_dir = runtime_root / "mailbox" / "inbox" / message_id
        inbox_dir.mkdir(parents=True)
        (inbox_dir / "message.json").write_text(json.dumps({
            "_mailbox_id": message_id,
            "from": "alice",
            "to": ["candidate-runtime-agent"],
            "subject": "topic",
            "message": "filter body",
            "received_at": "2026-01-01T00:00:00Z",
        }), encoding="utf-8")
        checked = email.handle(runtime, {
            "action": "check",
            "input": {"n": 10, "filter": {"from": "alice", "unread_only": True, "truncate": 2}},
        })
        self.assertEqual(checked["status"], "ok")
        self.assertEqual(checked["total"], 1)
        self.assertEqual(checked["emails"][0]["id"], message_id)
        self.assertTrue(checked["emails"][0]["preview"].startswith("fi"))

        with patch.object(runtime._email_manager, "_send", return_value={"status": "sent", "to": ["alice"]}) as send:
            replied = email.handle(runtime, {
                "action": "reply",
                "input": {"email_id": [message_id], "message": "ack"},
            })
        self.assertEqual(replied["status"], "sent")
        reply_args = send.call_args.args[0]
        self.assertEqual(reply_args["address"], "alice")
        self.assertEqual(reply_args["subject"], "Re: topic")
        self.assertEqual(reply_args["message"], "ack")

    def test_settings_are_fresh_copy_safe_behavior_neutral_and_secret_free(self):
        first = email.handle(self.fake, {"action": "check", "input": {}})
        self._assert_setting(first, "missing")
        first["current_setting"]["source"] = "mutated"

        self.settings.write_text(json.dumps({"schema_version": 1}), encoding="utf-8")
        valid = email.handle(self.fake, {"action": "check", "input": {}})
        setting = self._assert_setting(valid, "settings/email.json")
        self.assertNotEqual(setting["source"], "mutated")
        revision = setting["settings_revision"]
        baseline = self._without_setting(valid)

        self.settings.write_text(json.dumps({"schema_version": 1}), encoding="utf-8")
        unchanged = email.handle(self.fake, {"action": "check", "input": {}})
        self.assertEqual(self._without_setting(unchanged), baseline)
        self.assertEqual(unchanged["current_setting"]["settings_revision"], revision)

        self.settings.write_text(json.dumps({"schema_version": 1, "secret": "DO_NOT_LEAK"}), encoding="utf-8")
        invalid = email.handle(self.fake, {"action": "check", "input": {}})
        self._assert_setting(invalid, "settings_error")
        rendered = json.dumps(invalid, ensure_ascii=False)
        self.assertNotIn("DO_NOT_LEAK", rendered)
        self.assertNotIn("secret", rendered)
        self.assertEqual(self._without_setting(invalid), baseline)

    def test_every_error_and_manager_failure_still_carries_fresh_settings(self):
        self.settings.write_text(json.dumps({"schema_version": 1}), encoding="utf-8")
        self.fake._email_manager.raise_error = True
        result = email.handle(self.fake, {"action": "check", "input": {}})
        self.assertEqual(result["error"], "email action failed")
        self._assert_setting(result, "settings/email.json")
        self.fake._email_manager.raise_error = False
        malformed = email.handle(self.fake, {"action": "bogus", "input": {}})
        self._assert_setting(malformed, "settings/email.json")


if __name__ == "__main__":
    unittest.main()
