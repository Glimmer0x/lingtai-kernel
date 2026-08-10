---
name: component-behavior-test-convention
behavior_version: 1
related_files:
  - CONTRACT.md
  - ANATOMY.md
  - dev-guide-skill/SKILL.md
  - tests/CONTRACT.md
maintenance: |
  This file is the normative root of the distributed behavior-test definition
  system and the contract-of-behaviors. Keep the root CONTRACT.md and root
  ANATOMY.md reciprocal: contract clauses that state agent-observable behavior
  MUST link to the behavior(s) that guard them, behaviors MUST annotate the
  contract clause they guard, and anatomy MUST link code to both when
  applicable. Change architecture rules, schemas, templates, and validation
  together. Bump behavior_version for a breaking convention change.
---
# Behavior Test Convention (behaviors.md)

## Purpose

**BEHAVIORS.md is the distributed agent-observable behavior definition system.**
A `behaviors.md` sits beside a `CONTRACT.md` (and its paired `ANATOMY.md`) to
record **agent-executable behavioral tests**: markdown scenarios an agent runs
against the real product to prove the contract's *important behavior clauses*
do not drift.

It is the third leg of the **three-way linkage**:

| Document | Answers | Role |
|---|---|---|
| `CONTRACT.md` | What does it promise? | Interface / behavior obligations |
| `behaviors.md` | How do we verify the promise with an agent? | Agent-run behavioral tests |
| `ANATOMY.md` | Where is the code? | Code navigation |

## Relationship to pytest

pytest remains for **low-level assertions** (pure units, hermetic adapter
contracts, fast regressions). `behaviors.md` is the **primary behavior
verification entry** for behavior clauses: scenarios an agent executes against
the real runtime, checking observable outcomes (states, files, notifications,
receipts, side effects) rather than internal call shapes.

When a CONVERT_BEHAVIOR pytest is migrated, the behavior scenario records the
original pytest file as `supersedes` so the trace stays complete; the pytest may
be kept (bottom asserts) or removed, per the change's judgment.

## Bidirectional reference rules

1. **contract → behaviors.** Every *important behavior clause* in a `CONTRACT.md`
   MUST reference the guarding behavior(s) with a link of the form
   `[B012](BEHAVIORS.md#behavior-b012)` (relative to the same directory).
   A behavior clause is a clause stating agent-observable behavior: states,
   receipts, side effects, authorization gates, communication outcomes.
2. **behaviors → contract.** Every behavior entry MUST annotate which contract
   clause it guards, with `guards: <contract-frontmatter-name> §<clause heading>`
   and a relative link back to that clause.
3. **anatomy → both (if applicable).** Every `ANATOMY.md` whose component owns
   behavior MUST link its `behaviors.md` in `related_files` and, in the entry
   for the code that implements a behavior, name the behavior id.
4. **Change one, check the other two.** When any of the three changes in a way
   that could affect agent-observable behavior, the other two must be checked
   and updated if applicable. This is a review gate, not optional polish.

## Behaviors.md frontmatter schema

```yaml
---
name: <component>-behavior-tests      # e.g. system-behavior-tests
behavior_version: 1                   # bump on breaking format change only
contract: CONTRACT.md                 # the contract this guards (relative)
anatomy: ANATOMY.md                   # the anatomy this pairs with (relative)
related_files:                        # real repo-relative paths
  - src/lingtai/tools/system/karma.py
  - tests/test_karma.py
  - <any manual that teaches the behavior>
maintenance: |
  <who updates this, when, and how it links with contract/anatomy changes>
---
```

## Behavior entry template

Each behavior is a numbered markdown section: `## Behavior B### — <title>`.
The id is the anchor: `#behavior-b###` (lowercase).

```markdown
## Behavior B012 — karma verbs require admin.karma

- **guards**: `system-contract` § Karma-gated control of other agents
  (link back to the contract clause)
- **supersedes**: `tests/test_karma.py::test_interrupt_requires_karma_admin`
  (optional; the pytest this behavior replaces or complements)
- **runner**: any LingTai agent with `system` tool
- **preconditions**: two agent working dirs exist; sender has `admin.karma=True`

### Scenario
1. ... concrete steps the agent performs ...
2. ...

### Expected evidence
- [ ] observable outcome 1 (state, file, receipt, notification)
- [ ] observable outcome 2

### Pass / fail
Pass when all expected evidence is observed and no forbidden side effect
occurs. Fail on any mismatch; record the evidence trail in the task report.
```

## Discovery and validation

- Root `BEHAVIORS.md` links every governed child `behaviors.md` exactly once in
  `related_files` (same rule as the contract-of-contract).
- A validation test (`tests/test_architecture_documents.py` or a sibling)
  SHOULD enforce: every contract behavior clause has a behavior link; every
  behavior has a `guards` annotation resolving to a real contract clause; every
  child behaviors.md is linked from this root.
- Keep each behaviors.md concise: one scenario per behavior, scenario length
  bounded, evidence checklists over prose.
