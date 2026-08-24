"""Karma-gated lifecycle actions — sleep, lull, suspend, cpr, interrupt, clear, nirvana."""
from __future__ import annotations

import time
from typing import Any, Protocol

from lingtai.kernel.agent_presence import (
    AgentPresenceStorePort,
    DEFAULT_LIVENESS_THRESHOLD_SECONDS,
    is_agent as _presence_is_agent,
    observe_alive as _presence_observe_alive,
)
from lingtai.kernel.handshake import resolve_address


# ---------------------------------------------------------------------------
# Karma / Nirvana gate mapping
# ---------------------------------------------------------------------------

_KARMA_ACTIONS = {"interrupt", "lull", "suspend", "cpr", "clear"}
_NIRVANA_ACTIONS = {"nirvana"}


class SystemSleepPort(Protocol):
    """Narrow effects/evidence needed by the System sleep use case.

    The policy belongs to System; a host adapter supplies only the current
    attention evidence and the irreversible state-transition effects.  Keeping
    this protocol here prevents the mounted bridge from growing an
    Agent-shaped callback or a second sleep decision tree.
    """

    @property
    def language(self) -> str: ...

    def sleep_attention_fingerprints(
        self,
    ) -> tuple[tuple[Any, ...], tuple[Any, ...]]: ...

    def log(self, event: str, **fields: Any) -> None: ...

    def transition_to_asleep(self) -> None: ...


def sleep_use_case(
    port: SystemSleepPort, *, reason: str = "", force: bool = False
) -> dict:
    """Apply System's one self-sleep policy through a narrow port.

    ``pending`` and ``committed`` are attention fingerprints, not raw queue
    contents.  A mismatch refuses the transition unless the caller explicitly
    supplies ``force=True``; all logging, receipts, and state effects stay in
    this single System-owned use case.
    """
    from lingtai.kernel.i18n import t

    pending_fp, committed_fp = port.sleep_attention_fingerprints()
    has_pending = pending_fp != committed_fp
    if has_pending and not force:
        port.log(
            "sleep_refused_pending_notifications",
            reason=reason,
            pending_fp=list(pending_fp),
            committed_fp=list(committed_fp or ()),
        )
        return {
            "status": "ok",
            "message": t(
                port.language,
                "system_tool.sleep_refused_pending_notifications",
            ),
        }

    if has_pending and force:
        port.log(
            "sleep_forced_with_pending_notifications",
            reason=reason,
            pending_fp=list(pending_fp),
        )

    port.log("self_sleep", reason=reason)
    port.transition_to_asleep()
    return {
        "status": "ok",
        "message": t(port.language, "system_tool.sleep_message"),
    }


class _DirectSleepPort:
    """Compatibility-only port over the historical direct Agent surface."""

    __slots__ = ("_agent",)

    def __init__(self, agent: Any) -> None:
        self._agent = agent

    @property
    def language(self) -> str:
        return self._agent._config.language

    def sleep_attention_fingerprints(
        self,
    ) -> tuple[tuple[Any, ...], tuple[Any, ...]]:
        from lingtai.kernel.notifications import (
            _workdir_key,
            attention_fingerprint,
            is_channel_allowed,
        )

        workdir = _workdir_key(self._agent)
        pending = attention_fingerprint(
            self._agent._notification_store,
            lambda channel: is_channel_allowed(channel, workdir=workdir),
            workdir,
        )
        return pending, tuple(self._agent._notification_fp or ())

    def log(self, event: str, **fields: Any) -> None:
        self._agent._log(event, **fields)

    def transition_to_asleep(self) -> None:
        from lingtai.kernel.state import AgentState

        self._agent._set_state(AgentState.ASLEEP, reason="self-sleep")
        self._agent._asleep.set()
        self._agent._cancel_event.set()


def _presence_for(target) -> AgentPresenceStorePort:
    """Build a target-bound POSIX presence adapter for a resolved agent dir."""
    from lingtai.adapters.posix.agent_presence import PosixAgentPresenceStoreAdapter
    return PosixAgentPresenceStoreAdapter(target)


def _is_agent(target) -> bool:
    """Foreign-address agent check via the presence store + Core policy."""
    return _presence_is_agent(_presence_for(target).observe_manifest())


def _is_alive(target, threshold: float = DEFAULT_LIVENESS_THRESHOLD_SECONDS) -> bool:
    """Foreign-address liveness check via the presence store + Core policy.

    The default threshold is the shared config liveness window
    (``DEFAULT_LIVENESS_THRESHOLD_SECONDS`` in ``lingtai.kernel.agent_presence``,
    resolved from ``LINGTAI_AGENT_ALIVE_THRESHOLD_SEC``), so karma gates and the
    CPR relaunch poll share one window instead of the historical 2.0/3.0 split.
    """
    return _presence_observe_alive(
        _presence_for(target),
        wall_now=time.time(),
        threshold=threshold,
    )


def _check_karma_gate(agent, action: str, args: dict) -> dict | None:
    if action in _KARMA_ACTIONS and not agent._admin.get("karma"):
        return {"error": True, "message": f"Not authorized for {action} (requires admin.karma=True)"}
    if action in _NIRVANA_ACTIONS and not (agent._admin.get("karma") and agent._admin.get("nirvana")):
        return {"error": True, "message": f"Not authorized for {action} (requires admin.karma=True AND admin.nirvana=True)"}
    address = args.get("address")
    if not address:
        return {"error": True, "message": f"{action} requires an address"}
    # Resolve relative address to absolute path
    base_dir = agent._working_dir.parent
    resolved = resolve_address(address, base_dir)
    if str(resolved) == str(agent._working_dir):
        return {"error": True, "message": f"Cannot {action} self"}
    if not _is_agent(resolved):
        return {"error": True, "message": f"No agent at {address}"}
    # Store resolved path for downstream use
    args["_resolved_address"] = resolved
    return None


def _sleep(agent, args: dict) -> dict:
    """Self-sleep through System's single semantic use case.

    The direct Agent-like route uses ``_DirectSleepPort``.  A serialized
    integration will expose the same ``SystemSleepPort`` evidence/effects on
    ``SystemRuntimePort``; the exact-head mounted adapter still provides its
    historical ``_system_sleep`` compatibility callback until that shared seam
    is reconciled.
    """
    reason = str(args.get("reason", ""))
    force = bool(args.get("force", False))

    port = getattr(agent, "_system_sleep_port", None)
    if port is not None:
        return sleep_use_case(port, reason=reason, force=force)

    runtime_sleep = getattr(agent, "_system_sleep", None)
    if callable(runtime_sleep):
        # Current reviewed-head bridge compatibility. The serialized host
        # repair must replace this callback with ``sleep_use_case`` over the
        # SystemSleepPort; this fallback is intentionally not a second policy.
        return runtime_sleep(args)

    return sleep_use_case(_DirectSleepPort(agent), reason=reason, force=force)


def _lull(agent, args: dict) -> dict:
    """Lull another agent to sleep — karma-gated."""
    err = _check_karma_gate(agent, "lull", args)
    if err:
        return err
    address = args["address"]
    resolved = args["_resolved_address"]
    if not _is_alive(resolved):
        return {"error": True, "message": f"Agent at {address} is not running — already asleep?"}
    (resolved / ".sleep").write_text("", encoding="utf-8")
    agent._log("karma_lull", target=address)
    return {"status": "asleep", "address": address}


def _suspend(agent, args: dict) -> dict:
    """Suspend another agent — karma-gated."""
    err = _check_karma_gate(agent, "suspend", args)
    if err:
        return err
    address = args["address"]
    resolved = args["_resolved_address"]
    if not _is_alive(resolved):
        return {"error": True, "message": f"Agent at {address} is not running — already suspended?"}
    (resolved / ".suspend").write_text("", encoding="utf-8")
    agent._log("karma_suspend", target=address)
    return {"status": "suspended", "address": address}


def _cpr(agent, args: dict) -> dict:
    err = _check_karma_gate(agent, "cpr", args)
    if err:
        return err
    address = args["address"]
    resolved = args["_resolved_address"]
    if _is_alive(resolved):
        return {"error": True, "message": f"Agent at {address} is already running"}
    resuscitated = agent._cpr_agent(str(resolved))
    if resuscitated is None:
        return {"error": True, "message": "CPR not supported — no _cpr_agent handler"}
    if isinstance(resuscitated, dict) and resuscitated.get("error"):
        agent._log("karma_cpr_failed", target=address, message=resuscitated.get("message"))
        return resuscitated
    if resuscitated is False:
        agent._log("karma_cpr_failed", target=address, message="_cpr_agent returned False")
        return {"error": True, "message": "CPR failed"}
    agent._log("karma_cpr", target=address)
    return {"status": "resuscitated", "address": address}


def _interrupt(agent, args: dict) -> dict:
    err = _check_karma_gate(agent, "interrupt", args)
    if err:
        return err
    address = args["address"]
    resolved = args["_resolved_address"]
    if not _is_alive(resolved):
        return {"error": True, "message": f"Agent at {address} is not running"}
    (resolved / ".interrupt").write_text("", encoding="utf-8")
    agent._log("karma_interrupt", target=address)
    return {"status": "interrupted", "address": address}


def _clear(agent, args: dict) -> dict:
    """Force a full molt on another agent — karma-gated.

    Writes a .clear signal; the target's heartbeat loop picks it up and
    invokes psyche.context_forget, which archives chat history and injects
    a system-authored recovery summary pointing at pad/knowledge/inbox.
    """
    err = _check_karma_gate(agent, "clear", args)
    if err:
        return err
    address = args["address"]
    resolved = args["_resolved_address"]
    if not _is_alive(resolved):
        return {"error": True, "message": f"Agent at {address} is not running"}
    # Content of .clear becomes the `source` tag in the recovery summary.
    # Default to the calling agent's name so targets can see who forced it.
    source = (args.get("reason") or "").strip() or agent.agent_name or "admin"
    (resolved / ".clear").write_text(source, encoding="utf-8")
    agent._log("karma_clear", target=address, source=source)
    return {"status": "cleared", "address": address, "source": source}


def _nirvana(agent, args: dict) -> dict:
    import shutil
    err = _check_karma_gate(agent, "nirvana", args)
    if err:
        return err
    address = args["address"]
    resolved = args["_resolved_address"]
    if _is_alive(resolved):
        # Write .suspend (not .sleep) so the process actually shuts down.
        # .sleep sets _asleep — heartbeat continues, is_alive() stays True,
        # and the wait loop below would always time out.
        # .suspend sets _shutdown — process terminates, heartbeat stops.
        (resolved / ".suspend").write_text("", encoding="utf-8")
        import time as _time
        deadline = _time.time() + 10.0
        while _time.time() < deadline:
            if not _is_alive(resolved):
                break
            _time.sleep(0.5)
        else:
            if _is_alive(resolved):
                return {"error": True, "message": f"Agent at {address} did not shut down within timeout"}
    shutil.rmtree(resolved)
    agent._log("karma_nirvana", target=address)
    return {"status": "nirvana", "address": address}
