"""Tests for WeChat MCP config-path resolution (``Lingtai-AI/lingtai#336``).

WeChat used to resolve a relative ``LINGTAI_WECHAT_CONFIG`` only against the
project root (``LINGTAI_AGENT_DIR.parent.parent``), diverging from imap/telegram/
feishu which resolve against ``LINGTAI_AGENT_DIR``. That divergence caused a
``FileNotFoundError`` when an agent's WeChat secrets lived in the agent dir.

These tests pin the new policy: absolute paths unchanged; relative paths prefer
the agent dir; project root is a backward-compat fallback; a clear, secret-free
diagnostic is surfaced when neither exists; and the ``LINGTAI_AGENT_DIR``-unset
case falls back to cwd. The load path and the status/diagnostics path must use
the same helper.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from lingtai.mcp_servers.wechat import server


def _write_config(dir_path: Path) -> Path:
    dir_path.mkdir(parents=True, exist_ok=True)
    cfg = dir_path / "config.json"
    cfg.write_text(json.dumps({"poll_interval": 1.0}), encoding="utf-8")
    return cfg


def _write_manager_config(config_path: Path) -> None:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps({"poll_interval": 1.0}), encoding="utf-8")
    (config_path.parent / "credentials.json").write_text(
        json.dumps({"bot_token": "x", "user_id": "wxid_x"}),
        encoding="utf-8",
    )


def _agent_layout(tmp_path: Path) -> tuple[Path, Path]:
    """Return (project_root, agent_dir) for ``<project>/.lingtai/<agent>/``."""
    project_root = tmp_path / "project"
    agent_dir = project_root / ".lingtai" / "agent"
    agent_dir.mkdir(parents=True, exist_ok=True)
    return project_root, agent_dir


# --- absolute paths ---------------------------------------------------------

def test_absolute_config_path_unchanged(tmp_path, monkeypatch):
    abs_cfg = tmp_path / "elsewhere" / "config.json"
    _write_config(abs_cfg.parent)
    # agent dir set but must be ignored for absolute paths
    monkeypatch.setenv("LINGTAI_AGENT_DIR", str(tmp_path / "agent"))

    resolved, diag = server._resolve_config_path(str(abs_cfg))

    assert resolved == abs_cfg
    assert diag["base"] == "absolute"
    assert diag["resolved_via"] == "absolute"
    assert diag["candidates"] == [str(abs_cfg)]


# --- relative under the agent dir (preferred) -------------------------------

def test_relative_config_prefers_agent_dir(tmp_path, monkeypatch):
    project_root, agent_dir = _agent_layout(tmp_path)
    _write_config(agent_dir / ".secrets" / "wechat")
    monkeypatch.setenv("LINGTAI_AGENT_DIR", str(agent_dir))

    resolved, diag = server._resolve_config_path(".secrets/wechat/config.json")

    assert resolved == agent_dir / ".secrets" / "wechat" / "config.json"
    assert diag["resolved_via"] == "agent_dir"
    assert diag["base"] == "agent_dir"


def test_agent_dir_wins_over_project_root_when_both_exist(tmp_path, monkeypatch):
    project_root, agent_dir = _agent_layout(tmp_path)
    _write_config(agent_dir / ".secrets" / "wechat")
    _write_config(project_root / ".secrets" / "wechat")
    monkeypatch.setenv("LINGTAI_AGENT_DIR", str(agent_dir))

    resolved, diag = server._resolve_config_path(".secrets/wechat/config.json")

    assert resolved == agent_dir / ".secrets" / "wechat" / "config.json"
    assert diag["resolved_via"] == "agent_dir"


# --- project-root backward-compat fallback ----------------------------------

def test_relative_config_falls_back_to_project_root(tmp_path, monkeypatch):
    project_root, agent_dir = _agent_layout(tmp_path)
    # Only the project-root copy exists (old bootstrap convention / #336 workaround)
    _write_config(project_root / ".secrets" / "wechat")
    monkeypatch.setenv("LINGTAI_AGENT_DIR", str(agent_dir))

    resolved, diag = server._resolve_config_path(".secrets/wechat/config.json")

    assert resolved == project_root / ".secrets" / "wechat" / "config.json"
    assert diag["resolved_via"] == "project_root"
    # agent dir is still the preferred base reported in diagnostics
    assert diag["base"] == "agent_dir"


# --- neither exists: clear diagnostics, no secrets --------------------------

def test_no_candidate_exists_reports_candidates(tmp_path, monkeypatch):
    project_root, agent_dir = _agent_layout(tmp_path)
    monkeypatch.setenv("LINGTAI_AGENT_DIR", str(agent_dir))

    resolved, diag = server._resolve_config_path(".secrets/wechat/config.json")

    # Resolves to the preferred (agent-dir) candidate as the canonical location
    assert resolved == agent_dir / ".secrets" / "wechat" / "config.json"
    assert diag["resolved_via"] is None
    # Both candidate bases are surfaced for diagnosis
    assert any(".lingtai" in c and "agent" in c for c in diag["candidates"])
    project_cand = str(project_root / ".secrets" / "wechat" / "config.json")
    assert project_cand in diag["candidates"]


def test_load_config_failure_lists_candidates_without_secrets(tmp_path, monkeypatch):
    project_root, agent_dir = _agent_layout(tmp_path)
    monkeypatch.setenv("LINGTAI_AGENT_DIR", str(agent_dir))
    monkeypatch.setenv("LINGTAI_WECHAT_CONFIG", ".secrets/wechat/config.json")

    with pytest.raises(FileNotFoundError) as excinfo:
        server.load_config_and_credentials()

    msg = str(excinfo.value)
    # Both candidate paths appear so the user can see where it looked
    assert str(agent_dir / ".secrets" / "wechat" / "config.json") in msg
    assert str(project_root / ".secrets" / "wechat" / "config.json") in msg
    # Diagnostic names the env var that controls resolution
    assert "LINGTAI_AGENT_DIR" in msg


def test_load_config_failure_absolute_path_not_called_relative(tmp_path, monkeypatch):
    # Absolute, non-existent config path: the error must not call it "relative".
    abs_cfg = tmp_path / "nowhere" / "config.json"
    monkeypatch.setenv("LINGTAI_AGENT_DIR", str(tmp_path / "agent"))
    monkeypatch.setenv("LINGTAI_WECHAT_CONFIG", str(abs_cfg))

    with pytest.raises(FileNotFoundError) as excinfo:
        server.load_config_and_credentials()

    msg = str(excinfo.value)
    # Lists the absolute candidate...
    assert str(abs_cfg) in msg
    # ...and explicitly calls it absolute, never "relative path".
    assert "absolute path" in msg
    assert "relative path" not in msg
    # Agent-dir / project-root guidance is irrelevant for an absolute path.
    assert "project root" not in msg


# --- LINGTAI_AGENT_DIR unset: cwd fallback ----------------------------------

def test_missing_agent_dir_falls_back_to_cwd(tmp_path, monkeypatch):
    monkeypatch.delenv("LINGTAI_AGENT_DIR", raising=False)
    _write_config(tmp_path / ".secrets" / "wechat")
    monkeypatch.chdir(tmp_path)

    resolved, diag = server._resolve_config_path(".secrets/wechat/config.json")

    assert resolved == tmp_path / ".secrets" / "wechat" / "config.json"
    assert diag["base"] == "cwd"
    assert diag["resolved_via"] == "cwd"
    assert diag["agent_dir"] is None


@pytest.mark.parametrize(
    "resolution_case",
    ("absolute", "agent_relative", "legacy_root", "cwd", "normalized"),
)
def test_build_manager_snapshots_exact_loaded_config_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    resolution_case: str,
):
    project_root, agent_dir = _agent_layout(tmp_path)
    relative_path = Path(".secrets/wechat/owner-settings.json")

    if resolution_case == "absolute":
        selected_path = tmp_path / "absolute" / "owner-settings.json"
        config_path_raw = str(selected_path)
        monkeypatch.setenv("LINGTAI_AGENT_DIR", str(agent_dir))
    elif resolution_case == "agent_relative":
        selected_path = agent_dir / relative_path
        config_path_raw = str(relative_path)
        monkeypatch.setenv("LINGTAI_AGENT_DIR", str(agent_dir))
    elif resolution_case == "legacy_root":
        selected_path = project_root / relative_path
        config_path_raw = str(relative_path)
        monkeypatch.setenv("LINGTAI_AGENT_DIR", str(agent_dir))
    elif resolution_case == "cwd":
        selected_path = tmp_path / relative_path
        config_path_raw = str(relative_path)
        monkeypatch.delenv("LINGTAI_AGENT_DIR", raising=False)
        monkeypatch.chdir(tmp_path)
    else:
        normalized_raw = ".secrets/wechat/intermediate/../owner-settings.json"
        selected_path = agent_dir / Path(normalized_raw)
        config_path_raw = normalized_raw
        monkeypatch.setenv("LINGTAI_AGENT_DIR", str(agent_dir))
        (agent_dir / ".secrets" / "wechat" / "intermediate").mkdir(
            parents=True,
        )

    _write_manager_config(selected_path)
    monkeypatch.setenv("LINGTAI_WECHAT_CONFIG", config_path_raw)

    manager, _working_dir = server.build_manager()

    assert manager._settings_config_path == str(selected_path)


def test_build_manager_keeps_loaded_path_when_environment_changes_between_reads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    _project_root, agent_dir = _agent_layout(tmp_path)
    selected_path = agent_dir / ".secrets" / "wechat" / "loaded-settings.json"
    _write_manager_config(selected_path)
    monkeypatch.setenv("LINGTAI_AGENT_DIR", str(agent_dir))
    monkeypatch.setenv(
        "LINGTAI_WECHAT_CONFIG",
        ".secrets/wechat/loaded-settings.json",
    )
    load_config_and_credentials = server.load_config_and_credentials

    def load_then_change_environment():
        loaded = load_config_and_credentials()
        monkeypatch.setenv(
            "LINGTAI_WECHAT_CONFIG",
            ".secrets/wechat/different-settings.json",
        )
        return loaded

    monkeypatch.setattr(
        server,
        "load_config_and_credentials",
        load_then_change_environment,
    )

    manager, _working_dir = server.build_manager()

    assert manager._settings_config_path == str(selected_path)


# --- load path and status path share the same resolution --------------------

def test_load_and_status_resolve_identically(tmp_path, monkeypatch):
    project_root, agent_dir = _agent_layout(tmp_path)
    cfg = _write_config(agent_dir / ".secrets" / "wechat")
    (cfg.parent / "credentials.json").write_text(
        json.dumps({"bot_token": "x", "user_id": "wxid_x"}), encoding="utf-8"
    )
    monkeypatch.setenv("LINGTAI_AGENT_DIR", str(agent_dir))
    monkeypatch.setenv("LINGTAI_WECHAT_CONFIG", ".secrets/wechat/config.json")

    _file_cfg, _creds, loaded_config_path = server.load_config_and_credentials()
    status_path = server._resolve_config_path_for_status(".secrets/wechat/config.json")

    assert loaded_config_path == cfg
    assert status_path == cfg


def test_status_payload_exposes_resolution_without_secrets(tmp_path, monkeypatch):
    project_root, agent_dir = _agent_layout(tmp_path)
    # project-root-only layout exercises the backward-compat note
    cfg = _write_config(project_root / ".secrets" / "wechat")
    (cfg.parent / "credentials.json").write_text(
        json.dumps({"bot_token": "secret-token", "user_id": "wxid_x"}),
        encoding="utf-8",
    )
    monkeypatch.setenv("LINGTAI_AGENT_DIR", str(agent_dir))
    monkeypatch.setenv("LINGTAI_WECHAT_CONFIG", ".secrets/wechat/config.json")

    payload = server._safe_status_payload(None)

    resolution = payload["config_resolution"]
    assert resolution["resolved_via"] == "project_root"
    assert resolution["candidates"]
    # bot_token must never leak into status
    assert "secret-token" not in json.dumps(payload)
    assert payload["has_bot_token"] is True
    # backward-compat resolution is flagged in notes
    assert any("backward-compat" in n for n in payload["notes"])
    assert any("pre-signed upload_full_url" in n for n in payload["notes"])
