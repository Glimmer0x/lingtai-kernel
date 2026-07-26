"""Safe focused checks for the canonical notification action/input contract.

Run directly with the project runtime interpreter:

    python tests/test_notification_action_input_candidate.py

The candidate source is inserted at ``sys.path[0]`` before LingTai imports. One
real candidate Agent proves registration, prompt, provider, and initialized
manual provenance. Every dismissal test uses a candidate-owned in-memory Store;
this harness never reads, writes, or clears the running agent's live notification
surface.
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
import lingtai.tools.notification as notification  # noqa: E402
from lingtai.agent import Agent  # noqa: E402
from lingtai.kernel.llm.base import FunctionSchema, WIRE_TOOL_DESCRIPTION  # noqa: E402
from lingtai.kernel.notification_store import (  # noqa: E402
    CompareUpdateResult,
    UNCONDITIONAL,
)
from lingtai.llm.anthropic.adapter import _build_tools as build_anthropic_tools  # noqa: E402
from lingtai.llm.openai.adapter import (  # noqa: E402
    _build_responses_tools,
    _build_tools as build_chat_tools,
)

ARTIFACT_ROOT = ROOT / "artifacts" / "notification-action-input-test"


class _Service:
    provider = "gemini"
    model = "notification-candidate"

    def get_adapter(self):
        return object()


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


class _MemoryStore:
    """Candidate-owned in-memory NotificationStorePort test double."""

    def __init__(self) -> None:
        self.payloads: dict[str, dict] = {}
        self.versions: dict[str, tuple] = {}
        self.ack_refs: set[str] = set()
        self.calls: list[tuple] = []
        self.compare_error: Exception | None = None

    def reset_calls(self) -> None:
        self.calls.clear()

    def snapshot(self, allow_channel):
        self.calls.append(("snapshot",))
        return {key: value for key, value in self.payloads.items() if allow_channel(key)}

    def fingerprint(self, allow_channel):
        self.calls.append(("fingerprint",))
        return tuple(
            self.versions[key]
            for key in sorted(self.payloads)
            if allow_channel(key) and key in self.versions
        )

    def publish(self, channel, payload):
        self.calls.append(("publish", channel))
        self.payloads[channel] = payload

    def clear(self, channel):
        self.calls.append(("clear", channel))
        existed = channel in self.payloads
        self.payloads.pop(channel, None)
        return existed

    def compare_update_channel(self, channel, expected_version, mutator):
        self.calls.append(("compare_update_channel", channel, expected_version))
        if self.compare_error is not None:
            raise self.compare_error
        current_version = self.versions.get(channel)
        if expected_version is not UNCONDITIONAL and expected_version != current_version:
            safe = list(current_version) if current_version is not None else None
            return CompareUpdateResult(False, True, False, False, None, safe, safe)
        current = self.payloads.get(channel, {})
        new_payload, changed, value = mutator(current)
        if changed:
            if new_payload is None:
                self.payloads.pop(channel, None)
            else:
                self.payloads[channel] = new_payload
        return CompareUpdateResult(
            True,
            False,
            bool(changed),
            bool(changed and new_payload is None),
            value,
            None,
            None,
        )

    def load_ack_refs(self):
        self.calls.append(("load_ack_refs",))
        return set(self.ack_refs)

    def update_ack_refs(self, mutator):
        self.calls.append(("update_ack_refs",))
        updated, changed, value = mutator(set(self.ack_refs))
        if changed:
            self.ack_refs = set(updated)
        return type("AckResult", (), {"changed": changed, "value": value})()


class _FakeAgent:
    def __init__(self, workdir: Path) -> None:
        self._working_dir = workdir
        self._notification_store = _MemoryStore()
        self._notification_fp: tuple = ()
        self._chat = None
        self.logs: list[tuple[str, dict]] = []

    def _log(self, event: str, **fields) -> None:
        self.logs.append((event, fields))


class NotificationActionInputCandidate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
        cls.fake_workdir = cls._fresh_dir("fake-agent")
        cls.fake = _FakeAgent(cls.fake_workdir)
        cls.settings = cls.fake_workdir / "settings" / "notification.json"
        cls.settings.parent.mkdir(parents=True, exist_ok=True)

        cls.actual_workdir = cls._fresh_dir("actual-agent")
        cls.actual_agent = Agent(
            service=_Service(),
            agent_name="notification-candidate-agent",
            working_dir=cls.actual_workdir,
            capabilities=["notification"],
        )
        # Preserve the closure as data; a plain function class attribute would be
        # rebound by unittest's descriptor protocol.
        cls.actual_handler = staticmethod(cls.actual_agent._intrinsics["notification"])
        cls.installed_manual = (
            cls.actual_workdir
            / ".library"
            / "intrinsic"
            / "capabilities"
            / "notification-manual"
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
        self.assertIn("settings/notification.json", value["change_hint"])
        return value

    @staticmethod
    def _without_setting(result: dict) -> dict:
        value = dict(result)
        value.pop("current_setting")
        return value

    def _deliver(self, channel: str, version: tuple, payload: dict) -> None:
        store = self.fake._notification_store
        store.payloads[channel] = payload
        store.versions[channel] = version
        self.fake._notification_fp = (version,)
        store.reset_calls()

    def test_candidate_origins_intrinsic_closure_and_schemas(self):
        self.assertEqual(
            Path(lingtai.__file__).resolve(),
            (SRC / "lingtai" / "__init__.py").resolve(),
        )
        self.assertEqual(
            Path(notification.__file__).resolve(),
            (SRC / "lingtai/tools/notification/__init__.py").resolve(),
        )
        self.assertIs(inspect.getmodule(notification.handle), notification)
        self.assertIs(self.actual_agent._intrinsic_modules["notification"], notification)
        closure = self.actual_agent._intrinsics["notification"]
        self.assertTrue(closure.__defaults__)
        self.assertIs(closure.__defaults__[0], notification.handle)

        raw = notification.get_schema()
        self.assertEqual(set(raw), {"type", "properties", "required", "additionalProperties"})
        self.assertEqual(set(raw["properties"]), {"action", "input"})
        self.assertEqual(raw["required"], ["action", "input"])
        self.assertFalse(raw["additionalProperties"])
        self.assertNotIn("reasoning", raw["properties"])
        self.assertEqual(
            raw["properties"]["action"]["enum"],
            ["check", "dismiss_channel", "dismiss_event", "dismiss_ref", "manual"],
        )
        branches = raw["properties"]["input"]["anyOf"]
        self.assertEqual(
            [branch["title"] for branch in branches],
            [
                "check input",
                "dismiss_channel input",
                "dismiss_event input",
                "dismiss_ref input",
                "manual input",
            ],
        )
        self.assertEqual(branches[0]["properties"], {})
        self.assertEqual(branches[4]["properties"], {})
        self.assertEqual(set(branches[1]["properties"]), {"channel", "force", "reason"})
        self.assertEqual(set(branches[2]["properties"]), {"event_id", "channel", "force", "reason"})
        self.assertEqual(set(branches[3]["properties"]), {"ref_id", "channel", "force", "reason"})
        self.assertEqual(branches[1]["required"], ["channel"])
        self.assertEqual(branches[2]["required"], ["event_id"])
        self.assertEqual(branches[3]["required"], ["ref_id"])
        for branch in branches:
            self.assertFalse(branch["additionalProperties"])
            self.assertNotIn("reasoning", branch["properties"])

        facing = next(
            schema
            for schema in self.actual_agent._build_tool_schemas()
            if schema.name == "notification"
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
        section = prompt.split("### notification\n", 1)[1].split("\n\n### ", 1)[0]
        self.assertIn("notification(action=..., input={...})", section)
        self.assertIn("BaseAgent alone adds optional root reasoning", section)
        self.assertNotIn("omit action", section.lower())

        facing = next(
            schema
            for schema in self.actual_agent._build_tool_schemas()
            if schema.name == "notification"
        )
        self.assertEqual(facing.description, notification.get_description())
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
            self.assertEqual(name, "notification")
            self.assertEqual(description, WIRE_TOOL_DESCRIPTION)
            self.assertEqual(parameters, facing.parameters)

        before = self.actual_agent._notification_store.snapshot(lambda _channel: True)
        result = self.actual_handler(
            {
                "action": "manual",
                "input": {},
                "reasoning": "verify the initialized read-only manual",
            }
        )
        after = self.actual_agent._notification_store.snapshot(lambda _channel: True)
        self.assertEqual(before, after)
        self.assertEqual(result["status"], "ok")
        self.assertTrue(self.installed_manual.is_file())
        self.assertEqual(Path(result["manual_path"]).resolve(), self.installed_manual.resolve())
        self.assertEqual(
            result["notification_manual"],
            self.installed_manual.read_text(encoding="utf-8"),
        )
        self.assertIn("notification(action='manual', input={})", result["notification_manual"])
        self.assertIn("notification(action='check', input={})", result["notification_manual"])
        self.assertNotIn("notification(action='check')", result["notification_manual"])
        self._setting(result, "missing")

    def test_strict_malformed_calls_reach_zero_action_core_or_store_seams(self):
        malformed = [
            None,
            [],
            {},
            {"action": "check"},
            {"input": {}},
            {"action": "check", "input": []},
            {"action": "unknown", "input": {}},
            {"action": 1, "input": {}},
            {"action": "check", "input": {"channel": "system"}},
            {"action": "manual", "input": {"channel": "system"}},
            {"action": "dismiss_channel", "input": {"event_id": "evt"}},
            {"action": "dismiss_channel", "input": {"channel": "system", "ref_id": "ref"}},
            {"action": "dismiss_event", "input": {"ref_id": "ref"}},
            {"action": "dismiss_ref", "input": {"event_id": "evt"}},
            {"action": "dismiss_ref", "input": {"ref_id": 3}},
            {"action": "dismiss_channel", "input": {"channel": "system", "force": "yes"}},
            {"action": "dismiss_event", "input": {"event_id": "evt", "reason": 4}},
            {"action": "manual", "input": {}, "surprise": True},
            {"action": "manual", "input": {}, "reasoning": 4},
            {"action": "manual", "input": _OddKeys([])},
            {"action": "manual", "input": _OddKeys(1)},
            _OddKeys([]),
            _OddKeys(1),
            {1: "manual", "input": {}},
        ]
        store = self.fake._notification_store
        store.reset_calls()
        with patch.object(notification, "_check") as check_seam, \
             patch.object(notification, "_manual") as manual_seam, \
             patch.object(notification, "dismiss_channel") as core_seam:
            for args in malformed:
                with self.subTest(args=repr(args)):
                    result = notification.handle(self.fake, args)
                    self.assertEqual(result["status"], "error")
                    self._setting(result, None)
            self.assertEqual(check_seam.call_count, 0)
            self.assertEqual(manual_seam.call_count, 0)
            self.assertEqual(core_seam.call_count, 0)
        self.assertEqual(store.calls, [])

    def test_settings_missing_valid_hot_invalid_and_invariance(self):
        prompt_before = self.actual_agent._prompt_manager.read_section("tools")
        raw_schema = notification.get_schema()
        args = {"action": "check", "input": {}, "reasoning": "settings evidence"}

        missing = notification.handle(self.fake, args)
        missing_setting = self._setting(missing, "missing")
        self.assertEqual(missing_setting["settings_revision"], "missing")
        self.assertIsNone(missing_setting["settings_hash"])
        missing_body = self._without_setting(missing)

        self.settings.write_bytes(b'{"schema_version":1}')
        valid = notification.handle(self.fake, args)
        valid_setting = self._setting(valid, "settings/notification.json")
        self.assertEqual(len(valid_setting["settings_hash"]), 32)
        self.assertEqual(valid_setting["settings_revision"], valid_setting["settings_hash"])
        self.assertEqual(self._without_setting(valid), missing_body)

        self.settings.write_bytes(b'{ "schema_version" : 1 }\n')
        hot = notification.handle(self.fake, args)
        hot_setting = self._setting(hot, "settings/notification.json")
        self.assertNotEqual(hot_setting["settings_revision"], valid_setting["settings_revision"])
        self.assertNotEqual(hot_setting["settings_hash"], valid_setting["settings_hash"])
        self.assertEqual(self._without_setting(hot), missing_body)

        secret = "NOTIFICATION_SETTINGS_SECRET_SENTINEL"
        private_path = str(self.settings.resolve())
        invalid_values = [
            '{"schema_version":2}',
            '{"schema_version":"1"}',
            '{"schema_version":1,"secret":"' + secret + '"}',
            json.dumps({"schema_version": 1, "private_path": private_path}),
            '{"schema_version":1,"schema_version":1}',
            "not-json",
        ]
        for text in invalid_values:
            self.settings.write_text(text, encoding="utf-8")
            invalid = notification.handle(self.fake, args)
            setting = self._setting(invalid, "settings_error")
            self.assertIn("settings_error", setting)
            rendered = json.dumps(invalid, sort_keys=True)
            self.assertNotIn(secret, rendered)
            self.assertNotIn(private_path, rendered)
            self.assertEqual(self._without_setting(invalid), missing_body)

        self.assertEqual(prompt_before, self.actual_agent._prompt_manager.read_section("tools"))
        self.assertNotIn(secret, self.actual_agent._prompt_manager.read_section("tools"))
        self.assertNotIn(private_path, self.actual_agent._prompt_manager.read_section("tools"))
        self.assertEqual(notification.get_schema(), raw_schema)
        self.settings.write_bytes(b'{"schema_version":1}')

    def test_candidate_owned_fake_state_semantics_and_guards(self):
        store = self.fake._notification_store

        store.reset_calls()
        checked = notification.handle(self.fake, {"action": "check", "input": {}})
        self.assertTrue(checked["_notification_placeholder"])
        self.assertEqual(store.calls, [])

        version = ("soul.json", 1, "soul-v1")
        self._deliver("soul", version, {"header": "fake soul"})
        cleared = notification.handle(
            self.fake,
            {"action": "dismiss_channel", "input": {"channel": "soul"}},
        )
        self.assertEqual(cleared["status"], "ok")
        self.assertTrue(cleared["cleared"])
        self.assertNotIn("soul", store.payloads)

        system_version = ("system.json", 2, "system-v2")
        self._deliver(
            "system",
            system_version,
            {
                "header": "3 system notifications",
                "data": {
                    "events": [
                        {"event_id": "evt-a", "ref_id": "ref-a"},
                        {"event_id": "evt-b", "ref_id": "ref-b"},
                        {"event_id": "evt-c", "ref_id": "ref-b"},
                    ]
                },
            },
        )
        event = notification.handle(
            self.fake,
            {"action": "dismiss_event", "input": {"event_id": "evt-a"}},
        )
        self.assertEqual(event["status"], "ok")
        self.assertEqual(event["removed"], 1)
        ref = notification.handle(
            self.fake,
            {"action": "dismiss_ref", "input": {"ref_id": "ref-b"}},
        )
        self.assertEqual(ref["status"], "ok")
        self.assertEqual(ref["removed"], 2)
        self.assertNotIn("system", store.payloads)

        old = ("system.json", 3, "old")
        current = ("system.json", 4, "current")
        store.payloads["system"] = {"header": "changed", "data": {"events": []}}
        store.versions["system"] = current
        self.fake._notification_fp = (old,)
        store.reset_calls()
        stale = notification.handle(
            self.fake,
            {"action": "dismiss_channel", "input": {"channel": "system"}},
        )
        self.assertEqual(stale["reason"], "stale_channel_version")
        self.assertIn("system", store.payloads)
        forced = notification.handle(
            self.fake,
            {"action": "dismiss_channel", "input": {"channel": "system", "force": True}},
        )
        self.assertEqual(forced["status"], "ok")
        self.assertTrue(forced["forced"])
        self.assertNotIn("system", store.payloads)

        store.reset_calls()
        with patch(
            "lingtai.kernel.notifications.is_generic_dismiss_guarded",
            return_value="email(action='dismiss', input={})",
        ):
            guarded = notification.handle(
                self.fake,
                {"action": "dismiss_channel", "input": {"channel": "email"}},
            )
        self.assertEqual(guarded["reason"], "guarded")
        self.assertEqual(store.calls, [])

        protected = notification.handle(
            self.fake,
            {"action": "dismiss_channel", "input": {"channel": "goal", "force": True}},
        )
        self.assertEqual(protected["reason"], "protected_channel")

        atomic_wrong_channel = notification.handle(
            self.fake,
            {
                "action": "dismiss_event",
                "input": {"event_id": "evt", "channel": "soul", "force": True},
            },
        )
        self.assertEqual(
            atomic_wrong_channel["reason"],
            "atomic_dismiss_requires_system_channel",
        )

        post_version = ("post-molt.json", 5, "post")
        self._deliver("post-molt", post_version, {"header": "continue"})
        missing_reason = notification.handle(
            self.fake,
            {"action": "dismiss_channel", "input": {"channel": "post-molt"}},
        )
        self.assertEqual(missing_reason["reason"], "missing_ack_reason")
        acknowledged = notification.handle(
            self.fake,
            {
                "action": "dismiss_channel",
                "input": {"channel": "post-molt", "reason": "continue: tested"},
            },
        )
        self.assertEqual(acknowledged["status"], "ok")
        self.assertEqual(acknowledged["reason"], "continue: tested")

        manual_path = (
            self.fake_workdir
            / ".library"
            / "intrinsic"
            / "capabilities"
            / "notification-manual"
            / "SKILL.md"
        )
        manual_path.parent.mkdir(parents=True, exist_ok=True)
        manual_body = "---\nname: notification-manual\n---\n\n# candidate-owned fake manual\n"
        manual_path.write_text(manual_body, encoding="utf-8")
        store.reset_calls()
        manual = notification.handle(self.fake, {"action": "manual", "input": {}})
        self.assertEqual(manual["notification_manual"], manual_body)
        self.assertEqual(store.calls, [])

    def test_all_five_action_exceptions_are_bounded_and_core_error_is_sanitized(self):
        sentinel = "NOTIFICATION_PRIVATE_ACTION_SECRET"
        error_cases = [
            (
                "check",
                lambda: patch.object(notification, "_check", side_effect=RuntimeError(sentinel)),
                {"action": "check", "input": {}},
            ),
            (
                "dismiss_channel",
                lambda: patch.object(notification, "dismiss_channel", side_effect=RuntimeError(sentinel)),
                {"action": "dismiss_channel", "input": {"channel": "soul", "force": True}},
            ),
            (
                "dismiss_event",
                lambda: patch.object(notification, "dismiss_channel", side_effect=RuntimeError(sentinel)),
                {"action": "dismiss_event", "input": {"event_id": "evt", "force": True}},
            ),
            (
                "dismiss_ref",
                lambda: patch.object(notification, "dismiss_channel", side_effect=RuntimeError(sentinel)),
                {"action": "dismiss_ref", "input": {"ref_id": "ref", "force": True}},
            ),
            (
                "manual",
                lambda: patch.object(notification, "_manual", side_effect=RuntimeError(sentinel)),
                {"action": "manual", "input": {}},
            ),
        ]
        for label, seam_factory, args in error_cases:
            with self.subTest(action=label), seam_factory() as seam:
                result = notification.handle(self.fake, args)
                self.assertEqual(seam.call_count, 1)
                self.assertEqual(result["status"], "error")
                self.assertEqual(result["reason"], "notification_action_failed")
                self.assertEqual(result["message"], "notification action failed")
                self._setting(result, None)
                self.assertNotIn(sentinel, json.dumps(result, sort_keys=True))

        store = self.fake._notification_store
        version = ("soul.json", 9, "error")
        self._deliver("soul", version, {"header": "retained"})
        store.compare_error = OSError("/private/store/" + sentinel)
        try:
            failed = notification.handle(
                self.fake,
                {"action": "dismiss_channel", "input": {"channel": "soul"}},
            )
        finally:
            store.compare_error = None
        self.assertEqual(failed["status"], "error")
        self.assertEqual(failed["reason"], "clear_failed")
        self.assertEqual(failed["message"], "notification mirror operation failed")
        self.assertNotIn(sentinel, json.dumps(failed, sort_keys=True))
        self.assertIn("soul", store.payloads)


if __name__ == "__main__":
    unittest.main(verbosity=2)
