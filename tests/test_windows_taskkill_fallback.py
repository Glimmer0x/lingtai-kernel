"""PR-4: taskkill tree-kill fallback with creation-filetime identity re-check.

The Job Object adapter is the primary Windows tree-kill.  These tests pin the
fallback primitive (``_win32.taskkill_tree``) and its wiring into
``WindowsShellAsyncProcessAdapter.wait`` — the branches where the Job-Object
kill fails or a descendant escapes the job.  All mechanism boundaries are
monkeypatched, so the tests run on every platform.
"""
from __future__ import annotations

import subprocess
from types import SimpleNamespace

import pytest

from lingtai.adapters.windows import _win32
from lingtai.adapters.windows.powershell_process import (
    _Owned,
    WindowsShellAsyncProcessAdapter,
)
from lingtai.tools.bash._async_process import ProcessRef


@pytest.fixture
def _force_windows(monkeypatch):
    # Scope this to the primitive tests that actually exercise the
    # ``os.name != "nt"`` guard: patching the global ``os`` module attribute
    # for the whole file is a landmine for any future ``Path``/``os.name``
    # usage in the wiring path (pathlib's flavour selection is
    # ``os.name``-sensitive on 3.12).
    monkeypatch.setattr(_win32.os, "name", "nt")


def _matching_identity(pid: int) -> str:
    return f"windows:{pid}"


# ---------------------------------------------------------------------------
# _win32.taskkill_tree primitive
# ---------------------------------------------------------------------------


def test_taskkill_tree_requires_windows(monkeypatch):
    monkeypatch.setattr(_win32.os, "name", "posix")
    with pytest.raises(OSError, match="requires Windows"):
        _win32.taskkill_tree(123, "windows:1")


def test_taskkill_tree_refuses_without_captured_identity(_force_windows):
    assert _win32.taskkill_tree(123, None) is False
    assert _win32.taskkill_tree(123, "") is False


def test_taskkill_tree_refuses_recycled_pid_without_signaling(_force_windows, monkeypatch):
    monkeypatch.setattr(
        _win32, "process_creation_identity", lambda pid: "windows:999"
    )
    calls = []
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: calls.append(args) or SimpleNamespace(returncode=0),
    )
    assert _win32.taskkill_tree(123, "windows:1") is False
    assert calls == []


def test_taskkill_tree_invokes_taskkill_hidden_window_on_identity_match(_force_windows, monkeypatch):
    monkeypatch.setattr(
        _win32, "process_creation_identity", _matching_identity
    )
    calls = []
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: calls.append((args, kwargs)) or SimpleNamespace(returncode=0),
    )
    assert _win32.taskkill_tree(123, "windows:123") is True
    (argv, kwargs) = calls[0]
    assert argv[0] == ["taskkill", "/PID", "123", "/T", "/F"]
    assert kwargs["creationflags"] == _win32.CREATE_NO_WINDOW
    assert kwargs["stdin"] is subprocess.DEVNULL
    assert kwargs["timeout"] == 10


def test_taskkill_tree_reports_failure_on_nonzero_taskkill_exit(_force_windows, monkeypatch):
    monkeypatch.setattr(_win32, "process_creation_identity", _matching_identity)
    monkeypatch.setattr(
        subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=128)
    )
    assert _win32.taskkill_tree(123, "windows:123") is False


def test_taskkill_tree_reports_failure_when_taskkill_unavailable(_force_windows, monkeypatch):
    monkeypatch.setattr(_win32, "process_creation_identity", _matching_identity)

    def boom(*args, **kwargs):
        raise FileNotFoundError("taskkill")

    monkeypatch.setattr(subprocess, "run", boom)
    assert _win32.taskkill_tree(123, "windows:123") is False


# ---------------------------------------------------------------------------
# Wiring into WindowsShellAsyncProcessAdapter.wait
# ---------------------------------------------------------------------------


class _FakeProcess:
    def poll(self):
        return 0

    def wait(self):
        return 0


class _FakeKernel:
    def __init__(self, terminate_result: int):
        self.terminate_result = terminate_result

    def TerminateJobObject(self, handle, code):
        return self.terminate_result

    def CloseHandle(self, handle):
        return 1


def _record_fallback(calls):
    def taskkill_tree(pid, identity):
        calls.append((pid, identity))
        return True

    return taskkill_tree


def test_job_kill_failure_falls_back_to_taskkill_tree(monkeypatch):
    import lingtai.adapters.windows.powershell_process as process_adapter

    monkeypatch.setattr(process_adapter, "_kernel32", lambda: _FakeKernel(0))
    fallback = []
    monkeypatch.setattr(process_adapter, "taskkill_tree", _record_fallback(fallback))
    owned = _Owned(_FakeProcess(), ProcessRef(123, "windows:123"), object())
    completion = WindowsShellAsyncProcessAdapter().wait(owned, lambda: True)
    assert completion.cancellation_outcome == "unconfirmed"
    assert fallback == [(123, "windows:123")]


def test_escaped_child_falls_back_to_taskkill_tree(monkeypatch):
    import lingtai.adapters.windows.powershell_process as process_adapter

    monkeypatch.setattr(process_adapter, "_kernel32", lambda: _FakeKernel(1))
    monkeypatch.setattr(process_adapter, "_wait_job", lambda handle, timeout: False)
    fallback = []
    monkeypatch.setattr(process_adapter, "taskkill_tree", _record_fallback(fallback))
    owned = _Owned(_FakeProcess(), ProcessRef(456, "windows:456"), object())
    completion = WindowsShellAsyncProcessAdapter().wait(owned, lambda: True)
    assert completion.cancellation_outcome == "unconfirmed"
    assert fallback == [(456, "windows:456")]


def test_healthy_job_cancel_does_not_trigger_fallback(monkeypatch):
    import lingtai.adapters.windows.powershell_process as process_adapter

    monkeypatch.setattr(process_adapter, "_kernel32", lambda: _FakeKernel(1))
    monkeypatch.setattr(process_adapter, "_wait_job", lambda handle, timeout: True)
    fallback = []
    monkeypatch.setattr(process_adapter, "taskkill_tree", _record_fallback(fallback))
    owned = _Owned(_FakeProcess(), ProcessRef(789, "windows:789"), object())
    completion = WindowsShellAsyncProcessAdapter().wait(owned, lambda: True)
    assert completion.cancellation_outcome == "group_cancelled"
    assert fallback == []


def test_fallback_sweep_declined_root_survives_then_bounded_reap_commits(monkeypatch):
    """A fail-closed sweep leaves the root alive; the bounded reap must still
    commit once the root exits instead of blocking the supervisor forever.
    """
    import lingtai.adapters.windows.powershell_process as process_adapter

    class AliveThenExit:
        def __init__(self):
            self.calls = 0

        def poll(self):
            self.calls += 1
            return None if self.calls < 3 else 7

        def wait(self):
            return 7

    monkeypatch.setattr(process_adapter, "_kernel32", lambda: _FakeKernel(0))
    fallback = []
    monkeypatch.setattr(process_adapter, "taskkill_tree", _record_fallback(fallback))
    owned = _Owned(AliveThenExit(), ProcessRef(222, "windows:222"), object())
    completion = WindowsShellAsyncProcessAdapter().wait(owned, lambda: True)
    assert completion.exit_code == 7
    assert completion.cancellation_outcome == "unconfirmed"
    assert fallback == [(222, "windows:222")]
