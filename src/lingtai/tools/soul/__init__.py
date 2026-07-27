"""Soul intrinsic — the agent's inner voice.

Six actions (``inquiry``, ``flow``, ``config``, ``voice``, ``dismiss``,
``manual``), each a canonical :class:`~lingtai.tools.tool_family.ChildTool`
behind the one public ``soul`` family root. Per-action behavior, inputs, and
result/error shapes live in ``CONTRACT.md``; the model-facing text lives in the
schema descriptions below and in the ``soul-manual`` skill. Neither is restated
here.

Action separation is structural: :data:`_CHILD_SPECS` is the single registry of
name, schema, and handler, so the model-facing schema and dispatch are
generated from one source and cannot drift. The public tool name, action
values, semantics, receipts, and errors are exactly what they were before the
migration — only the argument *shape* moved from a flat root into ``action`` +
per-action ``input``.
"""
from __future__ import annotations

from typing import Any, Mapping

# Re-export constants from config.py
from lingtai.kernel.config import DEFAULT_SOUL_DELAY_SECONDS
from ..tool_family import ChildTool, ToolFamily
from ..tool_family.manual import build_manual_child
from .config import (
    SOUL_DELAY_MIN_SECONDS,
    CONSULTATION_PAST_COUNT_MIN,
    CONSULTATION_PAST_COUNT_MAX,
    SOUL_VOICE_BUILTINS,
    SOUL_VOICE_PROMPT_MAX,
)

# Re-export private helpers consumed by base_agent.py and tests
from .config import (
    _handle_config,
    _handle_voice,
    _persist_soul_config,
    _persist_soul_voice,
    _atomic_write_init,
    _build_soul_system_prompt,
)

# Re-export consultation pipeline
from .consultation import (
    _build_consultation_tool_refusal,
    _CONSULTATION_MAX_ROUNDS,
    _DIARY_CUE_TOKEN_CAP,
    _send_with_timeout,
    _render_current_diary,
    _write_soul_tokens,
    _load_snapshot_interface,
    _fit_interface_to_window,
    _kind_for_source,
    _build_consultation_cue,
    _run_consultation,
    _list_snapshot_paths,
    _run_consultation_batch,
    build_consultation_pair,
)

# Re-export inquiry
from .inquiry import soul_inquiry, _run_inquiry

# Re-export flow (soul cadence, fire, persistence, appendix tracking).
# These functions are the soul intrinsic's kernel-facing hook surface: after the
# tools consolidation the kernel resolves them through the injected intrinsic
# registry (``BaseAgent._intrinsic_hook("soul", ...)``) instead of importing
# them directly, since the kernel cannot import ``tools``.
from .flow import (
    _start_soul_timer,
    _cancel_soul_timer,
    _soul_whisper,
    _persist_soul_entry,
    _append_soul_flow_record,
    _flatten_v3_for_pair,
    _run_consultation_fire,
    _rehydrate_appendix_tracking,
)


# ---------------------------------------------------------------------------
# Canonical child input schemas — one strict, closed object per action.
# ---------------------------------------------------------------------------
#
# Each action's own ``input`` is declared exactly once here. ``ToolFamily``
# composes the model-facing schema and the dispatch allow-list from these same
# objects, so the two can never drift: the child's canonical name IS the public
# ``action`` value IS the dispatch key.
#
# The property descriptions are carried over verbatim from the pre-migration
# flat schema; only their location changed (flat root -> the one action that
# actually consumes them). That relocation is the whole point of the
# migration: ``inquiry`` no longer advertises ``delay_seconds``, and ``config``
# no longer advertises ``prompt``.

_INQUIRY_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "inquiry": {
            "type": "string",
            "description": "Your self-inquiry — a question to yourself. Required for action='inquiry'. This is you asking yourself a question, not prompting someone else.",
        },
    },
    "required": ["inquiry"],
    "additionalProperties": False,
}

# Flow takes no input. The env opt-in gate is the operator's, not the model's:
# there is deliberately no field here (and none anywhere in this family) that
# could enable flow from a tool call.
_FLOW_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {},
    "required": [],
    "additionalProperties": False,
}

# Both knobs are optional-but-at-least-one; strict provider schemas express
# optional fields as required nullable properties, and ``_strip_nulls`` turns a
# null back into "absent" before the existing validator sees it — so
# ``{delay_seconds: null, consultation_past_count: null}`` still produces the
# exact pre-migration "config requires at least one of ..." error.
_CONFIG_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "delay_seconds": {
            "type": ["number", "null"],
            "minimum": SOUL_DELAY_MIN_SECONDS,
            "description": "Wall-clock delay between soul flow fires, in seconds. This is ONLY the cadence AFTER soul flow is enabled via env LINGTAI_SOUL_FLOW_ENABLED=1 — it is NOT an off switch. If the env var is unset, soul flow is disabled entirely and NO fires occur regardless of this value (a large delay no longer even half-suppresses flow; the env gate does). Soul flow is your periodic inner reflection — when enabled and the timer fires, past versions of yourself (from molt snapshots) and a stepped-back read of your current work speak to you as voices, surfacing patterns, blind spots, and perspective you might miss while busy. Pass null when not setting it. Minimum 30s. Lower for more frequent reflection (e.g. 300 = every 5 minutes; 7200 = every 2 hours). When flow is enabled, the currently-pending fire is cancelled and the timer restarts on the new schedule. See soul-manual skill.",
        },
        "consultation_past_count": {
            "type": ["integer", "null"],
            "minimum": CONSULTATION_PAST_COUNT_MIN,
            "maximum": CONSULTATION_PAST_COUNT_MAX,
            "description": "K — number of past-self voices sampled per fire. Pass null when not setting it. Each fire runs M=1+K parallel LLM calls (1 stepped-back diary reader + K random past-snapshot voices). Range [0, 5]. 0 = insights-only fires (cheapest, no past-self voices). Higher K is costlier per fire and fills more chat-history with voice content; lower K is faster and quieter. At least one of delay_seconds/consultation_past_count must be non-null.",
        },
    },
    "required": ["delay_seconds", "consultation_past_count"],
    "additionalProperties": False,
}

_VOICE_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "set": {
            "type": ["string", "null"],
            "description": "Which voice profile to switch to. Built-ins: 'inner' (terse — 'you are the soul, speak as inner voice') or 'observer' (structured stepped-back hook framing). Or 'custom', which requires a 'prompt' field with your own system-prompt text. Pass null to read the current voice and resolved prompt without changing anything.",
        },
        "prompt": {
            "type": ["string", "null"],
            "maxLength": SOUL_VOICE_PROMPT_MAX,
            "description": "Custom system prompt for soul-flow voice. Required when set='custom'; ignored otherwise. Length capped at 4000 characters. Speak to yourself as the soul — describe how you want to be framed when reading your own diary. The same prompt is used for both insights (current self) and past (frozen earlier self) consultations; the per-fire cue text differentiates whose diary you're reading.",
        },
    },
    "required": ["set", "prompt"],
    "additionalProperties": False,
}

_DISMISS_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {},
    "required": [],
    "additionalProperties": False,
}

# The one canonical child registry: name, canonical input schema, and the
# factory producing that child's agent-bound handler. Declaring names, order,
# schemas, and handlers in a single place is what makes schema-vs-dispatch
# drift structurally impossible — there is no second list to forget to update,
# so a child can never be schema-advertised but dispatch-rejected. Order here is
# the model-facing ``action`` enum order and the ``input.oneOf`` branch order,
# unchanged from the pre-migration flat schema.
#
# ``manual`` is absent: ``build_manual_child`` owns that child's schema and
# handler, and :func:`_build_children` appends it last.
_CHILD_SPECS: tuple[tuple[str, dict[str, Any], Any], ...] = (
    ("inquiry", _INQUIRY_INPUT_SCHEMA,
     lambda agent: lambda i: _handle_inquiry(agent, _strip_nulls(i))),
    ("flow", _FLOW_INPUT_SCHEMA,
     lambda agent: lambda _i: _handle_flow(agent)),
    ("config", _CONFIG_INPUT_SCHEMA,
     lambda agent: lambda i: _handle_config(agent, _strip_nulls(i))),
    ("voice", _VOICE_INPUT_SCHEMA,
     lambda agent: lambda i: _handle_voice(agent, _strip_nulls(i))),
    ("dismiss", _DISMISS_INPUT_SCHEMA,
     lambda agent: lambda _i: _handle_dismiss(agent)),
)


def _build_children(agent) -> list[ChildTool]:
    """Build the six children from the one canonical registry.

    ``agent`` may be ``None`` for the module-level schema-only family, whose
    children are never dispatched — only their schemas are read.
    """
    return [
        ChildTool(name, schema, make_handler(agent), title=f"{name} input")
        for name, schema, make_handler in _CHILD_SPECS
    ] + [build_manual_child(agent, "soul-manual")]


# Composes the model-facing schema. Building it at import time is also the
# registry's duplicate/reserved-name collision check: a collision raises
# ``ToolFamilyError`` here rather than shipping silently. It never dispatches —
# soul is an intrinsic *module*, not a per-Agent manager object, so there is no
# instance to hang a family off; ``handle()`` binds one to the passed agent per
# call from this same registry.
_FAMILY = ToolFamily("soul", _build_children(None))


def get_description(lang: str = "en") -> str:
    return "Your inner voice. One tool, six actions, each with its own strict input object: soul(action=..., input={...}, reasoning='why'). flow is OPT-IN and DISABLED by default: it runs only when the operator sets env LINGTAI_SOUL_FLOW_ENABLED=1 (then refreshes). While disabled, soul(action='flow', input={}) returns status='disabled' (not an error — do not retry); inquiry/config/voice/dismiss still work. When enabled, flow fires periodic past-self consultation every soul_delay seconds while IDLE — M=1+K parallel LLM calls (1 stepped-back read of current chat + K past-snapshot voices) arrive as an involuntary soul(action='flow') pair. delay_seconds is only the cadence after opt-in, NOT an off switch, and no action in this family can enable flow. inquiry: ask a deep copy of yourself a question; answer returns in the tool result. config: tune flow knobs at runtime (delay_seconds, consultation_past_count) — does not enable flow. voice: read or choose how your own soul-flow voice sounds. dismiss: clear the current flow notification. manual: return the installed soul-manual skill without performing any soul operation. Results are small, so leave root summarize false (short-result profile); call manual with summarize=false so the exact procedure is not summarized away. See soul-manual for details."


def get_schema(lang: str = "en") -> dict:
    # Composed by the generic ToolFamily infra from each child's own canonical
    # ``input_schema`` above, rather than hand-assembled: root ``action`` +
    # per-action ``input`` + required ``reasoning`` + optional ``summarize``,
    # with a root ``allOf`` correlating each ``action`` const to that exact
    # action's ``input`` shape on both the Chat and Responses wires.
    return _FAMILY.build_schema()


def _strip_nulls(action_input: Mapping[str, Any]) -> dict[str, Any]:
    """Drop explicit nulls so "absent" and "null" mean the same downstream.

    Strict provider schemas express an optional field as a REQUIRED nullable
    property, so the model must send ``{"set": null, "prompt": null}`` for a
    bare voice read. The pre-migration handlers keyed off ``"x" in args`` /
    ``args.get("set") is None``; stripping nulls here reproduces that exact
    behavior — including ``config``'s "at least one knob" error when both
    knobs are null — without touching the validators themselves.
    """
    return {key: value for key, value in action_input.items() if value is not None}


def _adapt_manual_result(mcp_result: dict) -> dict:
    """Flatten the reserved ``manual`` child's canonical result to soul's shape.

    The reserved child is registered unwrapped, so ``ToolFamily.handle()``
    returns its canonical ``content``/``structuredContent`` result verbatim.
    Soul's public manual result predates that generic contract and must stay
    the flat ``status``/``manual``/``manual_path`` shape, so this Host-owned
    adapter runs strictly *after* dispatch — never inside the child, and never
    as a second envelope around it.
    """
    flat: dict = {
        "status": mcp_result.get("status", "ok"),
        "manual": mcp_result["content"][0]["text"],
        "manual_path": mcp_result["structuredContent"]["manual_path"],
    }
    if "error" in mcp_result:
        flat["error"] = mcp_result["error"]
    return flat


def _handle_flow(agent) -> dict:
    """``action='flow'`` — trigger one voluntary consultation fire.

    Relocated verbatim from the pre-migration ``handle`` if-chain; the gate,
    lock, thread, and payloads below are unchanged.
    """
    # Opt-in gate: soul flow is disabled by default. When disabled,
    # return an explicit, stable "disabled" status BEFORE touching the
    # lock or spawning a fire thread — so a disabled agent burns no
    # thread and does not wait for IDLE. This is expected config state,
    # not an error to retry (see soul-manual).
    from .flow import _soul_flow_enabled, SOUL_FLOW_ENABLED_ENV
    if not _soul_flow_enabled():
        agent._log("soul_flow_voluntary_disabled")
        return {
            "status": "disabled",
            "enabled": False,
            "env_var": SOUL_FLOW_ENABLED_ENV,
            "message": (
                "Soul flow is disabled by default on this agent. It is "
                "opt-in: set the environment variable "
                f"{SOUL_FLOW_ENABLED_ENV}=1 (also true/yes/on), then "
                "refresh/restart, to enable periodic and voluntary "
                "past-self consultation. delay_seconds is only the "
                "cadence AFTER this opt-in — it is not an off switch, "
                "and soul(action='config') does not enable flow. "
                "inquiry, config, voice, and dismiss remain available "
                "while flow is disabled. Do not retry flow blindly; the "
                "operator must set the env var first. See soul-manual "
                "skill for how to enable/disable, troubleshoot, and the "
                "privacy/cost rationale."
            ),
        }

    # Voluntary trigger: try-acquire the fire lock non-blocking. If
    # held, another fire is already in flight (timer-fired or a prior
    # voluntary call) — refuse so the agent isn't surprised by a
    # silent no-op. If free, release immediately and kick off the
    # real fire on a daemon thread; _run_consultation_fire will
    # re-acquire under the same gate.
    lock = getattr(agent, "_soul_fire_lock", None)
    if lock is not None:
        if not lock.acquire(blocking=False):
            agent._log("soul_flow_voluntary_rejected", reason="ongoing")
            return {"error": "soul flow ongoing, request rejected"}
        lock.release()

    import threading
    from .flow import _run_consultation_fire

    def _fire():
        try:
            # Wait for IDLE before firing — voluntary flow is triggered
            # while ACTIVE (inside a tool call), but _run_consultation_fire
            # gates on IDLE.  _idle is a threading.Event set on every
            # non-ACTIVE transition (see base_agent._set_state).
            idle_event = getattr(agent, "_idle", None)
            if idle_event is not None:
                agent._log("soul_flow_voluntary_waiting_idle")
                # Wait up to soul_delay seconds; if the agent never goes
                # IDLE (stuck in ACTIVE), give up rather than hang.
                timeout = getattr(agent, "_soul_delay", DEFAULT_SOUL_DELAY_SECONDS)
                if not idle_event.wait(timeout=timeout):
                    agent._log("soul_flow_voluntary_timeout",
                               timeout=timeout)
                    return
            _run_consultation_fire(agent)
        except Exception as e:
            try:
                agent._log("soul_flow_voluntary_error", error=str(e)[:200])
            except Exception:
                pass

    t = threading.Thread(target=_fire, daemon=True, name="soul-flow-voluntary")
    t.start()
    agent._log("soul_flow_voluntary_triggered")
    return {
        "status": "ok",
        "message": (
            "Soul flow triggered. Voices will arrive shortly as a "
            "separate soul(action='flow') tool-call pair appended to "
            "your chat history (replacing any prior soul-flow pair)."
        ),
    }


def _handle_inquiry(agent, action_input: Mapping[str, Any]) -> dict:
    """``action='inquiry'`` — sync mirror session; requires inquiry text."""
    inquiry = action_input.get("inquiry", "")
    if not isinstance(inquiry, str) or not inquiry.strip():
        return {"error": "inquiry is required — what do you want to reflect on?"}

    agent._log("soul_inquiry", inquiry=inquiry.strip()[:200])

    result = soul_inquiry(agent, inquiry.strip())

    if result:
        agent._persist_soul_entry(result, mode="inquiry")
        agent._log("soul_inquiry_done")
        return {"status": "ok", "voice": result["voice"]}
    else:
        agent._log("soul_inquiry_done")
        return {"status": "ok", "voice": "(silence)"}


def _handle_dismiss(agent) -> dict:
    """``action='dismiss'`` — clear the current soul flow notification."""
    from lingtai.kernel.notifications import dismiss_channel
    result = dismiss_channel(agent, "soul", invoked_by="soul")
    if result.get("status") == "ok":
        result.setdefault("message", "Soul flow notification dismissed.")
    return result


def handle(agent, args: dict) -> dict:
    """Handle the ``soul`` family root — validate the envelope, dispatch one action.

    Envelope validation and cross-action rejection belong to the generic
    dispatcher (``tool_family/CONTRACT.md``). This function owns only what is
    soul-specific: dropping ``_tc_id``, and the two post-dispatch presentation
    adaptations below.
    """
    raw = dict(args or {})
    # ``base_agent._dispatch_tool`` injects the wire ``_tc_id`` into EVERY
    # intrinsic's args (capabilities like ``web`` never see it). It is kernel
    # transport metadata, not a public root field and not action input, so it
    # is dropped here before the envelope's closed-root check — soul does not
    # consume it.
    raw.pop("_tc_id", None)

    action = raw.get("action")
    result = ToolFamily("soul", _build_children(agent)).handle(raw)

    if action == "manual" and "content" in result:
        return _adapt_manual_result(result)
    if result.get("error_code") == "ACTION_REQUIRED":
        # Preserve soul's pre-migration unknown-action error verbatim.
        return {
            "error": (
                f"Unknown soul action: {action if action is not None else ''}. "
                "Use inquiry, config, voice, dismiss, "
                "manual, or wait for flow (mechanical)."
            )
        }
    return result
