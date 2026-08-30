"""Focused proofs for Notification's five-field SHOW settings action."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

import lingtai.tools.notification as notification_tool
import lingtai.tools.notification.settings as notification_settings
from lingtai.tools.notification import DECLARATION
from tests._notification_helpers import StubAgent
from tests._tool_plugin_helpers import dispatch_declared_tool

_DEFAULT_INPUT = object()


class _SettingsAgent(StubAgent):
    """Notification stub retaining the real outer System-v2 file hook."""

    def resolve_notification_max_chars(self) -> int | None:
        from lingtai.tools.system.settings import resolve_notification_max_chars

        return resolve_notification_max_chars(self)


def _settings(agent: Any, action_input: Any = _DEFAULT_INPUT) -> dict[str, Any]:
    return dispatch_declared_tool(
        DECLARATION,
        agent,
        {
            "action": "settings",
            "input": {} if action_input is _DEFAULT_INPUT else action_input,
            "reasoning": "settings test",
        },
    )


def _write_system_v2(agent: _SettingsAgent, max_chars: int) -> Path:
    path = agent._working_dir / "settings" / "system.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {"schema_version": 2, "notification_max_chars": max_chars},
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    return path


def _tree_snapshot(root: Path) -> dict[str, bytes | None]:
    return {
        path.relative_to(root).as_posix(): None if path.is_dir() else path.read_bytes()
        for path in root.rglob("*")
        if path.is_dir() or path.is_file()
    }


def test_exact_ordered_five_field_rows_defaults_comments_and_family_opt_in(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("LINGTAI_NOTIFICATION_MAX_CHARS", raising=False)
    monkeypatch.delenv("LINGTAI_NOTIFICATION_DELAY_MAX_SECONDS", raising=False)

    result = _settings(_SettingsAgent(tmp_path))

    assert DECLARATION.settings is True
    assert DECLARATION.public_actions[-2:] == ("settings", "manual")
    assert result == {
        "settings": [
            {
                "key": "notification.max_chars",
                "current": 10_000,
                "default": 10_000,
                "configurable": True,
                "comment": (
                    "notification-manual#block-size-cap-persistent-and-attention-lanes"
                ),
            },
            {
                "key": "notification.delay_max_seconds",
                "current": 600,
                "default": 600,
                "configurable": True,
                "comment": "notification-manual#consumer-delay-and-expiry-alarm",
            },
        ]
    }
    assert [row["key"] for row in result["settings"]] == [
        "notification.max_chars",
        "notification.delay_max_seconds",
    ]
    assert all(
        list(row) == ["key", "current", "default", "configurable", "comment"]
        for row in result["settings"]
    )
    assert "<redacted>" not in repr(result)


def test_live_environment_system_v2_precedence_clamps_and_fallbacks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    agent = _SettingsAgent(tmp_path)
    monkeypatch.delenv("LINGTAI_NOTIFICATION_MAX_CHARS", raising=False)
    monkeypatch.delenv("LINGTAI_NOTIFICATION_DELAY_MAX_SECONDS", raising=False)
    system_path = _write_system_v2(agent, 3_000)

    assert _settings(agent)["settings"][0]["current"] == 3_000
    system_path.write_text(
        '{"schema_version":2,"notification_max_chars":4000}',
        encoding="utf-8",
    )
    assert _settings(agent)["settings"][0]["current"] == 4_000

    monkeypatch.setenv("LINGTAI_NOTIFICATION_MAX_CHARS", "2500")
    monkeypatch.setenv("LINGTAI_NOTIFICATION_DELAY_MAX_SECONDS", "45")
    rows = _settings(agent)["settings"]
    assert [(row["current"], row["default"]) for row in rows] == [
        (2_500, 10_000),
        (45, 600),
    ]

    monkeypatch.setenv("LINGTAI_NOTIFICATION_MAX_CHARS", "not-an-integer")
    monkeypatch.setenv("LINGTAI_NOTIFICATION_DELAY_MAX_SECONDS", "0")
    fallback_rows = _settings(agent)["settings"]
    assert fallback_rows[0]["current"] == 4_000
    assert fallback_rows[1]["current"] == 600
    assert agent._logs == []

    monkeypatch.setenv("LINGTAI_NOTIFICATION_MAX_CHARS", "100")
    assert _settings(agent)["settings"][0]["current"] == 2_048
    monkeypatch.setenv("LINGTAI_NOTIFICATION_MAX_CHARS", "999999")
    assert _settings(agent)["settings"][0]["current"] == 10_000

    monkeypatch.setenv("LINGTAI_NOTIFICATION_MAX_CHARS", "invalid")
    system_path.write_text(
        '{"schema_version":2,"notification_max_chars":"4000"}',
        encoding="utf-8",
    )
    assert _settings(agent)["settings"][0]["current"] == 10_000


def test_comment_targets_are_exact_manual_headings() -> None:
    manual = Path(notification_settings.__file__).with_name("manual") / "SKILL.md"
    headings = set(manual.read_text(encoding="utf-8").splitlines())
    expected_headings = {
        notification_settings.MAX_CHARS_COMMENT:
            "## Block size cap (persistent and attention lanes)",
        notification_settings.DELAY_MAX_SECONDS_COMMENT:
            "## Consumer delay and expiry alarm",
    }

    for comment, heading in expected_headings.items():
        manual_name, anchor = comment.split("#", 1)
        assert manual_name == "notification-manual"
        assert heading in headings
        assert anchor == heading.removeprefix("## ").lower().translate(
            str.maketrans("", "", "()")
        ).replace(" ", "-")


def test_unavailable_current_is_one_fixed_failure_without_partial_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unavailable(_read_settings: Any) -> tuple[Any, ...]:
        raise RuntimeError("private unavailable-current detail")

    monkeypatch.setattr(notification_tool, "notification_settings", unavailable)

    assert _settings(_SettingsAgent(tmp_path)) == {
        "status": "failed",
        "error_code": "SETTINGS_UNAVAILABLE",
        "message": "settings inventory is unavailable",
    }


@pytest.mark.parametrize(
    "action_input", [None, [], {"set": "notification.max_chars"}, {"reset": True}]
)
def test_settings_accepts_only_exact_empty_input(
    tmp_path: Path, action_input: Any
) -> None:
    result = _settings(_SettingsAgent(tmp_path), action_input)
    assert result["status"] == "failed"
    assert "settings" not in result


def test_show_does_not_mutate_environment_files_logs_or_notification_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    agent = _SettingsAgent(tmp_path)
    _write_system_v2(agent, 3_000)
    monkeypatch.setenv("LINGTAI_NOTIFICATION_MAX_CHARS", "2500")
    monkeypatch.setenv("LINGTAI_NOTIFICATION_DELAY_MAX_SECONDS", "45")
    before_environment = dict(os.environ)
    before_tree = _tree_snapshot(tmp_path)
    before_logs = list(agent._logs)
    before_fingerprints = (agent._notification_fp, agent._notification_raw_fp)

    assert _settings(agent)["settings"][0]["current"] == 2_500

    assert dict(os.environ) == before_environment
    assert _tree_snapshot(tmp_path) == before_tree
    assert agent._logs == before_logs
    assert (agent._notification_fp, agent._notification_raw_fp) == before_fingerprints
    assert not (tmp_path / ".notification").exists()


def test_check_action_remains_ordinary(tmp_path: Path) -> None:
    result = dispatch_declared_tool(
        DECLARATION,
        _SettingsAgent(tmp_path),
        {"action": "check", "input": {}, "reasoning": "ordinary action"},
    )

    assert result["_notification_placeholder"] is True
