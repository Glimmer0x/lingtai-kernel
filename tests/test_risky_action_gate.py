"""Tests for the opt-in kernel risky-action gate."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from lingtai.kernel.llm.base import ToolCall
from lingtai.kernel.loop_guard import LoopGuard
from lingtai.kernel.risky_action_gate import (
    build_risky_action_check,
    expire_pending,
    load_gate_config,
    mark_approval,
)
from lingtai.kernel.tool_call_guard import ToolCallGuard, ToolProposal
from lingtai.kernel.tool_executor import ToolExecutor


def _proposal(tool_name: str, args: dict) -> ToolProposal:
    return ToolProposal(tool_name=tool_name, tool_args=args, tool_call_id="tc-1")


def _file_config(root, *, local_write_roots=None):
    security = root / ".security"
    security.mkdir(parents=True, exist_ok=True)
    (security / "gate_config.json").write_text(
        json.dumps({"local_write_roots": local_write_roots or []}),
        encoding="utf-8",
    )


def test_gate_is_zero_behavior_change_without_opt_in(tmp_path):
    check = build_risky_action_check(tmp_path)

    decision = check(_proposal("file", {"action": "write", "input": {
        "file_path": str(tmp_path / "outside.txt"), "content": "x"
    }}))

    assert decision.allowed
    assert not (tmp_path / ".security").exists()


def test_executor_blocks_before_dispatch_when_gate_denies(tmp_path):
    _file_config(tmp_path)
    dispatched = []
    executor = ToolExecutor(
        dispatch_fn=lambda tool_call: dispatched.append(tool_call) or {"status": "ok"},
        make_tool_result_fn=lambda name, result, **kwargs: {"name": name, "result": result},
        guard=LoopGuard(max_total_calls=10),
        known_tools={"file"},
        working_dir=tmp_path,
        tool_call_guard=ToolCallGuard([build_risky_action_check(tmp_path)]),
    )
    results, intercepted, _ = executor.execute([ToolCall(
        name="file",
        args={"action": "write", "input": {
            "file_path": str(tmp_path / "outside.txt"), "content": "x"
        }},
        id="blocked-file",
    )])

    assert not intercepted
    assert dispatched == []
    assert results[0]["result"]["error_type"] == "ToolCallGuardDenied"
    assert results[0]["result"]["guard_decision"]["metadata"]["pending_request_id"]


def test_file_write_outside_allowlist_is_denied_and_recorded(tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    _file_config(tmp_path, local_write_roots=[str(allowed)])
    check = build_risky_action_check(tmp_path)

    proposal = _proposal("file", {"action": "write", "input": {
        "file_path": str(tmp_path / "outside.txt"), "content": "exact content"
    }})
    decision = check(proposal)

    assert not decision.allowed
    assert decision.check_name == "risky_action_gate"
    request_id = decision.metadata["pending_request_id"]
    request_path = tmp_path / ".security" / "pending" / f"{request_id}.json"
    payload = json.loads(request_path.read_text(encoding="utf-8"))
    assert payload["status"] == "pending"
    assert payload["approvals"] == {"telegram": None, "wechat": None}
    assert payload["operation"]["tool_name"] == "file"
    assert payload["operation"]["args"] == proposal.tool_args
    assert not (tmp_path / "outside.txt").exists()


def test_allowlisted_file_write_and_read_only_shell_pass(tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    _file_config(tmp_path, local_write_roots=[str(allowed)])
    check = build_risky_action_check(tmp_path)

    file_decision = check(_proposal("file", {"action": "edit", "input": {
        "file_path": str(allowed / "x.txt"), "old_string": "a",
        "new_string": "b", "replace_all": False,
    }}))
    shell_decision = check(_proposal("shell", {"action": "run", "input": {
        "command": "printf hello", "working_dir": None,
        "timeout": None, "async": False, "reminder": None,
    }}))

    assert file_decision.allowed
    assert shell_decision.allowed
    assert not list((tmp_path / ".security" / "pending").glob("*.json"))


def test_shell_unknown_command_is_denied_and_exact_command_is_recorded(tmp_path):
    _file_config(tmp_path)
    check = build_risky_action_check(tmp_path)
    command = "python3 -c 'open(\"outside.txt\", \"w\").write(\"x\")'"
    proposal = _proposal("shell", {"action": "run", "input": {
        "command": command, "working_dir": str(tmp_path),
        "timeout": None, "async": False, "reminder": None,
    }})

    decision = check(proposal)

    assert not decision.allowed
    request_path = tmp_path / ".security" / "pending" / f"{decision.metadata['pending_request_id']}.json"
    payload = json.loads(request_path.read_text(encoding="utf-8"))
    assert payload["operation"]["command"] == command
    assert payload["operation"]["args"] == proposal.tool_args
    assert not (tmp_path / "outside.txt").exists()


def test_expired_request_is_denied_even_if_approval_arrives_later(tmp_path):
    _file_config(tmp_path)
    decision = build_risky_action_check(tmp_path)(_proposal("shell", {
        "action": "run", "input": {"command": "rm -f x"}
    }))
    request_path = tmp_path / ".security" / "pending" / f"{decision.metadata['pending_request_id']}.json"
    payload = json.loads(request_path.read_text(encoding="utf-8"))
    payload["created_at"] = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    request_path.write_text(json.dumps(payload), encoding="utf-8")

    assert expire_pending(request_path)["status"] == "expired"
    assert mark_approval(request_path, "telegram", "approve")["status"] == "expired"


def test_shared_config_grants_are_unioned_and_two_approvals_transition_status(tmp_path):
    agent = tmp_path / "agent"
    shared = tmp_path / "shared"
    (agent / ".security").mkdir(parents=True)
    (shared / ".security").mkdir(parents=True)
    (agent / ".security" / "gate_config.json").write_text("{}", encoding="utf-8")
    (shared / ".security" / "gate_config.json").write_text(
        json.dumps({"local_write_roots": [str(agent / "shared-ok")], "ssh_hosts": ["cluster"]}),
        encoding="utf-8",
    )
    config = load_gate_config(agent)
    assert config["local_write_roots"] == [str(agent / "shared-ok")]
    assert config["ssh_hosts"] == ["cluster"]

    check = build_risky_action_check(agent)
    proposal = _proposal("file", {"action": "write", "input": {
        "file_path": str(agent / "not-ok.txt"), "content": "x"
    }})
    decision = check(proposal)
    request_path = agent / ".security" / "pending" / f"{decision.metadata['pending_request_id']}.json"
    assert mark_approval(request_path, "telegram", "approve")["status"] == "pending"
    assert mark_approval(request_path, "wechat", "approve")["status"] == "approved"


def test_glued_redirection_is_denied(tmp_path):
    """`printf pwn>/tmp/x` must not be unwrapped into read-only printf."""
    _file_config(tmp_path)
    decision = build_risky_action_check(tmp_path)(_proposal("shell", {
        "action": "run", "input": {"command": "printf pwn>/tmp/x"}
    }))
    assert not decision.allowed


def test_glued_append_redirection_is_denied(tmp_path):
    _file_config(tmp_path)
    decision = build_risky_action_check(tmp_path)(_proposal("shell", {
        "action": "run", "input": {"command": "echo hi >>/tmp/x"}
    }))
    assert not decision.allowed


def test_path_form_executable_is_denied(tmp_path):
    """`./ls` must not be trusted as the read-only system ``ls``."""
    _file_config(tmp_path)
    decision = build_risky_action_check(tmp_path)(_proposal("shell", {
        "action": "run", "input": {"command": "./ls"}
    }))
    assert not decision.allowed


def test_env_path_override_is_denied(tmp_path):
    """`env PATH=/attacker ls` must not unwrap into read-only ls."""
    _file_config(tmp_path)
    for command in (
        "env PATH=/attacker ls",
        "env LD_PRELOAD=/attacker.so ls",
        "env PYTHONPATH=/attacker python3 -c pass",
    ):
        decision = build_risky_action_check(tmp_path)(_proposal("shell", {
            "action": "run", "input": {"command": command}
        }))
        assert not decision.allowed, command


def test_git_list_only_subcommands_reject_positional_mutation(tmp_path):
    _file_config(tmp_path)
    for command in ("git branch pwn", "git tag v1", "git remote add x y"):
        decision = build_risky_action_check(tmp_path)(_proposal("shell", {
            "action": "run", "input": {"command": command}
        }))
        assert not decision.allowed, command
    # Bare list/query forms stay allowed.
    for command in ("git branch", "git tag", "git remote -v", "git status", "git log -1"):
        decision = build_risky_action_check(tmp_path)(_proposal("shell", {
            "action": "run", "input": {"command": command}
        }))
        assert decision.allowed, command


def test_read_only_verb_with_write_flag_is_denied(tmp_path):
    _file_config(tmp_path)
    for command in ("sort -o /tmp/x input", "curl -o /tmp/x https://example.com", "wget -O /tmp/x https://example.com"):
        decision = build_risky_action_check(tmp_path)(_proposal("shell", {
            "action": "run", "input": {"command": command}
        }))
        assert not decision.allowed, command


def test_bash_compat_name_is_treated_as_shell(tmp_path):
    """A compat ``bash`` tool call must hit the same shell gate as ``shell``."""
    _file_config(tmp_path)
    decision = build_risky_action_check(tmp_path)(_proposal("bash", {
        "action": "run", "input": {"command": "rm -f x"}
    }))
    assert not decision.allowed


def test_daemon_stub_wires_risky_action_gate(tmp_path):
    """Detached daemon stub must not bypass an opted-in gate."""
    _file_config(tmp_path)
    from lingtai.kernel.daemon_supervisor.agent_stub import DaemonSupervisorAgentStub
    stub = DaemonSupervisorAgentStub(tmp_path)
    assert stub._tool_call_guard is not None
    decision = stub._tool_call_guard.evaluate(_proposal("shell", {
        "action": "run", "input": {"command": "rm -f x"}
    }))
    assert not decision.allowed


def test_mark_approval_refuses_expired_inline(tmp_path):
    """mark_approval itself must refuse an already-expired pending request."""
    _file_config(tmp_path)
    decision = build_risky_action_check(tmp_path)(_proposal("shell", {
        "action": "run", "input": {"command": "rm -f x"}
    }))
    request_path = tmp_path / ".security" / "pending" / f"{decision.metadata['pending_request_id']}.json"
    payload = json.loads(request_path.read_text(encoding="utf-8"))
    payload["created_at"] = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    request_path.write_text(json.dumps(payload), encoding="utf-8")
    result = mark_approval(request_path, "telegram", "approve")
    assert result["status"] == "expired"
    assert request_path.read_text(encoding="utf-8") != ""
