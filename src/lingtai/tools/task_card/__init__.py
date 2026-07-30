"""Intrinsic declarative Task Card capability.

One model-facing root ``task_card`` owns a single agent-local Task Card artifact
under ``<workdir>/taskcard/``:

- ``status``     — exact text ``active`` or ``inactive``
- ``taskcard.md`` — the rendered card body

The producer writes only those files. Channels consume/project them
independently.
"""

from __future__ import annotations

import math
import os
import subprocess
import sys
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, NamedTuple

from lingtai.kernel._fsutil import atomic_write_json, read_json

from ..tool_family import ChildTool, ToolFamily
from ..tool_family.manual import MANUAL_INPUT_SCHEMA, build_manual_child

if TYPE_CHECKING:
    from lingtai.kernel.base_agent import BaseAgent

# Built-in fallback defaults, used when no configured value applies (missing
# config file, missing field, or an invalid field). ``interval_s`` is a pure
# cadence default with no ceiling — only ``_MIN_INTERVAL_S`` bounds it, in
# either direction. ``timeout_s``/``max_refreshes`` are safety ceilings: a
# configured value lowers the effective ceiling for both the default (used
# when a watch omits the field) and the maximum an explicit per-watch value
# may request.
_DEFAULT_TIMEOUT_S = 10.0
_DEFAULT_INTERVAL_S = 5.0
_MIN_INTERVAL_S = 1.0
_MIN_TIMEOUT_S = 0.1
_DEFAULT_MAX_REFRESHES = 2000
_TASKCARD_DIR = "taskcard"
_STATUS_FILENAME = "status"
_BODY_FILENAME = "taskcard.md"
_CONFIG_FILENAME = "taskcard.json"
# One-way migration source only: the retired Telegram-owned reverse-channel
# design persisted its own refresh ceiling here. Consulted only when this
# capability's own config file has never been created; that first resolution
# is always persisted (migrated or not), so this path is never read again
# afterward (see ``TaskCardManager._migrate_legacy_config``).
_LEGACY_CONFIG_DIR = "telegram"
# ``TelegramService``'s own untouched default/ceiling for that legacy field
# (see ``mcp_servers/telegram/service.py:_TASKCARD_DEFAULT_MAX_REFRESHES``).
# The ordinary ``/taskcard on|off|N`` commands persist that file's three
# fields together purely to toggle unrelated presentation settings, so a
# ``max_refreshes`` sitting at exactly this value carries no migration
# signal — only a value that actually differs proves a human, or an earlier
# now-removed interface, once chose it on purpose. Migrating this untouched
# value forward would silently cap most real agents below the new built-in
# default instead of leaving them on it.
_LEGACY_UNTOUCHED_MAX_REFRESHES = 1000
_MANUAL_SKILL_NAME = "task_card"


class _Config(NamedTuple):
    """Resolved agent-wide Task Card defaults/ceilings for a new watch."""

    interval_s: float
    timeout_s: float
    max_refreshes: int


_BUILTIN_CONFIG = _Config(_DEFAULT_INTERVAL_S, _DEFAULT_TIMEOUT_S, _DEFAULT_MAX_REFRESHES)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _object(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    value: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required is not None:
        value["required"] = required
    return value


_START_INPUT_SCHEMA = _object(
    {
        "renderer_path": {"type": "string"},
        "interval_s": {"type": "number", "minimum": 1},
        "timeout_s": {"type": "number", "minimum": 0.1},
        "max_refreshes": {"type": "integer", "minimum": 1},
    },
    required=["renderer_path"],
)
_WATCH_INPUT_SCHEMA = _object({"watch_id": {"type": "string"}}, required=["watch_id"])

_CHILDREN: tuple[tuple[str, dict[str, Any]], ...] = (
    ("start", _START_INPUT_SCHEMA),
    ("inspect", _WATCH_INPUT_SCHEMA),
    ("retry", _WATCH_INPUT_SCHEMA),
    ("stop", _WATCH_INPUT_SCHEMA),
    ("manual", MANUAL_INPUT_SCHEMA),
)


def _schema_family() -> ToolFamily:
    return ToolFamily(
        "task_card",
        [ChildTool(name, schema, lambda _input: {}) for name, schema in _CHILDREN],
    )


_SCHEMA_FAMILY = _schema_family()


def get_schema() -> dict[str, Any]:
    schema = _SCHEMA_FAMILY.build_schema()
    schema["properties"]["action"]["description"] = (
        "Declarative Task Card action. start keeps one renderer watch writing the "
        "agent-local taskcard/status and taskcard/taskcard.md files; inspect, retry, "
        "stop, and manual read or control that one artifact."
    )
    return schema


def get_description() -> str:
    return (
        "Manage the intrinsic declarative Task Card artifact. Provide a Python "
        "renderer under your working directory whose stdout is the full Task Card "
        "body to write into taskcard/taskcard.md. The capability writes taskcard/"
        "taskcard.md atomically, writes taskcard/status as exact active/inactive, "
        "keeps at most one active watch per agent, and leaves projection to "
        "channel-specific readers. Use it proactively for meaningful long-running, "
        "multi-step, or parallel work so a human can follow progress; skip it for "
        "quick single-step work, ritual updates, or a body you cannot keep truthful "
        "and current. Actions: start, inspect, retry, stop, manual."
    )


class TaskCardError(Exception):
    """Synchronous, user-visible Task Card error."""


class _Watch:
    __slots__ = (
        "watch_id",
        "renderer_path",
        "interval_s",
        "timeout_s",
        "thread",
        "stop_event",
        "lock",
        "last_valid_body",
        "last_valid_at",
        "error",
        "error_key",
        "error_epoch",
        "stopping",
        "max_refreshes",
        "refreshes_used",
        "attempt_lock",
        "limit_notified",
        "stop_reason",
    )

    def __init__(
        self,
        watch_id: str,
        renderer_path: Path,
        interval_s: float,
        timeout_s: float,
        max_refreshes: int,
    ) -> None:
        self.watch_id = watch_id
        self.renderer_path = renderer_path
        self.interval_s = interval_s
        self.timeout_s = timeout_s
        self.thread: threading.Thread | None = None
        self.stop_event = threading.Event()
        self.lock = threading.RLock()
        self.last_valid_body: str | None = None
        self.last_valid_at: str | None = None
        self.error: dict[str, Any] | None = None
        self.error_key: str | None = None
        self.error_epoch = 0
        self.stopping = False
        self.max_refreshes = max_refreshes
        self.refreshes_used = 0
        self.attempt_lock = threading.Lock()
        self.limit_notified = False
        self.stop_reason: str | None = None


class TaskCardManager:
    """Own the intrinsic Task Card watch and atomic writer contract."""

    def __init__(self, agent: BaseAgent) -> None:
        self._agent = agent
        self._lock = threading.RLock()
        self._counter = 0
        self._watch: _Watch | None = None
        self._taskcard_dir = Path(agent._working_dir) / _TASKCARD_DIR
        self._status_path = self._taskcard_dir / _STATUS_FILENAME
        self._body_path = self._taskcard_dir / _BODY_FILENAME
        self._config_path = self._taskcard_dir / _CONFIG_FILENAME
        self._legacy_config_path = self._taskcard_dir.parent / _LEGACY_CONFIG_DIR / _CONFIG_FILENAME

    def handle(self, args: dict[str, Any] | None) -> dict[str, Any]:
        try:
            return self._family().handle(args or {})
        except TaskCardError as exc:
            return {"status": "failed", "message": str(exc)}

    def _family(self) -> ToolFamily:
        children = [
            ChildTool("start", _START_INPUT_SCHEMA, self._start_child),
            ChildTool("inspect", _WATCH_INPUT_SCHEMA, self._inspect_child),
            ChildTool("retry", _WATCH_INPUT_SCHEMA, self._retry_child),
            ChildTool("stop", _WATCH_INPUT_SCHEMA, self._stop_child),
            build_manual_child(self._agent, _MANUAL_SKILL_NAME),
        ]
        return ToolFamily("task_card", children)

    def _start_child(self, input_: dict[str, Any]) -> dict[str, Any]:
        renderer_path = self._validate_renderer_path(input_.get("renderer_path"))
        config = self._load_config()
        # interval_s is a cadence default, not a safety ceiling: an omitted
        # value uses the configured cadence, and an explicit value is never
        # clamped down to it — only the absolute floor applies either way.
        interval_s = self._coerce_positive(
            input_.get("interval_s", config.interval_s), "interval_s", _MIN_INTERVAL_S
        )
        # timeout_s and max_refreshes are safety ceilings: an omitted value
        # uses the configured ceiling, and an explicit value may only lower
        # it (min-clamped), never exceed it.
        requested_timeout = input_.get("timeout_s")
        if requested_timeout is None:
            timeout_s = config.timeout_s
        else:
            timeout_s = min(
                self._coerce_positive(requested_timeout, "timeout_s", _MIN_TIMEOUT_S),
                config.timeout_s,
            )
        requested_max = input_.get("max_refreshes")
        if requested_max is None:
            effective_max = config.max_refreshes
        elif type(requested_max) is int and requested_max > 0:
            effective_max = min(requested_max, config.max_refreshes)
        else:
            raise TaskCardError("max_refreshes must be a positive integer")
        with self._lock:
            if self._watch is not None:
                raise TaskCardError("only one Task Card watch may be active per agent")
            self._counter += 1
            watch = _Watch(
                f"tc_{self._counter}",
                renderer_path,
                interval_s,
                timeout_s,
                effective_max,
            )
            self._watch = watch
        try:
            body = self._run_renderer(renderer_path, timeout_s)
            self._publish_active(body)
        except Exception:
            with self._lock:
                if self._watch is watch:
                    self._watch = None
            try:
                self._write_status("inactive")
            except OSError:
                pass
            raise
        with watch.lock:
            watch.last_valid_body = body
            watch.last_valid_at = _utc_now_iso()
        self._spawn(watch)
        return {
            "status": "ok",
            "watch_id": watch.watch_id,
            "state": "watching",
            **self._paths_payload(),
            **self._status_payload("active"),
            **self._refresh_fields(watch),
        }

    def _inspect_child(self, input_: dict[str, Any]) -> dict[str, Any]:
        watch = self._require_watch(input_.get("watch_id"))
        with watch.lock:
            if watch.stopping:
                state = "stop_failed" if watch.error else "stopping"
                status_value = "inactive"
            elif watch.error:
                state = "error"
                status_value = "active"
            else:
                state = "watching"
                status_value = "active"
            return {
                "status": "ok",
                "watch_id": watch.watch_id,
                "state": state,
                "last_valid_body": watch.last_valid_body,
                "last_valid_body_at": watch.last_valid_at,
                "error": watch.error,
                **self._paths_payload(),
                **self._status_payload(status_value),
                **self._refresh_fields(watch),
            }

    def _retry_child(self, input_: dict[str, Any]) -> dict[str, Any]:
        watch = self._require_watch(input_.get("watch_id"))
        if watch.stopping:
            return self._stop_watch(watch)
        self._tick(watch)
        return self._inspect_child({"watch_id": watch.watch_id})

    def _stop_child(self, input_: dict[str, Any]) -> dict[str, Any]:
        return self._stop_watch(self._require_watch(input_.get("watch_id")))

    def _stop_watch(self, watch: _Watch) -> dict[str, Any]:
        with watch.lock:
            watch.stopping = True
        try:
            self._write_status("inactive")
        except OSError as exc:
            error = {
                "code": "stop_finalize_failed",
                "retryable": True,
                "message": f"failed to write inactive status: {type(exc).__name__}",
            }
            with watch.lock:
                watch.error = error
            return {
                "status": "error",
                "watch_id": watch.watch_id,
                "state": "stop_failed",
                "error": error,
                **self._paths_payload(),
                **self._status_payload("inactive"),
                **self._refresh_fields(watch),
            }
        watch.stop_event.set()
        thread = watch.thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=watch.timeout_s + 1.0)
        if thread is not None and thread.is_alive():
            error = {
                "code": "stop_thread_alive",
                "retryable": True,
                "message": "the watcher thread has not stopped yet; retry stop once quiescent",
            }
            with watch.lock:
                watch.error = error
            return {
                "status": "error",
                "watch_id": watch.watch_id,
                "state": "stop_failed",
                "error": error,
                **self._paths_payload(),
                **self._status_payload("inactive"),
                **self._refresh_fields(watch),
            }
        with self._lock:
            if self._watch is watch:
                self._watch = None
        return {
            "status": "ok",
            "watch_id": watch.watch_id,
            "state": "stopped",
            **self._paths_payload(),
            **self._status_payload("inactive"),
            **self._refresh_fields(watch),
        }

    def _spawn(self, watch: _Watch) -> None:
        watch.thread = threading.Thread(
            target=self._loop,
            args=(watch,),
            daemon=True,
            name=f"task-card-watch-{watch.watch_id}",
        )
        watch.thread.start()

    def _loop(self, watch: _Watch) -> None:
        shutdown = getattr(self._agent, "_shutdown", None)
        while not watch.stop_event.is_set():
            if shutdown is not None and shutdown.is_set():
                return
            if watch.stop_event.wait(timeout=watch.interval_s):
                return
            if shutdown is not None and shutdown.is_set():
                return
            self._tick(watch)

    def _tick(self, watch: _Watch) -> None:
        with watch.attempt_lock:
            with watch.lock:
                if watch.stopping or watch.refreshes_used >= watch.max_refreshes:
                    return
                watch.refreshes_used += 1
                exhausted = watch.refreshes_used >= watch.max_refreshes
            try:
                body = self._run_renderer(watch.renderer_path, watch.timeout_s)
            except TaskCardError as exc:
                if self._stop_requested(watch):
                    return
                self._mark_error(watch, self._error_from_exc(exc), emit_notification=not exhausted)
                if exhausted:
                    self._exhaust(watch)
                return
            if self._stop_requested(watch):
                return
            try:
                self._write_body(body)
            except OSError as exc:
                self._mark_error(
                    watch,
                    {
                        "code": "write_failed",
                        "retryable": True,
                        "message": f"failed to update task card body: {type(exc).__name__}",
                    },
                    emit_notification=not exhausted,
                )
                if exhausted:
                    self._exhaust(watch)
                return
            self._mark_recovered(watch, body)
            if exhausted and not watch.stopping:
                self._exhaust(watch)

    def _exhaust(self, watch: _Watch) -> None:
        with watch.lock:
            if watch.stop_reason == "max_refreshes":
                return
            watch.stop_reason = "max_refreshes"
            watch.stopping = True
        try:
            self._write_status("inactive")
        except OSError as exc:
            with watch.lock:
                watch.error = {
                    "code": "stop_finalize_failed",
                    "retryable": True,
                    "message": f"failed to write inactive status: {type(exc).__name__}",
                }
            self._emit_limit_event(watch)
            return
        watch.stop_event.set()
        self._emit_limit_event(watch)
        with self._lock:
            if self._watch is watch:
                self._watch = None

    def _stop_requested(self, watch: _Watch) -> bool:
        if watch.stop_event.is_set():
            return True
        shutdown = getattr(self._agent, "_shutdown", None)
        return bool(shutdown is not None and shutdown.is_set())

    def _publish_active(self, body: str) -> None:
        self._write_body(body)
        self._write_status("active")

    def _write_body(self, body: str) -> None:
        self._atomic_write_text(self._body_path, body, trailing_newline=False)

    def _write_status(self, status: str) -> None:
        if status not in {"active", "inactive"}:
            raise ValueError(f"invalid task card status: {status}")
        self._atomic_write_text(self._status_path, status, trailing_newline=False)

    @staticmethod
    def _atomic_write_text(path: Path, text: str, *, trailing_newline: bool) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = text if not trailing_newline else f"{text}\n"
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def _run_renderer(self, path: Path, timeout_s: float) -> str:
        try:
            proc = subprocess.run(
                [sys.executable, str(path)],
                capture_output=True,
                text=True,
                timeout=timeout_s,
                cwd=str(self._agent._working_dir),
            )
        except subprocess.TimeoutExpired as exc:
            raise TaskCardError(f"renderer timed out after {timeout_s}s") from exc
        except OSError as exc:
            raise TaskCardError("renderer could not be executed") from exc
        if proc.returncode != 0:
            raise TaskCardError(f"renderer exited with status {proc.returncode}")
        return self._validate_body(proc.stdout)

    @staticmethod
    def _validate_body(stdout: str) -> str:
        if not isinstance(stdout, str) or not stdout.strip():
            raise TaskCardError("renderer produced no output")
        return stdout

    @staticmethod
    def _error_from_exc(exc: TaskCardError) -> dict[str, Any]:
        message = str(exc)
        if "timed out" in message:
            code = "renderer_timeout"
        elif "status" in message:
            code = "renderer_nonzero_exit"
        else:
            code = "renderer_failed"
        return {"code": code, "message": message, "retryable": True}

    def _mark_error(
        self,
        watch: _Watch,
        error: dict[str, Any],
        *,
        emit_notification: bool = True,
    ) -> None:
        key = str(error.get("code"))
        with watch.lock:
            if watch.error is None:
                watch.error_epoch += 1
            already = watch.error_key == key
            watch.error = error
            watch.error_key = key
            epoch = watch.error_epoch
            last_valid_at = watch.last_valid_at
        if already or not emit_notification:
            return
        self._emit_event(watch, error, last_valid_at, epoch=epoch, recovered=False)

    def _mark_recovered(self, watch: _Watch, body: str) -> None:
        with watch.lock:
            was_errored = watch.error is not None
            epoch = watch.error_epoch
            watch.error = None
            watch.error_key = None
            watch.last_valid_body = body
            watch.last_valid_at = _utc_now_iso()
        if was_errored:
            self._emit_event(watch, None, None, epoch=epoch, recovered=True)

    def _emit_event(
        self,
        watch: _Watch,
        error: dict[str, Any] | None,
        last_valid_at: str | None,
        *,
        epoch: int,
        recovered: bool,
    ) -> None:
        enqueue = getattr(self._agent, "_enqueue_system_notification", None)
        if not callable(enqueue):
            return
        if recovered:
            body = f"Task Card watch {watch.watch_id} recovered."
            extra: dict[str, Any] = {"watch_id": watch.watch_id, "state": "recovered"}
            key = f"task_card.recovered:{watch.watch_id}:{epoch}"
            priority = "normal"
        else:
            code = str((error or {}).get("code", "error"))
            body = f"Task Card watch {watch.watch_id} failed: {(error or {}).get('message', code)}"
            extra = {
                "watch_id": watch.watch_id,
                "state": "error",
                "code": code,
                "retryable": (error or {}).get("retryable", "unknown"),
            }
            if last_valid_at:
                extra["last_valid_body_at"] = last_valid_at
            key = f"task_card.error:{watch.watch_id}:{epoch}:{code}"
            priority = "high"
        try:
            enqueue(
                source="task_card.error",
                ref_id=watch.watch_id,
                body=body,
                idempotency_key=key,
                skip_if_idempotency_key_exists=True,
                priority=priority,
                extra=extra,
            )
        except Exception:
            pass

    def _emit_limit_event(self, watch: _Watch) -> None:
        enqueue = getattr(self._agent, "_enqueue_system_notification", None)
        if not callable(enqueue):
            return
        with watch.lock:
            if watch.limit_notified:
                return
            watch.limit_notified = True
            used = watch.refreshes_used
            maximum = watch.max_refreshes
            last_valid_at = watch.last_valid_at
        extra: dict[str, Any] = {
            "watch_id": watch.watch_id,
            "state": "stopped",
            "reason": "max_refreshes",
            "used": used,
            "max": maximum,
        }
        if last_valid_at:
            extra["last_valid_body_at"] = last_valid_at
        try:
            enqueue(
                source="task_card.limit",
                ref_id=watch.watch_id,
                body=(
                    f"Task Card watch {watch.watch_id} reached its refresh limit. "
                    "Refresh or reinspect the underlying task state, and start a new "
                    "watch only if useful."
                ),
                idempotency_key=f"task_card.limit:{watch.watch_id}:{maximum}",
                skip_if_idempotency_key_exists=True,
                priority="normal",
                extra=extra,
            )
        except Exception:
            pass

    def _require_watch(self, watch_id: Any) -> _Watch:
        if not isinstance(watch_id, str):
            raise TaskCardError("watch_id is required")
        with self._lock:
            watch = self._watch
        if watch is None or watch.watch_id != watch_id:
            raise TaskCardError(f"unknown watch_id: {watch_id}")
        return watch

    def shutdown_for_agent_stop(self, *, reason: str = "") -> None:
        del reason
        with self._lock:
            watch = self._watch
            self._watch = None
        if watch is None:
            return
        with watch.lock:
            watch.stopping = True
        try:
            self._write_status("inactive")
        except OSError:
            pass
        watch.stop_event.set()
        if watch.thread is not None and watch.thread.is_alive():
            watch.thread.join(timeout=watch.timeout_s + 1.0)

    def _load_config(self) -> _Config:
        """Load this agent's persisted Task Card defaults/ceilings.

        Each field falls back to its own built-in default independently, so
        one invalid field never discards a valid sibling. A config file that
        has never been created (not merely empty/invalid) triggers one-time
        resolution against legacy state instead of the plain built-in
        defaults; that resolution is persisted unconditionally, so this
        branch is taken at most once per agent (see
        ``_migrate_legacy_config``). If the config file already exists but
        cannot be read as a JSON object — missing, malformed, undecodable, or
        the wrong top-level type — it remains the sole owner: this falls back
        to built-in defaults without ever consulting legacy state.
        """
        if not self._config_path.is_file():
            return self._migrate_legacy_config()
        try:
            data = read_json(self._config_path, expect=dict)
        except (OSError, ValueError, TypeError):
            return _BUILTIN_CONFIG
        return _Config(
            self._config_number(data.get("interval_s"), _MIN_INTERVAL_S, _DEFAULT_INTERVAL_S),
            self._config_number(data.get("timeout_s"), _MIN_TIMEOUT_S, _DEFAULT_TIMEOUT_S),
            self._config_max_refreshes(data.get("max_refreshes")),
        )

    def _migrate_legacy_config(self) -> _Config:
        """One-time resolution against legacy state; always persisted.

        Reads ``<workdir>/telegram/taskcard.json`` (the retired Telegram
        controller's persisted ``max_refreshes`` fuse) only because this
        capability's own config file has never been created. A valid value
        that actually differs from Telegram's own untouched default is
        migrated into the resolved config; an absent, invalid, undecodable,
        or untouched-default legacy value resolves to the plain built-in
        defaults instead, exactly as if no legacy state existed — this is
        what keeps an ordinary ``/taskcard on|off|N`` user (who never
        customized the refresh ceiling, but whose settings file still
        carries that field at its own default) on the new built-in default
        instead of an incidental, non-chosen 1000.

        Either way, the resolved config is written into the intrinsic config
        file unconditionally. This is the only way that file is ever
        created, and creating it regardless of whether anything actually
        migrated is what makes the legacy read genuinely one-way and
        one-time: once it exists, ``_load_config`` never calls this method
        again for this agent, so a later change to the Telegram-owned file
        cannot alter intrinsic policy.
        """
        try:
            legacy = read_json(self._legacy_config_path, expect=dict)
        except (OSError, ValueError, TypeError):
            legacy = None
        legacy_max = legacy.get("max_refreshes") if legacy is not None else None
        if (
            type(legacy_max) is not int
            or legacy_max <= 0
            or legacy_max == _LEGACY_UNTOUCHED_MAX_REFRESHES
        ):
            resolved = _BUILTIN_CONFIG
        else:
            resolved = _Config(_DEFAULT_INTERVAL_S, _DEFAULT_TIMEOUT_S, legacy_max)
        try:
            atomic_write_json(
                self._config_path,
                {
                    "interval_s": resolved.interval_s,
                    "timeout_s": resolved.timeout_s,
                    "max_refreshes": resolved.max_refreshes,
                },
                fsync=True,
            )
        except OSError:
            pass
        return resolved

    @staticmethod
    def _config_number(value: Any, minimum: float, default: float) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return default
        numeric = float(value)
        return numeric if math.isfinite(numeric) and numeric >= minimum else default

    @staticmethod
    def _config_max_refreshes(value: Any) -> int:
        return value if type(value) is int and value > 0 else _DEFAULT_MAX_REFRESHES

    def _validate_renderer_path(self, raw: Any) -> Path:
        if not isinstance(raw, str) or not raw.strip():
            raise TaskCardError("renderer_path is required for start")
        workdir = Path(self._agent._working_dir)
        candidate = raw.strip()
        try:
            wd = workdir.resolve()
            joined = Path(candidate) if Path(candidate).is_absolute() else (workdir / candidate)
            resolved = joined.resolve()
        except (OSError, RuntimeError, ValueError) as exc:
            raise TaskCardError(f"renderer_path could not be resolved ({exc})") from exc
        try:
            resolved.relative_to(wd)
        except ValueError as exc:
            raise TaskCardError(
                "renderer_path must be inside the agent working directory "
                "(no path traversal, no absolute escape)"
            ) from exc
        if not resolved.is_file():
            raise TaskCardError("renderer_path must be an existing regular file")
        return resolved

    @staticmethod
    def _coerce_positive(value: Any, name: str, minimum: float) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TaskCardError(f"{name} must be a number")
        numeric = float(value)
        if numeric < minimum:
            raise TaskCardError(f"{name} must be at least {minimum}")
        return numeric

    @staticmethod
    def _refresh_fields(watch: _Watch) -> dict[str, Any]:
        with watch.lock:
            used = watch.refreshes_used
            maximum = watch.max_refreshes
            reason = watch.stop_reason
        return {
            "refreshes_used": used,
            "max_refreshes": maximum,
            "refreshes_remaining": max(0, maximum - used),
            "stop_reason": reason,
        }

    def _paths_payload(self) -> dict[str, str]:
        return {
            "taskcard_dir": str(self._taskcard_dir),
            "status_path": str(self._status_path),
            "body_path": str(self._body_path),
        }

    @staticmethod
    def _status_payload(status_value: str) -> dict[str, str]:
        return {"status_value": status_value}


def setup(agent: BaseAgent, **_ignored: Any) -> TaskCardManager:
    manager = getattr(agent, "_task_card_manager", None)
    if not isinstance(manager, TaskCardManager):
        manager = TaskCardManager(agent)
        agent._task_card_manager = manager
    else:
        manager._agent = agent
    agent.add_tool(
        "task_card",
        schema=get_schema(),
        handler=manager.handle,
        description=get_description(),
        glossary_package=None,
    )
    return manager
