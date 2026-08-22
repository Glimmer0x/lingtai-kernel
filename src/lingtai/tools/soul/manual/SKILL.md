---
name: soul-manual
description: |
  Operational guide for the `soul` tool — your inner voice: the one-tool/six-actions call shape, the `LINGTAI_SOUL_FLOW_ENABLED` opt-in gate, disabled-flow behavior, and the delay-is-cadence-not-an-off-switch semantics. Read it before calling `flow`, tuning `config`, or troubleshooting a `status: disabled` result.
version: 1.3.0
last_changed_at: "2026-08-22T00:00:00Z"
related_files:
- src/lingtai/tools/soul/__init__.py
- src/lingtai/tools/soul/plugin.py
- src/lingtai/tools/_plugin.py
- src/lingtai/tools/soul/ANATOMY.md
- src/lingtai/tools/soul/CONTRACT.md
- src/lingtai/tools/CONTRACT.md
- src/lingtai/tools/soul/flow.py
- src/lingtai/tools/soul/config.py
- src/lingtai/tools/soul/consultation.py
maintenance: |
  Tracks the tool/capability behavior it teaches; update when that tool's behavior changes.
---

# Soul Manual

`soul` is your inner voice. `inquiry`, `config`, `voice`, `dismiss`, and
`manual` are **always available**. `flow` is **opt-in and disabled by default**.

## 0. How to call it

One tool, six actions. Every call is `action` + that action's own strict `input`
object + `reasoning`; another action's field is rejected before anything runs:

```json
{"action": "inquiry", "input": {"inquiry": "What am I avoiding?"}, "reasoning": "check my own blind spot"}
```

| Action | `input` |
|---|---|
| `inquiry` | `{"inquiry": "<your question>"}` — required, non-empty |
| `flow` | `{}` |
| `config` | `{"delay_seconds": <num or null>, "consultation_past_count": <int or null>}` — at least one non-null |
| `voice` | `{"set": <profile or null>, "prompt": <text or null>}` — both null = read |
| `dismiss` | `{}` |
| `manual` | `{}` |

Optional fields are declared nullable rather than omittable, so pass `null` for
the ones you are not setting.

**`summarize`** is a root-level boolean (never inside `input`). Soul's results
are all small, and summarizing risks losing a voice's exact wording — leave it
false, especially for `manual`.

## 1. The soul-flow gate

**Soul flow does not run unless an operator turns it on.** It is gated by one
environment variable, `LINGTAI_SOUL_FLOW_ENABLED`:

- **Enabled** when the value is `1`, `true`, `yes`, or `on` (case-insensitive,
  surrounding whitespace ignored).
- **Disabled** when unset, empty, or anything else (`0`, `false`, `no`,
  `off`, ...).

The gate governs **both** firing paths:

1. **The wall-clock timer** — the periodic cadence that would otherwise fire
   every `delay_seconds` while you are IDLE. When disabled, no timer is armed.
2. **Voluntary `soul(action='flow', input={})`** — a call you make yourself. When
   disabled, it returns immediately and never spawns a fire.

A defensive last-line check inside the fire itself means even a stray residual
caller cannot fire while the gate is off.

## 2. Calling `flow` while disabled

`soul(action='flow', input={})` returns, **before** taking any lock or spawning any
thread:

```json
{"status": "disabled", "enabled": false, "env_var": "LINGTAI_SOUL_FLOW_ENABLED", "message": "..."}
```

**This is expected configuration state, not an error.** Do **not** retry it in
a loop — the result will not change until an operator sets the env var. If you
want soul flow, ask the operator to enable it (§4); otherwise use `inquiry` for
on-demand self-reflection.

## 3. `delay_seconds` is cadence, not an off switch

After the env opt-in, `delay_seconds` (set via
`soul(action='config', input={'delay_seconds': ..., 'consultation_past_count': null})`) controls **how often** the timer
fires — e.g. `300` = every 5 minutes, `7200` = every 2 hours; minimum `30`.
That is *all* it does:

- A **large** `delay_seconds` does not suppress flow — the env gate decides
  whether flow runs at all.
- A **small** `delay_seconds` does not enable flow — with the env var unset, no
  fires occur regardless of the delay.
- `config` itself never enables flow. It tunes and persists the knobs
  (`delay_seconds`, `consultation_past_count`) to `init.json`; while flow is
  disabled the result carries `soul_flow_enabled: false` and a `note` saying the
  knobs are saved but no fires will occur. Enabling is an **operator** action.

`delay_seconds` is cadence only. A huge sentinel value (e.g. `999999999`) used to
be the trust-based mute, but it silenced only the **timer** — the voluntary path
stayed live and could loop against the sleep gate. The env gate replaced that
fragile convention with an explicit opt-in covering both paths.

## 4. How to enable / disable

Enabling is an operator/deployment action, not something the agent does to
itself:

1. Set `LINGTAI_SOUL_FLOW_ENABLED=1` (or `true`/`yes`/`on`) in the agent's
   runtime environment.
2. Refresh/restart the agent so the new environment is loaded.
3. (Optional) tune cadence and voice count with
   `soul(action='config', input={'delay_seconds': 300, 'consultation_past_count': 2})`.

To **disable** again: unset the variable (or set it to `0`/`false`) and
refresh/restart. No `delay_seconds` sentinel is needed — the gate is the off
switch.

## 5. Checking the current state

- **Is flow enabled right now?** `soul(action='config', input={...})` reports
  `soul_flow_enabled` (or see the `flow` status in §2).
- **Check the env from a shell:**
  `shell({"command": "printenv LINGTAI_SOUL_FLOW_ENABLED"})` — empty output
  means unset (disabled).
- **Enabled but no fires?** Fires only happen while you are IDLE and only after
  `delay_seconds` elapses. Confirm `delay_seconds` is a small, sane value and
  that you actually reach IDLE between turns.

## 6. Actions that always work (flow disabled or not)

None of these depend on the env gate.

- **`inquiry`** — ask a deep copy of yourself a question; the answer returns in
  the tool result. Use this for deliberate, on-demand self-reflection instead
  of waiting on flow. Requires the `inquiry` field.
- **`config`** — tune `delay_seconds` / `consultation_past_count`; persists to
  `init.json`. (Does not enable flow — see §3.)
- **`voice`** — read or set how your own soul-flow voice sounds
  (`inner`/`observer`/`custom`). Yours to choose; persists to `init.json`.
- **`dismiss`** — clear the current soul-flow notification from the panel.
- **`manual`** — return this manual. Reads one file and performs **no** soul
  operation: no timer change, no consultation, no config/voice/notification
  write.

## 7. Settings files

`soul` has **no** settings file at either LTP level — there is no
`settings/soul.json` and no `settings/soul.<action>.json`. Cadence and voice
live in `init.json` under `manifest.soul` (written by `config`/`voice`), and
the flow gate lives in the process environment. Nothing here reads a
`settings/` file.

## 8. Privacy and cost rationale

Soul flow is **off by default** because each fire runs `M = 1 + K` parallel LLM
calls — a recurring silent token cost — and because it reads your current chat
and past-self snapshots to inject involuntary voices into your history. Opt-in
means an operator consciously decides to spend those tokens and surface that
reflection. Enable it when the reflection is worth the cost; otherwise reach for
`inquiry` when you specifically want a considered pause.
