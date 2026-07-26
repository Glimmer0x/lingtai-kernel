---
name: soul-contract
tool: soul
contract_version: 2
related_files:
  - src/lingtai/tools/soul/__init__.py
  - src/lingtai/tools/soul/config.py
  - src/lingtai/tools/soul/flow.py
  - src/lingtai/tools/soul/CONTRACT.md
  - src/lingtai/tools/soul/ANATOMY.md
  - src/lingtai/tools/_settings.py
  - src/lingtai/intrinsic_skills/soul-manual/SKILL.md
maintenance: |
  Keep related_files as repo-relative paths to real files. If behavior and this
  contract disagree, the code is the source of truth — fix the contract in the
  same change and bump contract_version on breaking contract edits.
---

# Soul capability contract

`soul` is the agent's inner voice: on-demand past-self `inquiry`, mechanical
periodic `flow` consultation, cadence/voice `config`, `voice` profile selection,
a `dismiss` for the soul-flow notification, and the installed `manual` action.
The implementation lives in `src/lingtai/tools/soul/`; the code is the source of
truth.

## Routing Card

**Use this when:**
- You are editing the sync `inquiry` mirror session, periodic `flow`
  consultation fire, soul cadence/voice config, or public action/input dispatch.
- You are reviewing how soul voices reach the agent (via
  `.notification/soul.json`) and how flow is opt-in gated.
- You are checking the Agent-owned settings evidence or installed manual path.

**Do not use this for:**
- General notification reads: use the `notification` tool
  (`src/lingtai/tools/notification/CONTRACT.md`). `soul` dismiss is a thin
  wrapper that clears only the `soul` channel via the shared helper.
- Context molt / summarize: those are `psyche` and `system`.
- Code navigation only: read `src/lingtai/tools/soul/ANATOMY.md`.

## Scope

- Canonical tool name: `soul`.
- The raw schema is a closed root object with exactly required `action` and
  required nested `input`.
- Actions are exactly `inquiry`, `flow`, `config`, `voice`, `dismiss`, and
  `manual`.
- `flow` is opt-in via `LINGTAI_SOUL_FLOW_ENABLED` and disabled by default; an
  agent-invoked call only triggers a fire and voices arrive asynchronously.
- There is no public flat, omitted-action, or fabricated compatibility form.
- Non-goals: general notification verbs, molt/summarize, mailbox actions, and
  settings-controlled soul options.

## Public call shape

Every public example uses explicit root `action`, nested `input`, and optional
root `reasoning` injected by `BaseAgent`:

```text
soul(action="inquiry", input={"inquiry": "What am I missing?"}, reasoning="reflect")
soul(action="flow", input={}, reasoning="check opt-in state")
soul(action="config", input={"delay_seconds": 300}, reasoning="tune cadence")
soul(action="voice", input={}, reasoning="read current voice")
soul(action="dismiss", input={}, reasoning="clear the notification")
soul(action="manual", input={}, reasoning="load the installed manual")
```

`reasoning` is optional Agent metadata. It is not in `get_schema()` and is never
owned by a nested `input` branch. The executor may carry it internally as
`_reasoning`. The raw schema contains no reasoning property; BaseAgent alone
adds the optional root property to its Agent-facing `FunctionSchema`.

The raw schema is:

- root `type: object`;
- root properties exactly `action` and `input`;
- root `required: ["action", "input"]`;
- root `additionalProperties: false`;
- `action` is the string enum `inquiry | flow | config | voice | dismiss | manual`;
- `input` is a strict `anyOf` of six action-owned object branches, each with
  `additionalProperties: false`.

Provider envelopes remain unchanged. `FunctionSchema` carries the Agent-facing
parameters; Chat uses `function.parameters`, Responses uses flat function
`parameters`, Anthropic uses `input_schema`, and all provider top-level tool
descriptions remain the existing `WIRE_TOOL_DESCRIPTION` constant.

## Action ownership

### `action="inquiry"`

`input` requires exactly the non-empty string field `inquiry`. The handler trims
the question for the existing synchronous mirror session, persists a result in
the existing soul log, and returns `{status: "ok", voice}` or
`{status: "ok", voice: "(silence)"}`. Empty or non-string values return the
existing inquiry error. It owns no config, voice, flow, dismiss, or reasoning
field.

### `action="flow"`

`input` must be empty. Flow remains opt-in and disabled by default. With the env
gate disabled it returns the stable `{status: "disabled", enabled: false,
env_var, message}` result before touching the fire lock or spawning a thread;
this is expected configuration state, not an error. With the gate enabled, the
voluntary call retains its immediate acknowledgement, non-blocking ongoing-fire
rejection, IDLE wait, daemon thread, consultation fan-out, notification
publication, and existing lifecycle gates. Tests use only disabled or patched
fake paths and never trigger a live fire.

### `action="config"`

`input` owns only `delay_seconds` and `consultation_past_count`; both are
optional at schema level because a caller may update either one or both, but at
least one real update is required. Existing validation and bounds remain:
`delay_seconds` is a finite number at least `30.0`, and
`consultation_past_count` is an integer in `[0, 5]`. The handler keeps live-state
updates, timer restart, `init.json` persistence, disabled-flow note, and existing
error text. Config never enables flow and settings evidence is not an option.

### `action="voice"`

`input` owns only `set` and `prompt`. Empty input reads the current voice, the
available built-ins, and the resolved prompt without changing state. `set` may
be `inner`, `observer`, or `custom`; `custom` requires a non-empty string
`prompt` no longer than `4000` characters. Preset switching clears a prior
custom prompt. Existing persistence, prompt resolution, and exact validation
messages remain unchanged. `prompt` is ignored by the existing handler for
non-custom profiles, as before.

### `action="dismiss"`

`input` must be empty. The action delegates to
`dismiss_channel(agent, "soul", invoked_by="soul")`, preserving the existing
shared notification guard, result shape, logging, and cross-channel safety.
It must not dismiss a live notification in tests.

### `action="manual"`

`input` must be empty. The action is read-only and loads the actual initialized
Agent copy at:

```text
<agent>/.library/intrinsic/capabilities/soul-manual/SKILL.md
```

It does not read a source resource as a substitute and does not change soul
state. A missing initialized copy returns the existing bounded degraded manual
result with its installed path.

## Validation and settings evidence

`handle` accepts only a mapping. It first rereads the Agent-owned
`settings/soul.json` through the strict shared v1 placeholder reader, then
validates root and nested mappings before any soul action/service seam. Root and
nested keys must be strings; unhashable keys, missing root fields, unsupported
root fields, non-string/unrecognized actions, non-mapping input, missing
required action fields, and wrong/cross-action nested fields are deterministic
bounded errors with zero service calls. The executor-only `_tc_id` and
`_reasoning` metadata are not public schema fields; nested input never accepts
reasoning.

The only valid settings content is exactly `{"schema_version": 1}`. Missing,
valid, byte-distinct hot revisions, invalid version/key/type/JSON, and read
errors remain truthful evidence states and never select a behavior or option.
Every result — success, validation error, action error, manual, and bounded
service error — receives a fresh secret-free `current_setting` block with
`configurable: false`, `placeholder: "no-op"`, source, revision, bounded hash,
and a no-op change hint. Invalid files may add only a bounded `settings_error`;
raw bytes, settings secrets, exception details, and host paths do not leak.

## State & storage

Paths are relative to the agent working directory (`agent._working_dir`):

```text
.notification/soul.json  — where flow/inquiry voices are published for the kernel
logs/soul_flow.jsonl     — append-only record of soul entries
history/snapshots/       — past-self snapshots sampled as flow substrate
init.json                — manifest.soul persistence for config and voice
settings/soul.json       — Agent-owned v1 evidence-only placeholder
.library/intrinsic/capabilities/soul-manual/SKILL.md — initialized manual copy
```

- `flow` fires `M = 1 + K` parallel LLM calls and writes voices through the
  existing notification system.
- `inquiry` runs the existing synchronous mirror session and persists its result.
- `config`/`voice` update live state and persist to `init.json`.
- `dismiss` clears only the `soul` notification channel.
- `manual` only reads the initialized manual copy.

## Preserved implementation and lifecycle invariants

This migration changes only the public action/input boundary and evidence
attachment. Preserve all existing implementation behavior, including:

- flow env parsing, timer IDLE gating, fire lock ownership, asynchronous
  consultation fan-out, stale-result handling, notification replacement and
  wake/sync lifecycle;
- inquiry cloning, text/thinking selection, timeout/refusal behavior,
  persistence, token accounting, and `/btw` provenance safeguards;
- config finite-number/integer bounds, timer restart, atomic `init.json` writes,
  disabled-flow note, and no implicit enablement;
- voice built-in/custom prompt resolution, maximum length, persistence, and
  custom-prompt semantics;
- dismiss shared-channel guard, notification bookkeeping, privacy/cost wording,
  and platform-neutral pathlib/threading behavior.

No settings placeholder field becomes an option. No live action is required or
permitted for contract validation.

## Anchored claims and verification

| Claim | Source | Safe focused coverage |
|---|---|---|
| Raw schema is closed action/input with six strict branches | `__init__.py:get_schema` | candidate raw schema assertions |
| BaseAgent adds only root reasoning | BaseAgent schema builder | candidate Agent FunctionSchema assertions |
| Provider envelope names and wire description stay stable | LLM adapters / `WIRE_TOOL_DESCRIPTION` | candidate Chat/Responses/Anthropic assertions |
| Flow remains opt-in and disabled path burns no thread | `__init__.py:handle`, `flow.py` | disabled fake-agent path |
| Inquiry, config, voice, dismiss preserve ownership and validation | `__init__.py`, `config.py` | deterministic fake seams |
| Every result receives fresh settings evidence | `_settings.py`, `__init__.py` | missing/valid/hot/invalid/error assertions |
| Manual reads the initialized Agent copy | `_manual.py`, `intrinsic_skills/soul-manual/SKILL.md` | actual-Agent installed-file equality assertion |

Run the candidate-owned direct test with the project runtime interpreter; do not
invoke live soul actions and do not substitute a pytest invocation for the safe
focused harness.

## Glossary ownership

Canonical identifiers — function names, JSON property names, action/enum values,
defaults, and bounds — remain immutable English literals. The schema and
canonical description are language-independent. This package owns
`glossary-en.md`, `glossary-zh.md`, and `glossary-wen.md`; localized glossaries
map terms only and never offer aliases or fabricated options. Any public action,
property, or call-shape change requires reviewing all three glossary files.
