"""Agent Record — the one atomic, versioned, redacted live personal record.

Every LingTai Agent (including avatars, which are ordinary ``Agent`` instances
bound to their own working directory) owns and publishes exactly one live
record describing itself: identity, model/provider, verified consumer-facing
handles, visible MCP integration labels, session/liveness, usage/context, and
a bounded aggregate of its own daemons' self-records.

This module is the sole writer/reader of that shape. Consumer surfaces (TUI,
``/kanban``, ``/details``, Telegram, Portal) read and curate this record; they
must not independently re-collect normal live state or scan daemon files to
reconstruct it (see the confirmed alignment: Telegram 14238/14242/14248).

Ownership split, mirroring the existing ``_build_manifest`` override pattern:

- Core (``BaseAgent``) builds the identity/session/health/usage/daemon blocks
  from data it already owns (state, lifecycle clock, token usage, heartbeat).
- The outer ``lingtai.Agent`` composition root overrides
  ``_build_agent_record_extra`` to add ``handles``/``integrations`` — Core
  knows nothing about MCP registries or specific integrations (Telegram,
  etc.), so it never imports them.

Daemons write a separate, much smaller self-record (see
``build_daemon_record``/``write_daemon_record``) on every daemon turn. The
owning agent's record aggregates ONLY present daemon self-records, newest
``LINGTAI_SESSION_STATS_DAEMON_LIMIT`` first; a daemon without a self-record is
silently ignored — never backfilled, never inferred, never shown as zero.

Never serialize: API keys/tokens/passwords, environment or config values, raw
prompts/messages/tool payloads, working-directory/host/user paths, shell
commands, PIDs, task/card free text, or raw logs. A field earns a place here
only with a documented consumer value, a bounded size/domain, and a clear
owner/clock.
"""
from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .._fsutil import atomic_write_json
from ..config import HEARTBEAT_LIVENESS_SECONDS

# ---------------------------------------------------------------------------
# Schema / filenames
# ---------------------------------------------------------------------------

#: The main Agent record — one per agent working directory, derived/safe to
#: delete, regenerated on the next throttled refresh (mirrors
#: ``system/manifest.resolved.json``).
AGENT_RECORD_SCHEMA = "lingtai.agent_record/v1"
AGENT_RECORD_VERSION = 1
AGENT_RECORD_RELATIVE_PATH = "system/agent_record.json"

#: One compact daemon self-record, written beside ``daemon.json`` in the
#: daemon's own run directory on every daemon turn.
DAEMON_RECORD_SCHEMA = "lingtai.daemon_record/v1"
DAEMON_RECORD_VERSION = 1
DAEMON_RECORD_FILENAME = "session_stats.json"

_DAEMONS_DIRNAME = "daemons"

# ---------------------------------------------------------------------------
# Environment configuration — validated with safe fallback, documented in
# ENVIRONMENT_VARIABLES.md (LINGTAI_SESSION_STATS_REFRESH_SECONDS,
# LINGTAI_SESSION_STATS_DAEMON_LIMIT).
# ---------------------------------------------------------------------------

REFRESH_SECONDS_ENV = "LINGTAI_SESSION_STATS_REFRESH_SECONDS"
DEFAULT_REFRESH_SECONDS = 5.0

DAEMON_LIMIT_ENV = "LINGTAI_SESSION_STATS_DAEMON_LIMIT"
DEFAULT_DAEMON_LIMIT = 1000


def session_stats_refresh_seconds() -> float:
    """Read ``LINGTAI_SESSION_STATS_REFRESH_SECONDS`` with a safe fallback.

    Missing, blank, non-numeric, non-finite, zero, or negative values fall
    back to :data:`DEFAULT_REFRESH_SECONDS`. Read live at each use point —
    no caching, no restart required.
    """
    raw = os.environ.get(REFRESH_SECONDS_ENV)
    if raw is None or not raw.strip():
        return DEFAULT_REFRESH_SECONDS
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return DEFAULT_REFRESH_SECONDS
    if not math.isfinite(value) or value <= 0:
        return DEFAULT_REFRESH_SECONDS
    return value


def session_stats_daemon_limit() -> int:
    """Read ``LINGTAI_SESSION_STATS_DAEMON_LIMIT`` with a safe fallback.

    Missing, blank, non-integer, zero, or negative values fall back to
    :data:`DEFAULT_DAEMON_LIMIT`. Read live at each use point.
    """
    raw = os.environ.get(DAEMON_LIMIT_ENV)
    if raw is None or not raw.strip():
        return DEFAULT_DAEMON_LIMIT
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_DAEMON_LIMIT
    if value <= 0:
        return DEFAULT_DAEMON_LIMIT
    return value


def should_refresh_agent_record(
    last_written_wall: float | None, wall_now: float, refresh_seconds: float
) -> bool:
    """Return whether a throttled Agent record write should proceed.

    ``last_written_wall`` is ``None`` on the first write (always refreshes).
    A wall-clock jump backwards (rare, e.g. NTP correction) also refreshes
    rather than wedging the record stale for ``refresh_seconds``.
    """
    if last_written_wall is None:
        return True
    return (wall_now - last_written_wall) >= refresh_seconds or wall_now < last_written_wall


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe_int(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return value


def _safe_round(value: Any, ndigits: int = 1) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value):
        return None
    return round(float(value), ndigits)


# ---------------------------------------------------------------------------
# Agent record — identity / session / health / usage / daemon aggregate
# ---------------------------------------------------------------------------


def agent_record_path(working_dir: Path | str) -> Path:
    return Path(working_dir) / AGENT_RECORD_RELATIVE_PATH


def build_agent_record(agent, *, sequence: int = 0) -> dict:
    """Build the redacted, versioned Agent record for *agent*.

    Reads only fields Core already owns (mirrors the allowlisted subset of
    ``BaseAgent.status()``/``_build_manifest`` — never the full working-dir
    path, never prompts/messages/tool payloads). ``extra`` blocks
    (``handles``/``integrations``) come from the outer composition root via
    ``agent._build_agent_record_extra()`` — Core never imports MCP/Telegram
    modules.
    """
    from ..config import HEARTBEAT_LIVENESS_SECONDS

    mail_addr = None
    if getattr(agent, "_mail_service", None) is not None and agent._mail_service.address:
        mail_addr = agent._mail_service.address

    wall_now = agent._lifecycle_clock.wall_seconds()
    started_at = getattr(agent, "_started_at", None)
    uptime_seconds = None
    if getattr(agent, "_uptime_anchor", None) is not None:
        uptime_seconds = _safe_round(
            agent._lifecycle_clock.monotonic_seconds() - agent._uptime_anchor
        )

    heartbeat = float(getattr(agent, "_heartbeat", 0.0) or 0.0)
    heartbeat_age_seconds = _safe_round(wall_now - heartbeat, 3) if heartbeat > 0 else None
    if heartbeat_age_seconds is None:
        liveness = "unknown"
    elif heartbeat_age_seconds < HEARTBEAT_LIVENESS_SECONDS:
        liveness = "fresh"
    else:
        liveness = "stale"

    # Last-activity anchors — the same fields Telegram's Task Card footer
    # already renders (an "active (Ns)" countdown) and the ACTIVE no-progress
    # watchdog uses. Carried through unchanged so that curated consumer can
    # stop reading .status.json without losing this fact.
    last_api_call_at = getattr(agent, "_last_api_call_at", None)
    last_progress_at = getattr(agent, "_last_progress_at", None)

    usage = agent.get_token_usage()
    context_limit = None
    context_usage_pct = None
    if getattr(agent, "_chat", None) is not None:
        try:
            context_limit = agent._config.context_limit or agent._chat.context_window()
            if context_limit:
                context_usage_pct = _safe_round(
                    usage["ctx_total_tokens"] / context_limit * 100
                )
        except Exception:
            context_limit = None

    from ..base_agent.identity import _safe_llm_from_service  # local import avoids a base_agent<->session_stats cycle at module load

    model = _safe_llm_from_service(agent)

    record: dict[str, Any] = {
        "schema": AGENT_RECORD_SCHEMA,
        "schema_version": AGENT_RECORD_VERSION,
        "generated_at": _utc_now_iso(),
        "sequence": sequence,
        "identity": {
            "agent_id": getattr(agent, "_agent_id", None),
            "agent_name": getattr(agent, "agent_name", None),
            "nickname": getattr(agent, "nickname", None),
            "mail_address": mail_addr,
        },
        "model": model or {},
        "handles": {},
        "integrations": [],
        "session": {
            "state": agent._state.value,
            "started_at": started_at,
            "uptime_seconds": uptime_seconds,
            "molt_count": _safe_int(getattr(agent, "_molt_count", 0)),
        },
        "health": {
            "heartbeat_at": heartbeat if heartbeat > 0 else None,
            "heartbeat_age_seconds": heartbeat_age_seconds,
            "liveness": liveness,
            "last_api_call_at": last_api_call_at,
            "last_progress_at": last_progress_at,
        },
        "usage": {
            "api_calls": _safe_int(usage.get("api_calls")),
            "input_tokens": _safe_int(usage.get("input_tokens")),
            "output_tokens": _safe_int(usage.get("output_tokens")),
            "thinking_tokens": _safe_int(usage.get("thinking_tokens")),
            "cached_tokens": _safe_int(usage.get("cached_tokens")),
            "context_used_tokens": _safe_int(usage.get("ctx_total_tokens")),
            "context_limit_tokens": context_limit,
            "context_usage_pct": context_usage_pct,
            # Meta-line decomposition — mirrors .status.json's tokens.context
            # (system/tools/history) so a curated consumer's existing
            # breakdown rendering (e.g. Telegram /kanban's "fixed/history"
            # line) needs no new source, only a new field path.
            "context_system_tokens": _safe_int(usage.get("ctx_system_tokens")),
            "context_tools_tokens": _safe_int(usage.get("ctx_tools_tokens")),
            "context_history_tokens": _safe_int(usage.get("ctx_history_tokens")),
        },
        "daemons": aggregate_daemon_records(getattr(agent, "_working_dir", None)),
    }

    extra_provider = getattr(agent, "_build_agent_record_extra", None)
    if callable(extra_provider):
        try:
            extra = extra_provider()
        except Exception:
            extra = None
        if isinstance(extra, dict):
            handles = extra.get("handles")
            if isinstance(handles, dict):
                record["handles"] = {
                    str(k): v for k, v in handles.items() if isinstance(v, (str, int, float, bool))
                }
            integrations = extra.get("integrations")
            if isinstance(integrations, list):
                record["integrations"] = [item for item in integrations if isinstance(item, dict)]

    return record


def write_agent_record(working_dir: Path | str, record: dict) -> Path:
    """Atomically publish *record* to ``system/agent_record.json``."""
    path = agent_record_path(working_dir)
    atomic_write_json(path, record, ensure_ascii=False, indent=2)
    return path


def read_agent_record(working_dir: Path | str) -> dict | None:
    """Read the current Agent record, or ``None`` if missing/corrupt.

    Callers that need to distinguish "missing" from "corrupt" for a stale
    presentation policy should catch the read themselves; this is the plain
    best-effort accessor used by same-process/local callers (e.g. wrapper
    extension points, tests).
    """
    path = agent_record_path(working_dir)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    return data if isinstance(data, dict) else None


def classify_published_agent_record(
    record: object,
    *,
    wall_now: float,
    liveness_seconds: float = HEARTBEAT_LIVENESS_SECONDS,
) -> str | None:
    """Classify a published Agent Record against an injected wall-clock value.

    ``health.liveness`` is a write-time snapshot, so consumers must not treat it
    as live evidence. Explicit ``stuck`` and ``suspended`` states remain
    authoritative. The running states require a finite heartbeat with an age
    strictly below ``liveness_seconds``; otherwise they are offline. Missing or
    unrecognized records return ``None`` for an unavailable presentation.
    """
    if not isinstance(record, dict):
        return None
    if (
        record.get("schema") != AGENT_RECORD_SCHEMA
        or record.get("schema_version") != AGENT_RECORD_VERSION
    ):
        return None

    session = record.get("session")
    if not isinstance(session, dict):
        return None
    state = session.get("state")
    if state not in {"active", "idle", "asleep", "stuck", "suspended"}:
        return None
    if state in {"stuck", "suspended"}:
        return state

    health = record.get("health")
    heartbeat_at = health.get("heartbeat_at") if isinstance(health, dict) else None
    if isinstance(heartbeat_at, bool) or not isinstance(heartbeat_at, (int, float)):
        return "offline"
    if not math.isfinite(heartbeat_at):
        return "offline"
    if isinstance(wall_now, bool) or not isinstance(wall_now, (int, float)):
        return "offline"
    if not math.isfinite(wall_now):
        return "offline"

    age = wall_now - heartbeat_at
    if not math.isfinite(age) or age >= liveness_seconds:
        return "offline"
    return state


def query_published_agent_liveness(
    record: object,
    *,
    wall_now: float,
) -> dict[str, str]:
    """Project the canonical published-record liveness decision as one dict.

    The result is always exactly ``{"liveness": <value>}``, where a malformed
    or unavailable record becomes ``"unavailable"``. This is the consumer
    contract: callers must not read legacy status sources or reconstruct the
    heartbeat policy from record fields.
    """
    lifecycle = classify_published_agent_record(record, wall_now=wall_now)
    return {"liveness": lifecycle if lifecycle is not None else "unavailable"}


# ---------------------------------------------------------------------------
# Daemon self-record — written by DaemonRunDir on every daemon turn
# ---------------------------------------------------------------------------


def daemon_record_path(run_dir: Path | str) -> Path:
    return Path(run_dir) / DAEMON_RECORD_FILENAME


def build_daemon_record(state: dict) -> dict:
    """Build the compact, redacted daemon self-record from live ``daemon.json`` state.

    Only bounded identity/lifecycle/usage fields cross this boundary — never
    the task text, tool arguments, error messages, or any path. ``tokens``
    (kernel-ledger-feeding) and ``cli_tokens`` (external-CLI display-only, see
    ``DaemonRunDir.record_cli_tokens``) are kept distinct, matching the
    source's own separation between billed ledger usage and UI-only CLI
    usage; aggregation combines them for display only (see
    ``aggregate_daemon_records``).
    """
    tokens = state.get("tokens") if isinstance(state.get("tokens"), dict) else {}
    cli_tokens = state.get("cli_tokens") if isinstance(state.get("cli_tokens"), dict) else {}
    run_id = state.get("run_id")
    handle = state.get("handle")
    group_id = state.get("group_id")
    backend = state.get("backend")
    daemon_state = state.get("state")
    return {
        "schema": DAEMON_RECORD_SCHEMA,
        "schema_version": DAEMON_RECORD_VERSION,
        "generated_at": _utc_now_iso(),
        "run_id": run_id if isinstance(run_id, str) else None,
        "handle": handle if isinstance(handle, str) else None,
        "group_id": group_id if isinstance(group_id, str) else None,
        "backend": backend if isinstance(backend, str) else None,
        "state": daemon_state if isinstance(daemon_state, str) else None,
        "started_at": state.get("started_at") if isinstance(state.get("started_at"), str) else None,
        "finished_at": state.get("finished_at") if isinstance(state.get("finished_at"), str) else None,
        "turn": _safe_int(state.get("turn")),
        "tool_call_count": _safe_int(state.get("tool_call_count")),
        "tokens": {
            "input": _safe_int(tokens.get("input")),
            "output": _safe_int(tokens.get("output")),
            "thinking": _safe_int(tokens.get("thinking")),
            "cached": _safe_int(tokens.get("cached")),
        },
        "cli_tokens": {
            "input": _safe_int(cli_tokens.get("input")),
            "output": _safe_int(cli_tokens.get("output")),
            "thinking": _safe_int(cli_tokens.get("thinking")),
            "cached": _safe_int(cli_tokens.get("cached")),
            "calls": _safe_int(cli_tokens.get("calls")),
        },
    }


def write_daemon_record(run_dir: Path | str, state: dict) -> Path:
    """Atomically publish this daemon's compact self-record.

    Called on every daemon turn (every write of ``daemon.json``'s live
    state) — see ``DaemonRunDir._persist_daemon_state``.
    """
    record = build_daemon_record(state)
    path = daemon_record_path(run_dir)
    atomic_write_json(path, record, ensure_ascii=False, indent=2)
    return path


# ---------------------------------------------------------------------------
# Bounded aggregation — newest-N PRESENT daemon self-records only. A daemon
# without this record is ignored: no legacy daemon.json scan, no inferred
# result, no fake zero, no partial backward-compat representation.
# ---------------------------------------------------------------------------


def _iter_daemon_record_paths(working_dir: Path | str) -> list[Path]:
    daemons_dir = Path(working_dir) / _DAEMONS_DIRNAME
    if not daemons_dir.is_dir():
        return []
    paths: list[Path] = []
    try:
        entries = list(daemons_dir.iterdir())
    except OSError:
        return []
    for run_dir in entries:
        if not run_dir.is_dir() or run_dir.name.startswith("_"):
            continue
        candidate = run_dir / DAEMON_RECORD_FILENAME
        if candidate.is_file():
            paths.append(candidate)
    return paths


def aggregate_daemon_records(working_dir: Path | str | None, *, limit: int | None = None) -> dict:
    """Aggregate the newest ``limit`` PRESENT daemon self-records.

    Returns ``present`` (how many daemon self-records exist at all),
    ``scanned`` (how many were actually read, bounded by *limit*), the
    resolved ``limit``, per-state counts, and combined usage totals. A
    missing ``working_dir`` (e.g. a bare test stub) returns an empty,
    honestly-zero aggregate rather than raising.
    """
    resolved_limit = limit if limit is not None else session_stats_daemon_limit()
    if not working_dir:
        return {
            "present": 0, "scanned": 0, "limit": resolved_limit,
            "counts_by_state": {}, "usage": _empty_daemon_usage_totals(),
        }

    paths = _iter_daemon_record_paths(working_dir)
    present = len(paths)
    try:
        paths.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        pass
    scanned_paths = paths[:resolved_limit]

    counts_by_state: dict[str, int] = {}
    totals = _empty_daemon_usage_totals()
    scanned = 0
    for path in scanned_paths:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            continue
        if not isinstance(data, dict) or data.get("schema") != DAEMON_RECORD_SCHEMA:
            continue
        scanned += 1
        state = data.get("state")
        if isinstance(state, str) and state:
            counts_by_state[state] = counts_by_state.get(state, 0) + 1
        tokens = data.get("tokens") if isinstance(data.get("tokens"), dict) else {}
        cli_tokens = data.get("cli_tokens") if isinstance(data.get("cli_tokens"), dict) else {}
        totals["input_tokens"] += _safe_int(tokens.get("input")) + _safe_int(cli_tokens.get("input"))
        totals["output_tokens"] += _safe_int(tokens.get("output")) + _safe_int(cli_tokens.get("output"))
        totals["thinking_tokens"] += _safe_int(tokens.get("thinking")) + _safe_int(cli_tokens.get("thinking"))
        totals["cached_tokens"] += _safe_int(tokens.get("cached")) + _safe_int(cli_tokens.get("cached"))
        totals["api_calls"] += _safe_int(cli_tokens.get("calls"))

    return {
        "present": present,
        "scanned": scanned,
        "limit": resolved_limit,
        "counts_by_state": counts_by_state,
        "usage": totals,
    }


def _empty_daemon_usage_totals() -> dict:
    return {
        "input_tokens": 0, "output_tokens": 0, "thinking_tokens": 0,
        "cached_tokens": 0, "api_calls": 0,
    }


__all__ = [
    "AGENT_RECORD_SCHEMA", "AGENT_RECORD_VERSION", "AGENT_RECORD_RELATIVE_PATH",
    "DAEMON_RECORD_SCHEMA", "DAEMON_RECORD_VERSION", "DAEMON_RECORD_FILENAME",
    "REFRESH_SECONDS_ENV", "DEFAULT_REFRESH_SECONDS",
    "DAEMON_LIMIT_ENV", "DEFAULT_DAEMON_LIMIT",
    "session_stats_refresh_seconds", "session_stats_daemon_limit",
    "should_refresh_agent_record",
    "agent_record_path", "build_agent_record", "write_agent_record", "read_agent_record",
    "classify_published_agent_record", "query_published_agent_liveness",
    "daemon_record_path", "build_daemon_record", "write_daemon_record",
    "aggregate_daemon_records",
]
