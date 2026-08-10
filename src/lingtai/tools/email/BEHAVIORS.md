---
name: email-behavior-tests
behavior_version: 1
labt_version: 2
contract: CONTRACT.md
anatomy: ANATOMY.md
related_files:
  - src/lingtai/tools/email/CONTRACT.md
  - src/lingtai/tools/email/ANATOMY.md
  - src/lingtai/tools/email/__init__.py
  - src/lingtai/tools/email/manager.py
maintenance: |
  Created during the every-contract-needs-behaviors sweep. Keep this file
  reciprocal with CONTRACT.md and ANATOMY.md (tridirectional loop): when an
  email tool behavior clause changes, update the guarding LABT here in the same
  change.
---
# Email Capability Behavior Tests

Self-contained agent behavior tasks guarding the observable behavior clauses of
`src/lingtai/tools/email/CONTRACT.md` (closed LTP v2 envelope, validation
before mailbox I/O, reserved `unread` rejection, exact receipts). Pinned pytest
commands must run from the repo root with the project's Python.

## Behavior EM001 — envelope failures are rejected before any mailbox I/O, and send returns the exact sent receipt

- **id**: EM001
- **title**: envelope failures are rejected before any mailbox I/O, and send returns the exact sent receipt
- **guards**: `email-contract` § Tool surface
- **runner**: any LingTai agent with `shell` and `file` access to this repository
- **prerequisites**: a clean checkout of `<repo>`; a scratch agent working directory `<scratch>`
- **estimate**: ≈ 20 minutes

### Steps
1. From `<repo>`, run `python -m pytest tests/test_layers_email.py -q` and capture the outcome.
2. Call `email(action="send", input={"address": "peer@example", "message": "hi", "unknown_key": 1}, reasoning="probe")` and record the result; confirm no mailbox file was created or modified.
3. Call `email(action="unread", input={}, reasoning="probe")` directly and record the result; then send a valid message and confirm the receipt contains `status: "sent"`.

### Expected evidence
- [ ] Step 1: the email layer suite passes, pinning the LTP v2 envelope, receipts, and wire parity.
- [ ] Step 2: the cross-action input key is rejected before any mailbox I/O, delivery thread, or read-state change.
- [ ] Step 3: direct `unread` is rejected with the reserved-action error before family dispatch; a valid send returns `{status: "sent", to, cc, bcc, delay}` and `reasoning`/`summarize`/`_tc_id` never reach the handler.

### Pass / Fail
Pass when the suite passes and the before-I/O rejection and exact receipt hold. Fail on an envelope failure that touches the mailbox, on a direct `unread` that dispatches, or on a send receipt missing `status: "sent"`; record the evidence trail in the task report.
