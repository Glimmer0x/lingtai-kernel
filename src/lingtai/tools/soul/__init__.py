"""Soul intrinsic — the agent's inner voice.

Six public actions use a strict root ``action`` plus nested ``input`` contract:
    flow    — opt-in past-self consultation appendix. Every ``_soul_delay`` seconds,
              fires M=1+K parallel LLM calls (1 stepped-back read of the
              current chat as "insights", K random past-snapshot
              consultations sampled from history/snapshots/). Voices are
              written to ``.notification/soul.json`` via
              ``publish_notification``; the kernel's ``_sync_notifications``
              picks up the fingerprint change and surfaces them inside the
              single-slot synthesized ``notification(action="check")`` wire
              pair. Mechanical and opt-in.
    inquiry — sync mirror session. Clones conversation (text+thinking only),
              sends question, returns answer in tool result. On-demand.
    config  — adjust soul flow knobs. Accepts any subset of two optional
              fields: delay_seconds (wall-clock cadence), consultation_past_count
              (K, number of past-self voices per fire). Updates live state,
              restarts the wall-clock timer if delay changed, persists to
              init.json.
    voice   — read or select the soul-flow voice profile. ``set`` is optional
              for read-current; ``custom`` requires its prompt.
    dismiss — clear the current soul-flow notification.
    manual  — return the initialized Agent copy of the installed soul manual.

The raw schema is deliberately closed and owns no ``reasoning`` field. BaseAgent
adds optional root reasoning to the Agent-facing FunctionSchema; the executor
may carry it internally as ``_reasoning``.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

# Re-export constants from config.py
from lingtai.kernel.config import DEFAULT_SOUL_DELAY_SECONDS
from .._manual import load_installed_manual
from .._settings import current_setting, read_settings
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


_ACTION_FIELDS: dict[str, tuple[str, ...]] = {
    "inquiry": ("inquiry",),
    "flow": (),
    "config": ("delay_seconds", "consultation_past_count"),
    "voice": ("set", "prompt"),
    "dismiss": (),
    "manual": (),
}
# ``_tc_id`` is injected by the intrinsic dispatch route.  ``reasoning`` is
# accepted for direct in-process Agent calls; BaseAgent strips it and supplies
# ``_reasoning`` for normal executor routing.  None of these are public raw
# schema fields.
_ALLOWED_ROOT_FIELDS = ("action", "input", "reasoning", "_reasoning", "_tc_id")


def get_description(lang: str = "en") -> str:
    return (
        "Your inner voice. The public call is always soul(action=..., input={...}, "
        "reasoning='...') with explicit action and nested input; BaseAgent injects "
        "optional root reasoning and reasoning is never nested in input. flow is "
        "OPT-IN and DISABLED by default: it runs only when the operator sets env "
        "LINGTAI_SOUL_FLOW_ENABLED=1 (then refreshes). While disabled, "
        "soul(action='flow', input={}) returns status='disabled' (not an error — do "
        "not retry); inquiry/config/voice/dismiss still work. When enabled, flow "
        "fires periodic past-self consultation every soul_delay seconds while IDLE — "
        "M=1+K parallel LLM calls (1 stepped-back read of current chat + K "
        "past-snapshot voices) arrive as an involuntary soul(action='flow', input={}) "
        "pair. delay_seconds is only the cadence after opt-in, NOT an off switch. "
        "inquiry: use soul(action='inquiry', input={'inquiry': '...'}) to ask a deep "
        "copy of yourself a question; answer returns in the tool result. You may "
        "ALSO invoke flow voluntarily while ACTIVE: the call returns immediately "
        "with a success acknowledgement, and the actual voices arrive shortly "
        "after as a separate involuntary soul(action='flow', input={}) pair. If a "
        "fire is already running when you invoke, the call is rejected with "
        "'soul flow ongoing, request rejected' — wait for the current fire to land, "
        "then try again. config: tune flow knobs at runtime with "
        "soul(action='config', input={'delay_seconds': 300}) or "
        "soul(action='config', input={'consultation_past_count': 2}) — it does not "
        "enable flow and at least one field is required. delay_seconds is wall-clock "
        "cadence after opt-in (minimum 30s), never an off switch. voice: use "
        "soul(action='voice', input={}) to read the current voice + resolved prompt. "
        "Pass input={'set': 'inner'} or input={'set': 'observer'} to switch presets. "
        "Pass input={'set': 'custom', 'prompt': '...'} with a non-empty custom "
        "system-prompt text to write your own soul-flow voice; the prompt is capped "
        "at 4000 characters and used for both insights and past consultations. "
        "dismiss: soul(action='dismiss', input={}) clears the current flow "
        "notification. manual: soul(action='manual', input={}) returns the real "
        "initialized Agent copy of the installed soul manual without changing soul "
        "state. See soul-manual for enabling/disabling, troubleshooting, and the "
        "privacy/cost rationale."
    )


def _input_branch(title: str, properties: dict[str, dict[str, Any]], required: list[str]) -> dict[str, Any]:
    return {
        "title": title,
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def get_schema(lang: str = "en") -> dict:
    """Return the raw closed action/input schema.

    The root is exactly ``action`` and ``input`` and both are required.  The
    nested ``anyOf`` branches are strict action-owned objects; BaseAgent alone
    adds optional root ``reasoning`` to its Agent-facing FunctionSchema.
    """
    return {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["inquiry", "flow", "config", "voice", "dismiss", "manual"],
                "description": "Required operation: inquiry, flow, config, voice, dismiss, or manual.",
            },
            "input": {
                "description": "Strict action-specific soul input; no nested reasoning field.",
                "anyOf": [
                    _input_branch(
                        "inquiry input",
                        {
                            "inquiry": {
                                "type": "string",
                                "description": "Your self-inquiry — a question to yourself. Required for action='inquiry'. This is you asking yourself a question, not prompting someone else.",
                            },
                        },
                        ["inquiry"],
                    ),
                    _input_branch("flow input", {}, []),
                    _input_branch(
                        "config input",
                        {
                            "delay_seconds": {
                                "type": "number",
                                "minimum": SOUL_DELAY_MIN_SECONDS,
                                "description": "Wall-clock delay between soul flow fires, in seconds. This is ONLY the cadence AFTER soul flow is enabled via env LINGTAI_SOUL_FLOW_ENABLED=1 — it is NOT an off switch. If the env var is unset, soul flow is disabled entirely and NO fires occur regardless of this value. Minimum 30s. When flow is enabled, the currently-pending fire is cancelled and the timer restarts on the new schedule.",
                            },
                            "consultation_past_count": {
                                "type": "integer",
                                "minimum": CONSULTATION_PAST_COUNT_MIN,
                                "maximum": CONSULTATION_PAST_COUNT_MAX,
                                "description": "K — number of past-self voices sampled per fire. Optional for action='config'. Each fire runs M=1+K parallel LLM calls (1 stepped-back diary reader + K random past-snapshot voices). Range [0, 5]. 0 = insights-only fires (cheapest, no past-self voices). Higher K is costlier per fire and fills more chat-history with voice content; lower K is faster and quieter.",
                            },
                        },
                        [],
                    ),
                    _input_branch(
                        "voice input",
                        {
                            "set": {
                                "type": "string",
                                "description": "Which voice profile to switch to. For action='voice'. Built-ins: 'inner' (terse — 'you are the soul, speak as inner voice') or 'observer' (structured stepped-back hook framing). Or 'custom', which requires a 'prompt' field with your own system-prompt text. Omit 'set' to read the current voice and resolved prompt without changing anything.",
                            },
                            "prompt": {
                                "type": "string",
                                "maxLength": SOUL_VOICE_PROMPT_MAX,
                                "description": "Custom system prompt for soul-flow voice. Required when set='custom'; ignored otherwise. Length capped at 4000 characters. Speak to yourself as the soul — describe how you want to be framed when reading your own diary. The same prompt is used for both insights (current self) and past (frozen earlier self) consultations; the per-fire cue text differentiates whose diary you're reading.",
                            },
                        },
                        [],
                    ),
                    _input_branch("dismiss input", {}, []),
                    _input_branch("manual input", {}, []),
                ],
            },
        },
        "required": ["action", "input"],
        "additionalProperties": False,
    }


def _with_setting(result: Any, diagnostic: dict[str, Any]) -> dict[str, Any]:
    """Attach one fresh, secret-free settings diagnostic to every result."""
    if isinstance(result, Mapping):
        value = dict(result)
    else:
        value = {"error": "soul action returned an invalid result"}
    value["current_setting"] = dict(diagnostic)
    return value


def _error(message: str, diagnostic: dict[str, Any]) -> dict:
    return _with_setting({"error": message}, diagnostic)


def _mapping_keys(value: Mapping) -> tuple[list[Any], str | None]:
    """Read mapping keys without hashing untrusted keys."""
    try:
        keys = list(value.keys())
    except Exception:
        return [], "mapping keys could not be read"
    if any(not isinstance(key, str) for key in keys):
        return keys, "mapping keys must be strings"
    return keys, None


def handle(agent, args: Any) -> dict:
    """Validate and dispatch one canonical soul action.

    Validation is deliberately performed before any soul service seam.  The
    settings placeholder is evidence-only and is reread for every call,
    including malformed, manual, and service-error paths.
    """
    snapshot = read_settings(agent, "soul")
    diagnostic = current_setting(snapshot, "soul")

    if not isinstance(args, Mapping):
        return _error("soul arguments must be an object", diagnostic)
    root_keys, root_error = _mapping_keys(args)
    if root_error:
        return _error(f"soul {root_error}", diagnostic)
    if any(key not in _ALLOWED_ROOT_FIELDS for key in root_keys):
        return _error("soul accepts only root action, input, and Agent reasoning metadata", diagnostic)
    if "action" not in root_keys or "input" not in root_keys:
        return _error("soul requires root action and input", diagnostic)

    try:
        action = args["action"]
        raw_input = args["input"]
    except Exception:
        return _error("soul arguments are malformed", diagnostic)
    if type(action) is not str or action not in _ACTION_FIELDS:
        return _error(
            f"Unknown soul action: {action}. Use inquiry, flow, config, voice, "
            "dismiss, or manual.",
            diagnostic,
        )
    if not isinstance(raw_input, Mapping):
        return _error("soul input must be an object", diagnostic)
    nested_keys, nested_error = _mapping_keys(raw_input)
    if nested_error:
        return _error(f"soul input {nested_error}", diagnostic)
    try:
        action_input = dict(raw_input)
    except Exception:
        return _error("soul input must be an object", diagnostic)
    allowed_fields = _ACTION_FIELDS[action]
    if any(key not in allowed_fields for key in nested_keys):
        return _error(f"unsupported soul input field for action {action!r}", diagnostic)

    if action in ("flow", "dismiss", "manual") and action_input:
        return _error(f"{action} input must be an empty object", diagnostic)

    # Root reasoning is optional Agent metadata.  The raw schema does not own
    # it, and nested input has already rejected any reasoning key.
    try:
        reasoning = args.get("_reasoning")
        if reasoning is None:
            reasoning = args.get("reasoning")
    except Exception:
        reasoning = None
    if reasoning is not None and not isinstance(reasoning, str):
        return _error("reasoning must be a string", diagnostic)

    dispatch_args = dict(action_input)
    dispatch_args["_reasoning"] = reasoning
    try:
        if action == "manual":
            # Preserve the existing installed-manual result shape; the public
            # action is represented by the call, not fabricated result fields.
            result = load_installed_manual(agent, "soul-manual")
        elif action == "flow":
            # The existing flow branch remains untouched semantically; the
            # opt-in gate returns before lock/thread work.
            from .flow import _soul_flow_enabled, SOUL_FLOW_ENABLED_ENV
            if not _soul_flow_enabled():
                agent._log("soul_flow_voluntary_disabled")
                result = {
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
                        "and config does not enable flow. "
                        "inquiry, config, voice, and dismiss remain available "
                        "while flow is disabled. Do not retry flow blindly; the "
                        "operator must set the env var first. See soul-manual "
                        "skill for how to enable/disable, troubleshoot, and the "
                        "privacy/cost rationale."
                    ),
                }
            else:
                lock = getattr(agent, "_soul_fire_lock", None)
                if lock is not None:
                    if not lock.acquire(blocking=False):
                        agent._log("soul_flow_voluntary_rejected", reason="ongoing")
                        result = {"error": "soul flow ongoing, request rejected"}
                    else:
                        lock.release()
                        import threading
                        from .flow import _run_consultation_fire

                        def _fire():
                            try:
                                idle_event = getattr(agent, "_idle", None)
                                if idle_event is not None:
                                    agent._log("soul_flow_voluntary_waiting_idle")
                                    timeout = getattr(agent, "_soul_delay", DEFAULT_SOUL_DELAY_SECONDS)
                                    if not idle_event.wait(timeout=timeout):
                                        agent._log("soul_flow_voluntary_timeout", timeout=timeout)
                                        return
                                _run_consultation_fire(agent)
                            except Exception as exc:
                                try:
                                    agent._log("soul_flow_voluntary_error", error=str(exc)[:200])
                                except Exception:
                                    pass

                        t = threading.Thread(target=_fire, daemon=True, name="soul-flow-voluntary")
                        t.start()
                        agent._log("soul_flow_voluntary_triggered")
                        result = {
                            "status": "ok",
                            "message": (
                                "Soul flow triggered. Voices will arrive shortly as a "
                                "separate soul(action='flow', input={}) tool-call pair "
                                "appended to your chat history (replacing any prior "
                                "soul-flow pair)."
                            ),
                        }
                # Preserve the historical direct-call behavior when a tiny
                # fake Agent has no fire lock: the fire routine owns its own
                # defensive gating and the voluntary acknowledgement remains
                # immediate.
                else:
                    import threading
                    from .flow import _run_consultation_fire

                    def _fire_without_lock():
                        try:
                            idle_event = getattr(agent, "_idle", None)
                            if idle_event is not None:
                                agent._log("soul_flow_voluntary_waiting_idle")
                                timeout = getattr(agent, "_soul_delay", DEFAULT_SOUL_DELAY_SECONDS)
                                if not idle_event.wait(timeout=timeout):
                                    agent._log("soul_flow_voluntary_timeout", timeout=timeout)
                                    return
                            _run_consultation_fire(agent)
                        except Exception as exc:
                            try:
                                agent._log("soul_flow_voluntary_error", error=str(exc)[:200])
                            except Exception:
                                pass

                    t = threading.Thread(target=_fire_without_lock, daemon=True, name="soul-flow-voluntary")
                    t.start()
                    agent._log("soul_flow_voluntary_triggered")
                    result = {
                        "status": "ok",
                        "message": (
                            "Soul flow triggered. Voices will arrive shortly as a "
                            "separate soul(action='flow', input={}) tool-call pair "
                            "appended to your chat history (replacing any prior "
                            "soul-flow pair)."
                        ),
                    }
        elif action == "inquiry":
            inquiry = action_input.get("inquiry", "")
            if not isinstance(inquiry, str) or not inquiry.strip():
                result = {"error": "inquiry is required — what do you want to reflect on?"}
            else:
                agent._log("soul_inquiry", inquiry=inquiry.strip()[:200])
                inquiry_result = soul_inquiry(agent, inquiry.strip())
                if inquiry_result:
                    agent._persist_soul_entry(inquiry_result, mode="inquiry")
                    agent._log("soul_inquiry_done")
                    result = {"status": "ok", "voice": inquiry_result["voice"]}
                else:
                    agent._log("soul_inquiry_done")
                    result = {"status": "ok", "voice": "(silence)"}
        elif action == "config":
            result = _handle_config(agent, dispatch_args)
        elif action == "voice":
            result = _handle_voice(agent, dispatch_args)
        elif action == "dismiss":
            from lingtai.kernel.notifications import dismiss_channel
            result = dismiss_channel(agent, "soul", invoked_by="soul")
            if result.get("status") == "ok":
                result.setdefault("message", "Soul flow notification dismissed.")
        else:  # pragma: no cover - action membership above is exhaustive.
            result = {"error": f"Unknown soul action: {action!r}"}
    except Exception:
        # Keep service and prompt details out of model-visible results while
        # preserving the pre-existing result contract for successful paths.
        result = {"error": "soul action failed"}
    return _with_setting(result, diagnostic)
