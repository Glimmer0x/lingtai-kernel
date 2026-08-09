"""Missing-finish failures must carry trace-inspection guidance.

Strict semantics are unchanged: a run that ends without calling finish()
while daemon_common MCP is loaded is still a failure. The failure message,
the daemon oneshot context, and the manual must tell the reader that
missing-finish is not by itself proof the task failed and to inspect the
run's trace/result.
"""

import json
from pathlib import Path

import pytest

from lingtai.tools.daemon import DaemonManager
from tests._daemon_helpers import make_daemon_agent, make_daemon_run_dir

_GUIDANCE = "does not necessarily mean the task failed"


def test_missing_finish_still_fails_and_message_directs_trace_inspection(tmp_path):
    agent = make_daemon_agent(tmp_path)
    mgr = agent.get_capability("daemon")
    run_dir = make_daemon_run_dir(
        agent,
        handle="em-missing-finish-guidance",
        call_parameters={"mcp": [{"name": "daemon_common", "transport": "stdio"}]},
    )

    with pytest.raises(RuntimeError, match="missing completion") as excinfo:
        mgr._require_done_completion(run_dir, "final text without finish")

    message = str(excinfo.value)
    assert _GUIDANCE in message
    assert "inspect the run's trace/result" in message

    state = json.loads(run_dir.daemon_json_path.read_text())
    assert state["state"] == "failed"

    # An explicit finish(failed) is the agent's own verdict — the
    # trace-inspection wording is reserved for the missing-finish case.
    (run_dir.path / "daemon_completion.json").write_text(
        json.dumps(
            {
                "schema": "lingtai.daemon_completion.v1",
                "status": "failed",
                "run_id": run_dir.run_id,
                "reason": "blocked",
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError) as explicit:
        mgr._require_done_completion(run_dir, "final text")
    assert _GUIDANCE not in str(explicit.value)


def test_daemon_context_and_manual_carry_missing_finish_guidance():
    context = DaemonManager._daemon_common_context()
    assert "missing-finish" in context
    assert "not proof of failure" in context

    manual = (
        Path(__file__).resolve().parents[1]
        / "src/lingtai/tools/daemon/manual/SKILL.md"
    ).read_text(encoding="utf-8")
    assert "missing-finish failure" in manual
    assert "inspect the run's trace/result" in manual
