---
name: avatar-manual
description: |
  Complete operational guide for the avatar tool — spawning, managing, and communicating with 他我 (alter-ego agents). Read this when you are about to spawn an avatar, an avatar goes quiet, you need to choose between avatar/daemon/bash, or you need escalation guidance.
version: 2.0.0
last_changed_at: 2026-07-26T00:00:00Z
related_files:
- src/lingtai/tools/avatar/__init__.py
- src/lingtai/tools/avatar/ANATOMY.md
- src/lingtai/tools/avatar/CONTRACT.md
maintenance: |
  Tracks the routed source/resources it summarizes; update when the underlying capability or its sub-references change.
---

# Avatar Manual

## 1. What Is an Avatar

An avatar (他我) is a **fully independent agent process** spawned from you. It
inherits the relevant `init.json` configuration, boots on your default preset,
is recorded in `delegates/ledger.jsonl`, and communicates through mail or email.
Once spawned it is detached, with its own working directory, history, and life.

Use avatar only for work that needs persistence and learning. Use `daemon` when
you need only an ephemeral conclusion, and `bash` for one-off commands.

## 2. The public call shape

The avatar-owned public call is always a closed root `action` plus nested `input`,
with optional root `reasoning` injected by `BaseAgent`:

```text
avatar(action="spawn", input={"name": "researcher"}, reasoning="...mission briefing...")
avatar(action="spawn", input={"name": "clone", "type": "deep", "comment": "", "dry_run": true, "confirm": false}, reasoning="preview this reviewed mission")
avatar(action="rules", input={"rules_content": "Always report findings."}, reasoning="distribute the reviewed rule")
avatar(action="manual", input={}, reasoning="load the installed avatar manual")
```

`action` and `input` are both required. Do not omit `action`, flatten nested
fields, or move `reasoning` into `input`. Avatar-owned prose uses no flat or
omitted-action compatibility form. `reasoning` is Agent metadata, not a nested
avatar option; for `spawn` it becomes the avatar's first mission prompt.

## 3. Spawn types and input ownership

`avatar(action="spawn", input={...}, reasoning="...")` requires
`input.name`. Spawn owns only these nested fields:

- `name`: a single bare sibling-directory segment; letters (any script),
  digits, underscore, and hyphen only; no dots, slashes, spaces, or leading
  dot; maximum 64 characters.
- `type`: `shallow` (default, `初生`) copies `init.json` only; `deep`
  (`二重身`) copies durable identity and knowledge.
- `comment`: optional persistent system note, not inherited.
- `dry_run`: optional preview with no directory, files, or process.
- `confirm`: optional acknowledgement for the mission-quality gate.

`rules_content` belongs only to the `rules` action. Do not include it in a
spawn input.

## 4. The root `reasoning` field — mission briefing

The root `reasoning` metadata on
`avatar(action="spawn", input={"name": "..."}, reasoning="...")` becomes the
avatar's first prompt. Write a thorough mission briefing: task, importance,
relevant paths/resources, parent/collaborator contact, done criteria, and
constraints. Re-read it before invoking the tool.

The mission-quality gate refuses empty, very short (<20 characters), or
placeholder/debug-like missions unless `confirm=true`; `dry_run=true` is exempt.

## 5. Spawn discipline

Every ordinary spawn call creates an independent process and consumes resources
until lifecycle management sleeps or suspends it. Therefore:

1. Never put `avatar(action="spawn", input={...}, reasoning="...")` in a
   parallel batch with unrelated calls.
2. Re-read the root `reasoning` mission before invoking.
3. Use `bash` or `system` for inspection and one-off commands.
4. Use `avatar(action="spawn", input={"name": "...", "dry_run": true}, reasoning="...")`
   to preview without creating a process.
5. Use `confirm=true` only after reviewing the mission and intending to spawn.

## 6. Caring for avatars

After a spawn, record its address, mission, and delegation purpose in your pad.
If an avatar goes quiet, do not send probe mails: report upstream so the parent
can decide whether to use lifecycle tools or accept the loss.

Every avatar receives a system-level parent prompt identifying its parent address.
The avatar should email its parent when it completes, encounters an unresolved
problem, or needs to report back.

## 7. Escalation for avatars

If your admin block is empty or all privileges are false and you hit a blocker,
mail your parent. Report concrete facts: what you were doing, what failed, what
you tried, and what decision or help you need. Report ambiguity, budget
pressure, broken peers, safety concerns, and surprising findings rather than
silently retrying forever.

## 8. Persistent `comment`

`comment` is a persistent system-level note injected into the avatar prompt. It
is not inherited and survives molt, refresh, sleep, and wake. Use it only for
instructions the avatar must always remember.

## 9. Network rules

`avatar(action="rules", input={"rules_content": "..."}, reasoning="...")` requires
at least one truthy admin privilege. Its input owns only `rules_content`.
The action writes a `.rules` signal to the caller and distributes it to all
ledger-discovered descendants. Rules are non-negotiable plain-text constraints,
not suggestions. This is a live filesystem side effect; use a deterministic
fake service in tests and never point validation at a live network.

## 10. Manual action and installed content

`avatar(action="manual", input={}, reasoning="load guidance")` is read-only. It
loads the real installed `avatar-manual` file from the current agent:

```text
<agent>/.library/intrinsic/capabilities/avatar/SKILL.md
```

It does not spawn, write rules, or append a ledger entry. If the installed file
is missing, the result is degraded and includes the installed path so the
initializer problem is visible.

## 11. Settings evidence

Every avatar call rereads the Agent-owned `settings/avatar.json` v1 placeholder.
Missing, valid, byte-distinct revisions, and invalid content are evidence only;
they never select behavior or change this manual/prompt. Every success, manual,
malformed, and service-error result includes secret-free `current_setting`
evidence. Secret values, raw bytes, and host paths are not returned.

## 12. Safety and footprint

Avatars create independent directories and records; do not delete them directly
without explicit retirement authority. Production spawn and rules operations
have real side effects. Tests and harnesses must patch a candidate-owned fake
launcher/service and prove malformed action/input calls make zero service calls.

Before any separately authorized retirement or cleanup, audit the footprint
read-only: the sibling agent directory, the parent's `delegates/ledger.jsonl`
rows, live heartbeat/process evidence, `.rules` propagation state, and any
shared-artifact references. Record what was inspected and the exact paths an
operator authorized. A completed task, a failed boot, a dry-run preview, or the
fact that an avatar directory looks temporary is never deletion permission.
