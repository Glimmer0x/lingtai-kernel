"""Focused execution-workspace rooting and isolation tests."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from lingtai.kernel.execution_workspace import (
    ExecutionWorkspace,
    bind_execution_workspace,
    current_execution_workspace,
    reset_execution_workspace,
)
from lingtai.kernel.risky_action_gate import build_risky_action_check
from lingtai.kernel.tool_call_guard import ToolProposal
from lingtai.services.file_io import LocalFileIOService
from lingtai.tools._file_paths import resolve_workdir_path
from lingtai.tools.bash import ShellManager, ShellPolicy
from lingtai.tools.file._edit import build_operation as build_edit
from lingtai.tools.file._glob import build_operation as build_glob
from lingtai.tools.file._grep import build_operation as build_grep
from lingtai.tools.file._read import build_operation as build_read
from lingtai.tools.file._write import build_operation as build_write


def test_execution_workspace_canonicalizes_and_requires_existing_directory(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(workspace, target_is_directory=True)

    assert ExecutionWorkspace(alias).root == workspace.resolve()
    with pytest.raises(ValueError, match="existing directory"):
        ExecutionWorkspace(tmp_path / "missing")
    not_directory = tmp_path / "file"
    not_directory.write_text("x")
    with pytest.raises(ValueError, match="existing directory"):
        ExecutionWorkspace(not_directory)


def test_non_workspace_file_and_shell_keep_historical_agent_root(tmp_path: Path):
    agent_dir = tmp_path / "agent"
    outside = tmp_path / "outside"
    agent_dir.mkdir()
    outside.mkdir()
    absolute = outside / "x.txt"

    assert resolve_workdir_path(agent_dir, absolute) is absolute
    assert resolve_workdir_path(agent_dir, "nested/x.txt") == str(agent_dir / "nested/x.txt")

    shell = ShellManager(ShellPolicy.yolo(), str(agent_dir), rehydrate=False)
    escaped = shell.handle({
        "action": "run", "command": "pwd", "working_dir": "../outside"
    })
    assert escaped["status"] == "error"
    assert "must be under agent working directory" in escaped["message"]


def test_file_and_shell_use_canonical_workspace_outside_agent_dir(tmp_path: Path):
    process_cwd = Path.cwd()
    agent_dir = tmp_path / "agent"
    workspace = tmp_path / "project"
    agent_dir.mkdir()
    workspace.mkdir()
    workdir = SimpleNamespace(path=agent_dir)
    service = LocalFileIOService(root=agent_dir)
    file_io = SimpleNamespace(
        read=service.read,
        write=service.write,
        glob=service.glob,
        grep=service.grep,
        max_result_chars=500_000,
        last_traversal=service.last_traversal,
    )
    token = bind_execution_workspace(ExecutionWorkspace(workspace.resolve()))
    try:
        written = build_write(workdir, file_io)({"file_path": "src/a.txt", "content": "ok"})
        assert written["status"] == "ok"
        assert (workspace / "src/a.txt").read_text() == "ok"
        assert build_read(workdir, file_io)({"file_path": "src/a.txt"})["content"] == "1\tok"
        assert build_glob(workdir, file_io)({"pattern": "**/*.txt"})["count"] == 1

        shell = ShellManager(ShellPolicy.yolo(), str(agent_dir), rehydrate=False)
        result = shell.handle({"action": "run", "command": "pwd"})
        assert result["status"] == "ok"
        assert Path(result["stdout"].strip()).resolve() == workspace.resolve()
        (workspace / "subdir").mkdir()
        relative = shell.handle({
            "action": "run", "command": "pwd", "working_dir": "subdir"
        })
        assert Path(relative["stdout"].strip()).resolve() == (workspace / "subdir").resolve()
        assert shell.handle({
            "action": "run", "command": "pwd", "working_dir": "../outside"
        })["message"] == "Invalid working_dir path"
    finally:
        reset_execution_workspace(token)

    assert current_execution_workspace() is None
    assert Path.cwd() == process_cwd
    assert not (agent_dir / "src/a.txt").exists()


def test_file_rejects_parent_and_symlink_escape(tmp_path: Path):
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    workspace.mkdir()
    outside.mkdir()
    (workspace / "link").symlink_to(outside, target_is_directory=True)
    workdir = SimpleNamespace(path=tmp_path / "agent")
    service = LocalFileIOService(root=workdir.path)
    file_io = SimpleNamespace(read=service.read, write=service.write)
    token = bind_execution_workspace(ExecutionWorkspace(workspace.resolve()))
    try:
        parent = build_write(workdir, file_io)({"file_path": "../outside/a", "content": "x"})
        linked = build_write(workdir, file_io)({"file_path": "link/a", "content": "x"})
        read_escape = build_read(workdir, file_io)({"file_path": "../outside/a"})
        edit_escape = build_edit(workdir, file_io)({
            "file_path": "../outside/a", "old_string": "x", "new_string": "y"
        })
        grep_escape = build_grep(workdir, file_io)({
            "pattern": "x", "path": "../outside"
        })
        glob_escape = build_glob(workdir, file_io)({
            "pattern": "*", "path": "../outside"
        })
        for result in (parent, linked, read_escape, edit_escape, grep_escape, glob_escape):
            assert result["status"] == "error"
            assert "escapes execution workspace" in result["message"]
    finally:
        reset_execution_workspace(token)
    assert not (outside / "a").exists()


def test_risky_action_guard_canonicalizes_relative_target_from_workspace(tmp_path: Path):
    agent_dir = tmp_path / "agent"
    workspace = tmp_path / "workspace"
    (agent_dir / ".security").mkdir(parents=True)
    workspace.mkdir()
    (agent_dir / ".security/gate_config.json").write_text(json.dumps({
        "local_write_roots": [str(workspace)],
    }))
    check = build_risky_action_check(agent_dir)
    token = bind_execution_workspace(ExecutionWorkspace(workspace.resolve()))
    try:
        decision = check(ToolProposal(
            tool_name="file",
            tool_args={"action": "write", "input": {"file_path": "nested/a.txt"}},
        ))
        escaped_shell = check(ToolProposal(
            tool_name="shell",
            tool_args={
                "action": "run",
                "input": {"command": "pwd", "working_dir": "../outside"},
            },
        ))
    finally:
        reset_execution_workspace(token)
    assert decision.allowed
    assert not escaped_shell.allowed
    assert escaped_shell.reason == "shell working_dir escapes execution workspace"
    assert "pending_request_id" not in escaped_shell.metadata
    assert not (agent_dir / ".security/pending").exists()
