---
related_files:
  - src/lingtai/ANATOMY.md
  - src/lingtai/tools/avatar/__init__.py
  - src/lingtai/tools/avatar/_launcher.py
  - src/lingtai/tools/avatar/CONTRACT.md
  - src/lingtai/tools/avatar/manual/SKILL.md
  - src/lingtai/tools/avatar/glossary-en.md
  - src/lingtai/tools/avatar/glossary-zh.md
  - src/lingtai/tools/avatar/glossary-wen.md
  - src/lingtai/tools/_manual.py
  - src/lingtai/tools/_settings.py
  - src/lingtai/adapters/avatar_launcher.py
  - src/lingtai/adapters/posix/ANATOMY.md
  - src/lingtai/adapters/posix/avatar_launcher.py
  - src/lingtai/adapters/windows/ANATOMY.md
  - src/lingtai/adapters/windows/avatar_launcher.py
  - tests/test_avatar_rules.py
  - tests/test_layers_avatar.py
  - tests/test_avatar_action_input_candidate.py
maintenance: |
  Keep related_files as repo-relative paths to real files and keep this anatomy
  connected to neighboring anatomy/manual/contract authorities. If code drifts,
  update the authoritative source and this map together.
---
# core/avatar

Avatar is the durable peer-agent capability. It exposes exactly one public tool,
`avatar`, with a closed root `action` plus required nested `input`. Every
avatar-owned public example is explicit and includes Agent-injected root
`reasoning`:

```text
avatar(action="spawn", input={"name": "researcher"}, reasoning="...")
avatar(action="rules", input={"rules_content": "..."}, reasoning="...")
avatar(action="manual", input={}, reasoning="load guidance")
```

The raw avatar `get_schema()` contains only `action` and `input`. `BaseAgent`
adds optional root `reasoning` when it constructs the model-facing
`FunctionSchema.parameters`; reasoning never enters an input branch.
Avatar-owned prose does not describe flat or omitted-action forms. Sibling tools
remain outside this migration boundary.

## Components

- `avatar/__init__.py` — strict action/input schema and runtime validation,
  settings evidence, installed-manual route, spawn preparation/boot/ledger,
  rules distribution, and setup. `AvatarManager` is the core class.
- `avatar/_launcher.py` — immutable launch request/receipt and the opaque
  launcher Port.
- `avatar/manual/SKILL.md` — installed avatar-manual source body and public
  operational guidance.
- `CONTRACT.md` — canonical public contract and provider-envelope notes.
- `adapters/avatar_launcher.py` — launcher selection boundary.
- `adapters/posix/avatar_launcher.py` and `adapters/windows/avatar_launcher.py`
  — platform-specific process/session ownership. Their neighboring anatomy files
  define the platform edges; core avatar code must not duplicate them.

## Preserved runtime edges

The public schema change does not alter the existing lifecycle graph:

```text
validated spawn input + root reasoning
  → safe sibling destination and composed init
  → optional shallow/deep durable copy and identity/history stripping
  → LaunchRequest through injected AvatarLauncher Port
  → heartbeat/boot decision
  → release opaque process handle
  → append registration outcome in delegates/ledger.jsonl
  → propagate existing .rules signal through the ledger tree
```

`dry_run` stops before directory/process/ledger side effects. Platform-specific
process APIs remain below the POSIX/Windows launcher adapters. Confirmation,
duplicate/liveness, boot-failure, and admin-rule gates remain owned by the
existing manager methods and their tests; only the public argument envelope and
settings evidence change here.

## Dispatch anatomy

```text
AvatarManager.handle(args)
  ├─ read settings/avatar.json (fresh v1 placeholder snapshot)
  ├─ validate root mapping/action/input and action-owned nested keys
  ├─ action=manual → load_installed_manual(agent, "avatar")
  ├─ action=spawn  → _spawn({nested fields, _reasoning})
  └─ action=rules  → _rules({rules_content})
      └─ every result gets secret-free current_setting evidence
```

The strict checks happen before `_spawn`, `_rules`, launcher calls, or rules
writes. Manual is read-only. A malformed or cross-action call cannot reach an
avatar service seam.

## Action ownership

| Action | Required nested input | Owned optional nested input |
|---|---|---|
| `spawn` | `name` | `type`, `comment`, `dry_run`, `confirm` |
| `rules` | `rules_content` | none |
| `manual` | empty object | none |

Spawn retains shallow/deep copy, mission-quality gate, duplicate liveness,
path-scope, dry-run, boot heartbeat, detached launcher, ledger, and descendant
rule propagation semantics. Rules retains its independent admin gate and
signal-file distribution. No unlisted action input is introduced.

## Settings evidence

`read_settings(agent, "avatar")` rereads the fixed Agent-owned
`settings/avatar.json` on every call. The strict v1 placeholder is metadata-only:
missing, valid, byte-distinct revisions, and invalid content cannot change
behavior or prompt text. All success/manual/malformed/service-error results
carry `current_setting`; invalid content contributes only a bounded,
secret-free error marker.

## Installed manual edge

`action="manual"` reads the actual initialized agent path
`<agent>/.library/intrinsic/capabilities/avatar/SKILL.md` through the
shared installed-manual loader. It does not substitute the source package body,
construct a launcher, write a signal, or mutate the agent.

## Side-effect boundary

The production spawn and rules paths can have live effects. Focused tests must
inject deterministic fake launchers/services and prove malformed calls make
zero service calls. Never invoke real avatar spawning, rules distribution,
process creation, network modification, or descendant config writing during
validation.
