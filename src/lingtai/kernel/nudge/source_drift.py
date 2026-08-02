"""Nudge: warn the agent when on-disk source has drifted since startup.

A long-running packaged agent process may have imported old code before a new
kernel package landed on disk.  This nudge re-runs the same dual fingerprint
that was captured at startup (git rev + source digest) and compares with
``agent._runtime_fingerprint``.  When the two disagree, the running interpreter
is stale: only a full process relaunch (``system(action='refresh')``) picks up
new code.

Editable/source/dev installs are intentionally included. This producer is an
integrity/diagnostic channel: it reports that the running interpreter's startup
fingerprint differs from current on-disk source, without classifying that fact
as a package update or suppressing it under the release-version dev policy.

Throttled to one check per 60 seconds so a long-running agent doesn't get a
flood of nudge entries on every heartbeat tick. If the on-disk state returns to
match the startup fingerprint (revert, or stale state from a prior process), the
previously-emitted entry is cleared.
"""
from __future__ import annotations

import time

from .prompts import NudgeFacts, NudgeSituation, render_nudge_payload

_INTERVAL_SECONDS = 60.0
_KIND = "source_drift"


def check(agent) -> None:
    """Check for source-level drift between startup and on-disk code."""
    state = _state(agent)
    now = time.time()
    if now - state.get("last_probe_ts", 0.0) < _INTERVAL_SECONDS:
        return
    state["last_probe_ts"] = now

    from . import upsert, remove

    from ..base_agent.lifecycle import _capture_runtime_fingerprint

    startup_fp = getattr(agent, "_runtime_fingerprint", None)
    if not isinstance(startup_fp, dict):
        return  # no startup fingerprint — nothing to compare

    try:
        disk_fp = _capture_runtime_fingerprint(agent._source_revision_port)
    except Exception:
        return

    # Compare the two fingerprints
    drift_signals: list[str] = []

    startup_git = startup_fp.get("git_rev")
    disk_git = disk_fp.get("git_rev")
    if startup_git is not None and disk_git is not None and startup_git != disk_git:
        drift_signals.append(f"git_rev: {startup_git} → {disk_git}")

    startup_digest = startup_fp.get("source_digest")
    disk_digest = disk_fp.get("source_digest")
    if startup_digest is not None and disk_digest is not None and startup_digest != disk_digest:
        drift_signals.append(f"source_digest: {startup_digest} → {disk_digest}")

    if not drift_signals:
        # No drift — clear any prior nudge
        if state.get("emitted"):
            remove(agent, _KIND)
            state["emitted"] = False
        return

    # Drift detected. The central Nudge policy handles duplicate/dismissed
    # findings; this producer does not assign its own repeat cadence.
    drift_key = "; ".join(drift_signals)

    body = render_nudge_payload(
        NudgeSituation.SOURCE_DRIFT,
        NudgeFacts(
            startup_fingerprint=startup_fp,
            disk_fingerprint=disk_fp,
            drift_signals=tuple(drift_signals),
        ),
    )
    try:
        upsert(agent, _KIND, body)
        state["emitted"] = True
        state["emitted_for"] = drift_key
        agent._log(
            "nudge_emitted",
            kind=_KIND,
            drift_signals=drift_signals,
        )
    except Exception as e:
        agent._log("nudge_emit_error", kind=_KIND, error=str(e)[:200])


def _safe_log(agent, event: str, **fields) -> None:
    try:
        agent._log(event, **fields)
    except Exception:
        return


def _state(agent) -> dict:
    s = getattr(agent, "_nudge_source_drift_state", None)
    if s is None:
        s = {}
        agent._nudge_source_drift_state = s
    return s
