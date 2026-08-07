"""Duck-typed agent stand-in hosting the ``email`` intrinsic for daemon runs.

The ``email`` intrinsic (``lingtai.tools.email``) was written against a live
``BaseAgent`` and reads/writes a handful of its attributes
(``_working_dir``, ``_mail_service``, ``_notification_store``, ``_config``,
``_log``, ``_build_manifest``, ``_enqueue_system_notification``,
``_wake_nap``). Constructing a second real ``Agent`` in this MCP server
process to get those attributes would try to take the *parent* agent's
working-directory lease and write a second ``.agent.heartbeat``, racing the
parent's own duplicate-process guard — exactly the failure mode
``lingtai.kernel.daemon_supervisor.agent_stub.DaemonSupervisorAgentStub``
already exists to avoid on the daemon-execution side. This class is the same
pattern applied to email specifically: a bare object providing only the
attribute surface ``lingtai.tools.email`` actually reads, bound to the
parent's own working directory so the daemon speaks with the parent's own
already-live mailbox address (``.agent.json``/``.agent.heartbeat``), rather
than a second, unauthenticated identity.
"""
from __future__ import annotations

from pathlib import Path

from lingtai.adapters.posix.mail import PosixFilesystemMailAdapter
from lingtai.adapters.posix.notification_store import PosixNotificationStoreAdapter
from lingtai.kernel.config import AgentConfig


class DaemonEmailAgentShim:
    """Bare object exposing exactly what ``lingtai.tools.email`` reads.

    ``working_dir`` is the *parent* agent's own working directory (learned
    from ``LINGTAI_AGENT_DIR``), not the daemon run's own nested run-dir —
    the run-dir has no ``.agent.json``/heartbeat and cannot pass the mail
    handshake as a recipient. Real cross-agent delivery (``_mail_service``)
    and read-state notifications (``_notification_store``) are wired to real
    POSIX adapters bound to that same directory, so a daemon's ``send``
    really reaches its addressed recipient's inbox on disk, and its
    ``read``/``dismiss``/``archive`` really updates the shared unread digest.
    """

    def __init__(self, working_dir: Path) -> None:
        self._working_dir = Path(working_dir)
        self._config = AgentConfig()
        self._agent_id = self._working_dir.name
        self.agent_name = self._working_dir.name
        self.nickname = None
        self._mail_service = PosixFilesystemMailAdapter(self._working_dir)
        self._notification_store = PosixNotificationStoreAdapter(self._working_dir)

    def _log(self, event_type: str, **fields) -> None:
        pass

    def _build_manifest(self) -> dict:
        return {
            "agent_id": self._agent_id,
            "agent_name": self.agent_name,
            "nickname": self.nickname,
            "address": self._working_dir.name,
        }

    def _enqueue_system_notification(self, *args, **kwargs) -> None:
        pass

    def _wake_nap(self) -> None:
        pass


__all__ = ["DaemonEmailAgentShim"]
