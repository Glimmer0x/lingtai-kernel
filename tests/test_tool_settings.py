"""Focused tests for the private no-op placeholder-settings foundation."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from lingtai.tools._settings import (
    MAX_SETTINGS_BYTES,
    current_setting,
    read_settings,
    settings_path,
    valid_tool_name,
)


class _Agent:
    def __init__(self, root: Path) -> None:
        self._working_dir = root


def _write(root: Path, tool_name: str, payload: str | bytes) -> Path:
    path = root / "settings" / f"{tool_name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, bytes):
        path.write_bytes(payload)
    else:
        path.write_text(payload, encoding="utf-8")
    return path


def test_missing_is_a_normal_noop_placeholder_state(tmp_path):
    snapshot = read_settings(_Agent(tmp_path), "example")
    setting = current_setting(snapshot, "example")
    assert setting == {
        "configurable": False,
        "placeholder": "no-op",
        "source": "missing",
        "settings_revision": "missing",
        "settings_hash": None,
        "change_hint": (
            "Edit settings/example.json; changes apply on the next example call; "
            "this no-op placeholder never changes tool behavior."
        ),
    }


def test_valid_v1_only_changes_source_revision_and_hash(tmp_path):
    agent = _Agent(tmp_path)
    _write(tmp_path, "example", '{"schema_version": 1}')
    snapshot = read_settings(agent, "example")
    setting = current_setting(snapshot, "example")
    assert snapshot.error is None
    assert setting["configurable"] is False
    assert setting["placeholder"] == "no-op"
    assert setting["source"] == "settings/example.json"
    assert setting["settings_revision"] == setting["settings_hash"]
    assert setting["settings_hash"]


def test_reader_rereads_hot_changes_without_cache(tmp_path):
    agent = _Agent(tmp_path)
    path = _write(tmp_path, "example", '{"schema_version": 1}')
    first = read_settings(agent, "example")
    path.write_text('{ "schema_version": 1 }', encoding="utf-8")
    second = read_settings(agent, "example")
    assert first.digest != second.digest
    assert second.source == "settings/example.json"


def test_duplicate_and_extra_fields_are_invalid(tmp_path):
    agent = _Agent(tmp_path)
    duplicate = _write(tmp_path, "duplicate", '{"schema_version": 1, "schema_version": 1}')
    duplicate_snapshot = read_settings(agent, "duplicate")
    assert duplicate_snapshot.source == "settings_error"
    assert "duplicate" in (duplicate_snapshot.error or "")

    extra = _write(tmp_path, "extra", '{"schema_version": 1, "future": false}')
    extra_snapshot = read_settings(agent, "extra")
    assert extra_snapshot.source == "settings_error"
    assert "only schema_version" in (extra_snapshot.error or "")


def test_bool_and_other_schema_versions_are_invalid(tmp_path):
    agent = _Agent(tmp_path)
    for name, version in (("bool", True), ("float", 1.0), ("other", 2)):
        _write(tmp_path, name, json.dumps({"schema_version": version}))
        snapshot = read_settings(agent, name)
        assert snapshot.source == "settings_error"
        assert "integer 1" in (snapshot.error or "")


def test_invalid_encoding_and_json_are_truthful_bounded_errors(tmp_path):
    agent = _Agent(tmp_path)
    _write(tmp_path, "encoding", b'{"schema_version": 1}\xff')
    encoding_snapshot = read_settings(agent, "encoding")
    assert encoding_snapshot.source == "settings_error"
    assert encoding_snapshot.error

    _write(tmp_path, "json", "{not-json")
    json_snapshot = read_settings(agent, "json")
    assert json_snapshot.source == "settings_error"
    assert json_snapshot.error
    assert len(json_snapshot.error) <= 240


def test_symlink_non_regular_and_oversized_files_are_rejected(tmp_path):
    agent = _Agent(tmp_path)
    target = tmp_path / "outside.json"
    target.write_text('{"schema_version": 1}', encoding="utf-8")
    symlink = tmp_path / "settings" / "symlink.json"
    symlink.parent.mkdir()
    symlink.symlink_to(target)
    symlink_snapshot = read_settings(agent, "symlink")
    assert symlink_snapshot.source == "settings_error"
    assert "regular file" in (symlink_snapshot.error or "")

    non_regular = tmp_path / "settings" / "directory.json"
    non_regular.mkdir()
    directory_snapshot = read_settings(agent, "directory")
    assert directory_snapshot.source == "settings_error"
    assert "regular file" in (directory_snapshot.error or "")

    _write(tmp_path, "large", b"{" + b"x" * MAX_SETTINGS_BYTES + b"}")
    large_snapshot = read_settings(agent, "large")
    assert large_snapshot.source == "settings_error"
    assert "bounded size" in (large_snapshot.error or "")


def test_unstable_snapshot_is_not_treated_as_missing(tmp_path, monkeypatch):
    import lingtai.tools._settings as settings_module

    agent = _Agent(tmp_path)
    _write(tmp_path, "unstable", '{"schema_version": 1}')

    def raise_unstable(_path):
        raise settings_module.SettingsError("settings snapshot changed during read")

    monkeypatch.setattr(settings_module, "_read_stable", raise_unstable)
    snapshot = read_settings(agent, "unstable")
    assert snapshot.source == "settings_error"
    assert snapshot.revision == "error"
    assert snapshot.error == "settings snapshot changed during read"


def test_tool_names_are_bounded_path_components(tmp_path):
    assert valid_tool_name("web_search")
    assert not valid_tool_name("../escape")
    assert not valid_tool_name("nested/name")
    assert not valid_tool_name("\\escape")
    assert not valid_tool_name("x" * 65)
    with pytest.raises(ValueError):
        settings_path(_Agent(tmp_path), "../escape")
