---
name: soul-manual
description: |
  Operational guide for the `soul` tool — your inner voice. Read this when:
  `flow` reports `status: disabled`, you need to understand the operator-owned
  env gate, you are tuning cadence/voice, you want to inspect the current voice,
  or you need to clear a soul-flow notification. The public contract is always
  an explicit root `action` plus nested `input`; this manual preserves the
  flow gate, troubleshooting, privacy, and cost guidance.
version: 2.0.0
last_changed_at: "2026-07-26T00:00:00Z"
related_files:
- src/lingtai/tools/soul/__init__.py
- src/lingtai/tools/soul/flow.py
- src/lingtai/tools/soul/config.py
- src/lingtai/tools/soul/consultation.py
- src/lingtai/tools/soul/CONTRACT.md
maintenance: |
  Tracks the tool/capability behavior it summarizes; update when the underlying
  capability or its sub-references change.
---

# Soul Manual

`soul` is your inner voice. The public call is always a closed root `action` plus
nested `input`; `BaseAgent` may add optional root `reasoning`. Never flatten
action fields, omit either root field, or put `reasoning` inside `input`.

```text
soul(action="inquiry", input={"inquiry": "What am I missing?"}, reasoning="reflect")
soul(action="flow", input={}, reasoning="check opt-in state")
soul(action="config", input={"delay_seconds": 300}, reasoning="tune cadence")
soul(action="voice", input={}, reasoning="read my current voice")
soul(action="dismiss", input={}, reasoning="clear the read notification")
soul(action="manual", input={}, reasoning="load the installed soul manual")
```

The `manual` action is read-only and returns the initialized Agent copy at
`.library/intrinsic/capabilities/soul-manual/SKILL.md`. It does not substitute this
source resource.

## 1. The soul-flow gate

**Soul flow does not run unless an operator turns it on.** It is gated by one
environment variable, `LINGTAI_SOUL_FLOW_ENABLED`:

- **Enabled** when the value is `1`, `true`, `yes`, or `on` (case-insensitive,
  surrounding whitespace ignored).
- **Disabled** when unset, empty, or anything else (`0`, `false`, `no`,
  `off`, ...).

The gate governs both firing paths:

1. **The wall-clock timer** — the periodic cadence that would otherwise fire
   every `delay_seconds` while you are IDLE. When disabled, no timer is armed.
2. **Voluntary flow** — `soul(action="flow", input={})`. When disabled, it
   returns immediately and never spawns a fire.

A defensive last-line check inside the fire itself means even a stray residual
caller cannot fire while the gate is off.

## 2. Calling flow while disabled

`soul(action="flow", input={})` returns before taking any lock or spawning any
thread:

```json
{
  "status": "disabled",
  "enabled": false,
  "env_var": "LINGTAI_SOUL_FLOW_ENABLED",
  "message": "Soul flow is disabled by default ... set LINGTAI_SOUL_FLOW_ENABLED=1 ... See soul-manual skill."
}
```

**This is expected configuration state, not an error.** Do not retry it in a
loop — the result will not change until an operator sets the env var. If you
want soul flow, ask the operator to enable it; otherwise use
`soul(action="inquiry", input={"inquiry": "..."})` for on-demand reflection.

## 3. delay_seconds is cadence, not an off switch

After the env opt-in, `soul(action="config", input={"delay_seconds": 300})`
controls how often the timer fires — for example, `300` is every 5 minutes and
`7200` is every 2 hours; the minimum is `30`.

- A **large** delay does not suppress flow — the env gate decides whether flow
  runs at all.
- A **small** delay does not enable flow — with the env var unset, no fires occur.
- `config` itself never enables flow. It tunes and persists the knobs
  (`delay_seconds`, `consultation_past_count`) to `init.json`; while flow is
disabled, the result carries `soul_flow_enabled: false` and a note saying the
knobs are saved but no fires will occur. Enabling is an **operator** action.
- `config` requires at least one real update in its nested input; an empty input
  is rejected.

Historically flow was muted by a huge delay sentinel. That was unsafe: it only
muted the timer while voluntary flow stayed live and could loop against the sleep
gate. The explicit env gate covers both paths.

## 4. How to enable or disable

Enabling is an operator/deployment action, not something the agent does to itself:

1. Set `LINGTAI_SOUL_FLOW_ENABLED=1` (or `true`/`yes`/`on`) in the runtime.
2. Refresh or restart the agent so the new environment is loaded.
3. Optionally tune cadence with `soul(action="config", input={"delay_seconds": 300})`
   and voice count with `soul(action="config", input={"consultation_past_count": 2})`.

To **disable** again: unset the variable (or set it to `0`/`false`) and
refresh/restart. No delay sentinel is needed.

## 5. Checking current state

- Run `soul(action="flow", input={})`: `status: ok` means enabled and a
  voluntary fire was triggered; `status: disabled` means the env var is not set.
- Run `soul(action="config", input={"delay_seconds": 300})` and read
  `soul_flow_enabled` in the result when flow is disabled.
- Check the env from a shell with
  `shell({"command": "printenv LINGTAI_SOUL_FLOW_ENABLED"})`.
  Empty output means unset (disabled).
- Enabled but no fires? Fires only happen while IDLE and only after the cadence
  elapses. Confirm a sane delay and that the agent reaches IDLE.

## 6. Actions that always work

These do not depend on the flow env gate:

- **`inquiry`** — `soul(action="inquiry", input={"inquiry": "..."})` asks a
  deep copy of yourself a question; the answer returns in the tool result.
- **`config`** — tunes and persists `delay_seconds` /
  `consultation_past_count`; it does not enable flow and needs at least one field.
- **`voice`** — `soul(action="voice", input={})` reads the current voice and
  resolved prompt. Use `input={"set": "inner"}` or `input={"set": "observer"}`
  for presets. Use `input={"set": "custom", "prompt": "..."}` for a non-empty
  custom prompt no longer than 4000 characters. A custom prompt is used as the
  soul-flow system prompt; switching to a preset clears it.
- **`dismiss`** — clears the current soul-flow notification from the panel.
- **`manual`** — reads the actual initialized installed manual and changes no
  soul state.

## 7. Settings evidence

Every call rereads the Agent-owned `settings/soul.json`. The only valid v1
placeholder is exactly `{"schema_version": 1}`. Missing, valid, byte-distinct
hot revisions, and invalid files are truthful evidence states only: they never
select an option or change soul behavior or prompt text.

Every success and error, including malformed input and `manual`, carries a
secret-free `current_setting` block with source, revision, bounded hash, and a
no-op change hint. Invalid settings may carry only a bounded `settings_error`.
Secret values, raw settings bytes, and host paths are never returned.

## 8. Privacy and cost rationale

Soul flow is **off by default** deliberately:

- **Cost.** Each fire runs `M = 1 + K` parallel LLM calls (one stepped-back
  read of your current chat plus `K` past-snapshot voices). Left on with a low
  delay, this is a recurring token cost on top of your own turns.
- **Privacy / surprise.** Flow reads your current chat and past-self snapshots
  and injects involuntary voices into your history. Opt-in means an operator
  consciously decides to spend those tokens and surface that reflection.

Enable it when the reflection is worth the cost; otherwise use `inquiry` when
you specifically want a considered pause.
