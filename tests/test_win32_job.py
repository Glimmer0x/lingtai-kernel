"""PR-B2: Windows Job Object tree-kill helper and bounded io drain.

The shell capability's Windows sync path previously killed only the direct
child on timeout and then let ``subprocess.run`` block on a second
``communicate()`` until EOF — a grandchild that inherited the pipe write ends
hung the caller forever (Goose PR #7689; Codex ``io_drain_timeout``).  These
tests pin the Job Object containment helper (``win32_job``) — the Codex
``process_group``/``win/job.rs`` pattern — and its sync-path wiring into
``ShellManager._run_sync``.  Every mechanism boundary is monkeypatched, so the
tests run on every platform; native behavior is exercised by the
Windows-latest workflow.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from lingtai.adapters.windows import win32_job
from lingtai.tools.bash import ShellManager, ShellPolicy
from lingtai.tools.bash._shell_dialect import ShellInvocation


@pytest.fixture(autouse=True)
def _bypass_windows_guard(monkeypatch):
    """Fake-mechanism tests bypass the Windows guard; the guard itself is
    pinned by ``test_win32_job_helpers_raise_outside_windows``."""
    monkeypatch.setattr(win32_job, "_require_windows", lambda: None)


_REAL_REQUIRE_WINDOWS = win32_job._require_windows


# ---------------------------------------------------------------------------
# Platform guard and ctypes argument construction
# ---------------------------------------------------------------------------


def test_win32_job_imports_safely_on_every_platform():
    assert win32_job.CONTAINED_CREATIONFLAGS & win32_job.CREATE_SUSPENDED


def test_win32_job_helpers_raise_outside_windows(monkeypatch):
    monkeypatch.setattr(win32_job.os, "name", "posix")
    monkeypatch.setattr(win32_job, "_require_windows", _REAL_REQUIRE_WINDOWS)
    with pytest.raises(OSError, match="requires Windows"):
        win32_job.create_job_handle()
    with pytest.raises(OSError, match="requires Windows"):
        win32_job.spawn_into_job(["echo"], {})
    with pytest.raises(OSError, match="requires Windows"):
        win32_job.terminate_job(1)
    with pytest.raises(OSError, match="requires Windows"):
        win32_job.wait_job_empty(1, 0.0)


def test_extended_limit_info_pins_kill_on_close_plus_breakaway_flags():
    info = win32_job._extended_limit_info(
        win32_job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        | win32_job.JOB_OBJECT_LIMIT_BREAKAWAY_OK
    )
    assert info.BasicLimitInformation.LimitFlags == 0x3000
    assert win32_job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE == 0x2000
    assert win32_job.JOB_OBJECT_LIMIT_BREAKAWAY_OK == 0x1000


# ---------------------------------------------------------------------------
# create_job_handle
# ---------------------------------------------------------------------------


class _RecordingKernel:
    """Fake kernel32: records calls, returns configured results, defaults truthy."""

    def __init__(self, **defaults):
        self.calls: list[tuple[str, tuple]] = []
        self._defaults = defaults

    def __getattr__(self, name):
        def _call(*args):
            self.calls.append((name, args))
            return self._defaults.get(name, 1)

        return _call


@pytest.fixture
def kernel(monkeypatch):
    fake = _RecordingKernel(CreateJobObjectW=7, OpenProcess=13)
    monkeypatch.setattr(win32_job, "_kernel32", lambda: fake)
    return fake


def test_create_job_handle_sets_kill_on_close_and_breakaway(kernel, monkeypatch):
    set_calls = []
    monkeypatch.setattr(
        win32_job, "_set_limit_flags",
        lambda handle, flags: set_calls.append((handle, flags)),
    )
    job = win32_job.create_job_handle()
    assert job == 7
    assert kernel.calls[0][0] == "CreateJobObjectW"
    # The exact flags the Job Object is configured with (Codex win/job.rs):
    assert set_calls == [(7, 0x3000)]


def test_create_job_handle_closes_handle_when_limit_config_fails(kernel, monkeypatch):
    monkeypatch.setattr(
        win32_job, "_set_limit_flags", lambda handle, flags: (_ for _ in ()).throw(OSError(5, "boom"))
    )
    with pytest.raises(OSError):
        win32_job.create_job_handle()
    assert ("CloseHandle", (7,)) in kernel.calls


# ---------------------------------------------------------------------------
# spawn_into_job: suspended spawn -> assign -> resume
# ---------------------------------------------------------------------------


class _FakePopen:
    def __init__(self, pid=42, handle=11):
        self.pid = pid
        self._handle = handle
        self.killed = False
        self.waited = False

    def kill(self):
        self.killed = True

    def wait(self, timeout=None):
        self.waited = True
        return 0


def test_spawn_into_job_spawns_suspended_assigns_then_resumes(monkeypatch, kernel):
    fake_popen = _FakePopen()
    spawn_calls = []
    monkeypatch.setattr(
        win32_job.subprocess, "Popen",
        lambda *args, **kwargs: spawn_calls.append(kwargs) or fake_popen,
    )
    resume_calls = []
    ntdll = _RecordingKernel()
    monkeypatch.setattr(win32_job, "_ntdll", lambda: ntdll)

    process, job = win32_job.spawn_into_job(["pwsh", "-Command", "x"], {"text": True})
    assert process is fake_popen
    assert job == 7
    assert spawn_calls[0]["creationflags"] & win32_job.CREATE_SUSPENDED
    assert spawn_calls[0]["creationflags"] & win32_job.CREATE_NO_WINDOW
    assert spawn_calls[0]["creationflags"] & win32_job.CREATE_NEW_PROCESS_GROUP
    # Sequence: job created -> limit flags -> process opened -> assigned -> resumed.
    names = [call[0] for call in kernel.calls]
    assert names == [
        "CreateJobObjectW",
        "SetInformationJobObject",
        "OpenProcess",
        "AssignProcessToJobObject",
        "CloseHandle",
    ]
    assert [call[0] for call in ntdll.calls] == ["NtResumeProcess"]
    assert ntdll.calls[0][1] == (11,)
    # OpenProcess access = SET_QUOTA | TERMINATE | QUERY_LIMITED_INFORMATION.
    assert kernel.calls[2][1] == (0x1101, False, 42)


def test_spawn_into_job_cleans_up_when_resume_fails(monkeypatch, kernel):
    fake_popen = _FakePopen()
    monkeypatch.setattr(win32_job.subprocess, "Popen", lambda *a, **k: fake_popen)
    ntdll = _RecordingKernel(NtResumeProcess=-1)
    monkeypatch.setattr(win32_job, "_ntdll", lambda: ntdll)

    with pytest.raises(OSError, match="NtResumeProcess"):
        win32_job.spawn_into_job(["pwsh"], {})
    assert ("TerminateJobObject", (7, 1)) in kernel.calls
    assert fake_popen.killed and fake_popen.waited


# ---------------------------------------------------------------------------
# terminate_owned_tree: job kill with taskkill fallback
# ---------------------------------------------------------------------------


def test_terminate_owned_tree_job_kill_is_primary(monkeypatch, kernel):
    calls = []
    monkeypatch.setattr(win32_job, "taskkill_tree_best_effort", lambda pid: calls.append(pid))
    assert win32_job.terminate_owned_tree(7, 42) is True
    assert ("TerminateJobObject", (7, 1)) in kernel.calls
    assert calls == []


def test_terminate_owned_tree_falls_back_to_taskkill(monkeypatch, kernel):
    kernel._defaults["TerminateJobObject"] = 0
    taskkill = []
    monkeypatch.setattr(win32_job, "taskkill_tree_best_effort", lambda pid: taskkill.append(pid))
    assert win32_job.terminate_owned_tree(7, 42) is False
    assert taskkill == [42]


def test_taskkill_fallback_invokes_hidden_tree_kill(monkeypatch):
    calls = []
    monkeypatch.setattr(
        win32_job.subprocess, "run",
        lambda *args, **kwargs: calls.append((args, kwargs)) or SimpleNamespace(returncode=0),
    )
    win32_job.taskkill_tree_best_effort(42)
    argv, kwargs = calls[0]
    assert argv[0] == ["taskkill", "/PID", "42", "/T", "/F"]
    assert kwargs["creationflags"] == win32_job.CREATE_NO_WINDOW
    assert kwargs["timeout"] == 10.0
    assert kwargs["stdin"] is subprocess.DEVNULL


def test_taskkill_fallback_is_safe_noop_when_unavailable(monkeypatch):
    def boom(*args, **kwargs):
        raise FileNotFoundError("taskkill")

    monkeypatch.setattr(win32_job.subprocess, "run", boom)
    win32_job.taskkill_tree_best_effort(42)  # must not raise
    win32_job.taskkill_tree_best_effort(0)  # pid guard


# ---------------------------------------------------------------------------
# drain_pipes: bounded post-kill io drain
# ---------------------------------------------------------------------------


class _FakeStream:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class _FakeProcess:
    def __init__(self, communicate_result):
        self._communicate_result = communicate_result
        self.stdout = _FakeStream()
        self.stderr = _FakeStream()

    def communicate(self, timeout=None):
        raise self._communicate_result


def test_drain_pipes_returns_partial_output_and_closes_streams_on_timeout():
    exc = subprocess.TimeoutExpired(cmd="pwsh", timeout=0.5, output="partial-out", stderr="partial-err")
    process = _FakeProcess(exc)
    stdout, stderr = win32_job.drain_pipes(process, 0.5)
    assert stdout == "partial-out"
    assert stderr == "partial-err"
    assert process.stdout.closed and process.stderr.closed


def test_drain_pipes_passes_full_output_when_eof_arrives(monkeypatch):
    process = _FakeProcess(None)
    monkeypatch.setattr(process, "communicate", lambda timeout=None: ("out", "err"))
    assert win32_job.drain_pipes(process, 0.5) == ("out", "err")
    assert not process.stdout.closed


def test_wait_job_empty_polls_active_count(monkeypatch):
    counts = iter([2, 1, 0])
    monkeypatch.setattr(win32_job, "job_active_processes", lambda handle: next(counts))
    monkeypatch.setattr(win32_job.time, "sleep", lambda seconds: None)
    assert win32_job.wait_job_empty(7, 1.0) is True


def test_wait_job_empty_times_out(monkeypatch):
    monkeypatch.setattr(win32_job, "job_active_processes", lambda handle: 1)
    monkeypatch.setattr(win32_job.time, "sleep", lambda seconds: None)
    assert win32_job.wait_job_empty(7, 0.0) is False


# ---------------------------------------------------------------------------
# Wiring into ShellManager._run_sync (Windows sync path)
# ---------------------------------------------------------------------------


class _NotificationSink:
    """Small no-I/O notification Port sufficient for ShellManager construction."""

    def publish(self, channel: str, payload: dict) -> None:
        return None

    def compare_update_channel(self, channel, expected_version, mutator):
        _payload, _changed, value = mutator({})
        return SimpleNamespace(value=value)


def _manager(tmp_path: Path) -> ShellManager:
    agent = SimpleNamespace(_notification_store=_NotificationSink())
    return ShellManager(
        policy=ShellPolicy.yolo(),
        working_dir=str(tmp_path),
        agent=agent,
    )


class _SyncProcess:
    def __init__(self, result):
        self._result = result
        self.pid = 4242

    def communicate(self, timeout=None):
        raise self._result


def test_sync_timeout_kills_whole_tree_and_drains_boundedly(monkeypatch, tmp_path):
    import lingtai.tools.bash as bash_module

    monkeypatch.setattr(bash_module, "_sync_run_contained", lambda: True)
    process = _SyncProcess(subprocess.TimeoutExpired(cmd="pwsh", timeout=5, output="p", stderr="e"))
    events = []
    monkeypatch.setattr(
        win32_job, "spawn_into_job",
        lambda args, kwargs: events.append(("spawn", args, kwargs)) or (process, 99),
    )
    monkeypatch.setattr(
        win32_job, "terminate_owned_tree",
        lambda job, pid: events.append(("terminate", job, pid)),
    )
    monkeypatch.setattr(
        win32_job, "drain_pipes",
        lambda proc, timeout: events.append(("drain", timeout)) or ("p", "e"),
    )
    monkeypatch.setattr(win32_job, "close_handle", lambda handle: events.append(("close", handle)))

    manager = _manager(tmp_path)
    result = manager._run_sync(
        "sleep 100", str(tmp_path), 5.0, ShellInvocation(script="sleep 100")
    )
    assert result == {"status": "error", "message": "Command timed out after 5.0s"}
    assert events[0][0] == "spawn"
    assert events[1] == ("terminate", 99, 4242)
    assert events[2] == ("drain", win32_job.IO_DRAIN_TIMEOUT_SECONDS)
    assert events[3] == ("close", 99)


def test_sync_success_caps_output(monkeypatch, tmp_path):
    import lingtai.tools.bash as bash_module

    monkeypatch.setattr(bash_module, "_sync_run_contained", lambda: True)

    class _OkProcess:
        pid = 7
        returncode = 0

        def communicate(self, timeout=None):
            return "x" * 60_000, ""

    events = []
    monkeypatch.setattr(win32_job, "spawn_into_job", lambda args, kwargs: (_OkProcess(), 5))
    monkeypatch.setattr(win32_job, "close_handle", lambda handle: events.append(("close", handle)))

    manager = _manager(tmp_path)
    result = manager._run_sync(
        "echo hi", str(tmp_path), 30.0,
        ShellInvocation(script="echo hi", encoding="utf-8"),
    )
    assert result["status"] == "ok"
    assert result["exit_code"] == 0
    assert result["ok"] is True and result["command_status"] == "success"
    assert result["stdout"].endswith("... (truncated, 60000 chars total)")
    assert events == [("close", 5)]


def test_sync_falls_back_to_plain_run_when_job_unavailable(monkeypatch, tmp_path):
    import lingtai.tools.bash as bash_module

    monkeypatch.setattr(bash_module, "_sync_run_contained", lambda: True)
    monkeypatch.setattr(win32_job, "spawn_into_job", lambda args, kwargs: (_ for _ in ()).throw(OSError(5, "job policy")))
    run_calls = []
    monkeypatch.setattr(
        bash_module.subprocess, "run",
        lambda *args, **kwargs: run_calls.append(kwargs)
        or SimpleNamespace(stdout="plain", stderr="", returncode=0),
    )

    manager = _manager(tmp_path)
    result = manager._run_sync(
        "echo hi", str(tmp_path), 30.0, ShellInvocation(script="echo hi")
    )
    assert result["status"] == "ok"
    assert result["stdout"] == "plain"
    assert run_calls[0]["timeout"] == 30.0
    assert run_calls[0]["capture_output"] is True
