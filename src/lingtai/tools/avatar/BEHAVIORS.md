---
name: avatar-behavior-tests
behavior_version: 1
labt_version: 2
contract: CONTRACT.md
anatomy: ANATOMY.md
related_files:
  - src/lingtai/tools/avatar/CONTRACT.md
  - src/lingtai/tools/avatar/ANATOMY.md
  - src/lingtai/tools/avatar/__init__.py
  - src/lingtai/tools/avatar/_launcher.py
maintenance: |
  Created during the every-contract-needs-behaviors sweep. Keep this file
  reciprocal with CONTRACT.md and ANATOMY.md (tridirectional loop): when an
  avatar spawn/rules/manual behavior clause changes, update the guarding LABT
  here in the same change.
---
# Avatar Capability Behavior Tests

Self-contained agent behavior tasks guarding the observable behavior clauses of
`src/lingtai/tools/avatar/CONTRACT.md` (spawn mission gate, name grammar, rules
admin gate, manual no-I/O). Pinned pytest commands must run from the repo root
with the project's Python.

## Behavior AV001 — spawn enforces the name grammar and the mission-quality gate, and rules requires admin privilege

- **id**: AV001
- **title**: spawn enforces the name grammar and the mission-quality gate, and rules requires admin privilege
- **guards**: `avatar-contract` § Tool surface
- **runner**: any LingTai agent with `shell` and `file` access to this repository
- **prerequisites**: a clean checkout of `<repo>`; a scratch parent agent directory `<scratch>`; no live avatar of the probe name
- **estimate**: ≈ 25 minutes

### Steps
1. From `<repo>`, run `python -m pytest tests/test_avatar_launcher.py tests/test_avatar_rules.py -q` and capture the outcome.
2. Call `avatar(action="spawn", input={"name": "bad name with spaces"}, reasoning="probe")` and record the result; then call it with `name="good"` and a mission shorter than 20 characters and record the result.
3. Call `avatar(action="rules", input={"rules_content": "..."}, reasoning="probe")` from a caller without admin karma and record the result; retry with a truthy admin karma.

### Expected evidence
- [ ] Step 1: the avatar launcher/rules suites pass, pinning dry-run, mission gate, receipts, authorization, and distribution.
- [ ] Step 2: a name violating `^[\w-]+$` or carrying a dot/slash/leading dot is rejected; an empty/very-short/debug-placeholder mission is refused with `confirmation_needed` unless `confirm=true` (dry_run exempt).
- [ ] Step 3: `rules` without admin privilege is refused before any write; with admin privilege it writes the self `.rules` signal and returns `distributed_to`.

### Pass / Fail
Pass when the suites pass and the gate observations hold. Fail on a malformed name spawning, on a weak mission spawning without confirmation, or on `rules` executing without admin karma; record the evidence trail in the task report.
