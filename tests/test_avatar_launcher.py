"""Focused Contract tests for the avatar-local launcher boundary."""
import socket
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from lingtai.tools.avatar import AvatarManager
from lingtai.tools.avatar._launcher import AvatarLaunchReceipt, AvatarLaunchRequest
from lingtai.adapters.acp.driver_authority import DriverChildEndpointLease
from lingtai.adapters.posix.avatar_launcher import PosixAvatarLauncherAdapter


def test_posix_launch_contract_and_release(tmp_path):
    process = MagicMock(pid=417, poll=MagicMock(return_value=None))
    stderr = tmp_path / "logs" / "spawn.stderr"
    request = AvatarLaunchRequest(("python", "-m", "lingtai", "run", "/avatar"), stderr)
    with patch("lingtai.adapters.posix.avatar_launcher.subprocess.Popen", return_value=process) as popen:
        receipt = PosixAvatarLauncherAdapter().launch(request)
    assert receipt == AvatarLaunchReceipt(417, process)
    kwargs = popen.call_args.kwargs
    assert popen.call_args.args == (["python", "-m", "lingtai", "run", "/avatar"],)
    assert kwargs["stdin"] is __import__("subprocess").DEVNULL
    assert kwargs["stdout"] is __import__("subprocess").DEVNULL
    assert kwargs["start_new_session"] is True
    assert kwargs["stderr"].closed is True
    assert "cwd" not in kwargs
    assert "env" not in kwargs
    adapter = PosixAvatarLauncherAdapter()
    adapter.release(process)
    process.poll.assert_called_once()
    adapter.terminate(process)
    adapter.force_terminate(process)
    process.terminate.assert_called_once()
    process.kill.assert_called_once()


def test_posix_launch_propagates_explicit_derived_child_requirement(tmp_path):
    """A derived-avatar marker tightens child boot without carrying authority."""
    process = MagicMock(pid=418, poll=MagicMock(return_value=None))
    stderr = tmp_path / "logs" / "spawn.stderr"
    request = AvatarLaunchRequest(
        ("python", "-m", "lingtai", "run", "/avatar"),
        stderr,
        environment={"LINGTAI_DERIVED_AVATAR_EXECUTION": "1"},
    )
    with patch("lingtai.adapters.posix.avatar_launcher.subprocess.Popen", return_value=process) as popen:
        PosixAvatarLauncherAdapter().launch(request)
    assert popen.call_args.kwargs["env"]["LINGTAI_DERIVED_AVATAR_EXECUTION"] == "1"


def test_posix_launch_passes_only_the_one_shot_driver_child_endpoint(tmp_path):
    """The child gets a lease endpoint, never an inherited root descriptor."""
    process = MagicMock(pid=419, poll=MagicMock(return_value=None))
    client, driver = socket.socketpair()
    request = AvatarLaunchRequest(
        ("python", "-m", "lingtai", "run", "/avatar"),
        tmp_path / "logs" / "spawn.stderr",
        authority_lease=DriverChildEndpointLease(client),
    )
    try:
        with patch(
            "lingtai.adapters.posix.avatar_launcher.subprocess.Popen",
            return_value=process,
        ) as popen:
            PosixAvatarLauncherAdapter().launch(request)
        kwargs = popen.call_args.kwargs
        child_fd = kwargs["pass_fds"]
        assert len(child_fd) == 1
        assert kwargs["env"]["LINGTAI_DRIVER_AUTHORITY_FD"] == str(child_fd[0])
        assert kwargs["close_fds"] is True
    finally:
        driver.close()


def test_manager_marks_avatar_child_as_requiring_derived_authority(tmp_path):
    """The production avatar launch request carries no authority bearer."""
    launcher = MagicMock()
    launcher.launch.return_value = AvatarLaunchReceipt(419, object())
    manager = AvatarManager(SimpleNamespace(), launcher=launcher)
    with patch("lingtai.venv_resolve.resolve_venv", return_value=tmp_path), patch(
        "lingtai.venv_resolve.venv_python", return_value=tmp_path / "python"
    ):
        manager._launch(tmp_path)
    request = launcher.launch.call_args.args[0]
    assert request.environment == {"LINGTAI_DERIVED_AVATAR_EXECUTION": "1"}


def test_manager_boot_policy_uses_opaque_port_and_preserves_precedence(tmp_path):
    launcher = MagicMock()
    manager = AvatarManager(SimpleNamespace(), launcher=launcher)
    receipt = AvatarLaunchReceipt(123, object())
    launcher.poll.return_value = 37
    stderr = tmp_path / "spawn.stderr"
    stderr.write_bytes(b"x" * 3000)
    status, error = manager._wait_for_boot(tmp_path, receipt, stderr)
    assert status == "failed"
    assert error.startswith("process exited with code 37: ...[truncated]")
    assert launcher.poll.call_args.args == (receipt.handle,)

    launcher.reset_mock()
    (tmp_path / ".agent.heartbeat").write_text("now")
    launcher.poll.return_value = 99
    assert manager._wait_for_boot(tmp_path, receipt, stderr) == ("ok", None)
    launcher.poll.assert_not_called()  # heartbeat remains first observation


def test_manager_slow_observation_does_not_terminate_child(tmp_path):
    launcher = MagicMock()
    manager = AvatarManager(SimpleNamespace(), launcher=launcher)
    launcher.poll.return_value = None
    with patch("lingtai.tools.avatar.time.monotonic", side_effect=[0.0, 0.1, 5.0]), \
         patch("lingtai.tools.avatar.time.sleep") as sleep:
        assert manager._wait_for_boot(
            tmp_path, AvatarLaunchReceipt(1, "opaque"), tmp_path / "missing"
        ) == ("slow", None)
    launcher.poll.assert_called_once_with("opaque")
    sleep.assert_called_once_with(manager._BOOT_POLL_INTERVAL)
    launcher.terminate.assert_not_called()
    launcher.force_terminate.assert_not_called()


def test_selector_selects_posix_and_fails_loud_for_unsupported():
    from lingtai.adapters import avatar_launcher

    with patch.object(avatar_launcher.os, "name", "posix"), \
         patch.object(avatar_launcher.sys, "platform", "linux"):
        assert isinstance(avatar_launcher.select_avatar_launcher(), PosixAvatarLauncherAdapter)

    # ``nt`` is now a supported platform (Windows adapter) — its positive
    # selector assertion lives in tests/test_avatar_launcher_windows.py. Only a
    # genuinely unrecognized ``os.name`` still fails loudly here.
    for name, platform in (("other", "other"),):
        with patch.object(avatar_launcher.os, "name", name), \
             patch.object(avatar_launcher.sys, "platform", platform):
            try:
                avatar_launcher.select_avatar_launcher()
            except NotImplementedError as exc:
                assert "No production avatar launcher" in str(exc)
            else:
                raise AssertionError("unsupported platform must fail loudly")
