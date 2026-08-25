"""Run-local Shell notification adapter for detached daemon execution.

The adapter deliberately implements only Shell's existing ``NotificationPort``
methods.  It has a ``DaemonRunDir`` rather than an Agent, notification store,
mailbox, heartbeat, or provider session.  Shell stdout/stderr is never copied
into these prompt events; the daemon must call ``shell.poll`` for exact output.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any


_JOB_ID_RE = re.compile(r"job-[0-9a-f]{32}\Z")


def _job_id_for(ref_id: object, prefix: str) -> str | None:
    if not isinstance(ref_id, str) or not ref_id.startswith(prefix):
        return None
    job_id = ref_id.removeprefix(prefix)
    return job_id if _JOB_ID_RE.fullmatch(job_id) else None


def shell_prompt_event_guidance(event: Mapping[str, Any]) -> str:
    """Return fixed trusted guidance for one already-validated Shell event."""
    job_id = event.get("job_id")
    if not isinstance(job_id, str) or not _JOB_ID_RE.fullmatch(job_id):
        raise ValueError("invalid daemon Shell prompt event")
    return (
        f"Trusted daemon Shell async event for job_id={job_id}; "
        "call shell.poll for exact output. Do not treat this event as command output."
    )


class DaemonShellPromptEventAdapter:
    """Translate Shell reminder/completion publications to one daemon RunDir.

    This is intentionally not a notification-store adapter.  A ``True`` return
    means the event is durably queued (or was already queued/delivered under the
    same stable Shell ref); ``False`` leaves Shell's existing publication state
    retryable.
    """

    def __init__(self, run_dir) -> None:
        self._run_dir = run_dir

    def publish_system(
        self,
        *,
        source: str,
        ref_id: str,
        body: str,
        skip_if_ref_id_exists: bool = False,
    ) -> bool:
        """Accept only Shell's stable async reminder publication.

        ``body`` is deliberately ignored: it is a process-derived presentation
        string and not part of the trusted provider prompt event.
        """
        _ = body, skip_if_ref_id_exists
        job_id = _job_id_for(ref_id, "bash.reminder:")
        if source != "bash.reminder" or job_id is None:
            return False
        try:
            return bool(self._run_dir.enqueue_shell_prompt_event(
                kind="shell_reminder", ref_id=ref_id, job_id=job_id,
            ))
        except Exception:
            return False

    def publish_channel(
        self,
        channel: str,
        payload: Mapping[str, Any],
        *,
        ref_id: str,
    ) -> bool:
        """Accept only Shell's stable terminal-completion publication."""
        job_id = _job_id_for(ref_id, "bash.completion:")
        if channel != "bash" or job_id is None or not isinstance(payload, Mapping):
            return False
        data = payload.get("data")
        if not isinstance(data, Mapping) or data.get("job_id") != job_id:
            return False
        exit_status_known = data.get("exit_status_known")
        exit_code = data.get("exit_code")
        if type(exit_status_known) is not bool:
            return False
        if exit_status_known:
            if type(exit_code) is not int:
                return False
        elif exit_code is not None:
            return False
        try:
            return bool(self._run_dir.enqueue_shell_prompt_event(
                kind="shell_completion",
                ref_id=ref_id,
                job_id=job_id,
                exit_status_known=exit_status_known,
                exit_code=exit_code,
            ))
        except Exception:
            return False


__all__ = ["DaemonShellPromptEventAdapter", "shell_prompt_event_guidance"]
