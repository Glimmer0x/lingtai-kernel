"""Regression: MCPClient.close() must terminate the subprocess tree.

On POSIX, stopping the asyncio loop closes the stdio pipes and the child
receives EOF on stdin, which exits it. On Windows that is not reliable: a
venv launcher shim spawns a real interpreter as a child that survives,
so every boot/refresh/molt respawn leaked another stdio pair (duplicate
telegram listeners etc). close() now captures the child tree after start
and explicitly terminates it.
"""
import os
import subprocess
import sys
import time

import pytest

from lingtai.services.mcp import (
    MCPClient,
    _snapshot_process_table,
)


FAKE_SERVER = r"""
import sys, time
# Simulates a server that does NOT exit on stdin EOF (the Windows leak case).
while True:
    try:
        data = sys.stdin.buffer.read(1)
    except Exception:
        break
    if not data:
        time.sleep(3600)
"""


@pytest.fixture
def fake_server_script(tmp_path):
    path = tmp_path / "fake_server_keepalive.py"
    path.write_text(FAKE_SERVER, encoding="utf-8")
    return str(path)


def _pids_still_alive(pids):
    table = _snapshot_process_table()
    present = {r["pid"] for r in table}
    return [pid for pid in pids if pid in present]


def test_close_terminates_subprocess_tree(fake_server_script):
    marker = "keepalive_marker_%d" % os.getpid()
    client = MCPClient(command=sys.executable, args=[fake_server_script, marker])
    client.start()
    client._capture_child_pids()

    assert client._child_pids, "expected at least one captured child process"
    assert _pids_still_alive(client._child_pids), "child should be alive after start"

    client.close()
    time.sleep(0.5)

    still = _pids_still_alive(client._child_pids)
    assert not still, f"close() leaked subprocesses: {still}"


def test_name_identity_derived_from_command(fake_server_script):
    client = MCPClient(command=sys.executable, args=[fake_server_script])
    assert client.name
    assert "fake_server_keepalive" in client.name


def test_dedup_identity_detects_same_server(fake_server_script):
    c1 = MCPClient(command=sys.executable, args=[fake_server_script, "dedup_a"])
    c2 = MCPClient(command=sys.executable, args=[fake_server_script, "dedup_a"])
    assert c1.name == c2.name
    c1.close()
    c2.close()
