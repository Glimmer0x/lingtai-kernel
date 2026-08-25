---
name: acp-local-stdio-behavior-tests
behavior_version: 1
labt_version: 2
contract: CONTRACT.md
anatomy: ANATOMY.md
related_files:
  - src/lingtai/adapters/acp/CONTRACT.md
  - src/lingtai/adapters/acp/ANATOMY.md
  - src/lingtai/adapters/acp/MANUAL.md
  - src/lingtai/adapters/acp/server.py
  - src/lingtai/cli_acp.py
  - src/lingtai/kernel/turns.py
  - src/lingtai/kernel/base_agent/lifecycle.py
  - tests/test_acp_stdio.py
  - tests/test_correlated_turns.py
  - tests/test_lifecycle_daemon_shutdown.py
maintenance: |
  Keep this LABT reciprocal with the ACP Contract and Anatomy. Update exact wire
  evidence, supported scope, commands, and pass criteria whenever the v1 stdio
  behavior changes; do not turn an omitted capability into an implied promise.
---
# ACP Local Stdio Behavior Tests

## Behavior ACP001 — one local ACP v1 baseline turn settles normally or cooperatively cancelled without corrupting stdout

- **id**: ACP001
- **title**: one local ACP v1 baseline turn settles normally or cooperatively cancelled without corrupting stdout
- **guards**: `acp-local-stdio` § Behavior and Contract rules 1–7 — see [CONTRACT.md](CONTRACT.md#contract-rules)
- **supersedes**: `tests/test_acp_stdio.py`, `tests/test_correlated_turns.py` (retained as bottom asserts)
- **runner**: any LingTai coding agent with shell access to this repository
- **prerequisites**: a clean checkout at `<repo>`; a project Python with installed runtime/test dependencies; no live agent sharing a pytest scratch directory
- **estimate**: ≈ 5 minutes

### Steps
1. From `<repo>`, run `python -m pytest -q -x tests/test_correlated_turns.py tests/test_acp_stdio.py` with the project Python.
2. Inspect the captured normal-turn frames in the passing wire test: initialize result, session/new result, one `session/update` with `sessionUpdate=agent_message_chunk` and Text content, then the original prompt result with `stopReason=end_turn`; inspect the ResourceLink case and confirm validated link metadata reaches the Core text boundary.
3. Inspect the cancellation test: while the original prompt is unresolved, send a no-id `session/cancel` for the same session and confirm only the original prompt id receives `stopReason=cancelled`.
4. Inspect every Adapter-authored stdout line with `json.loads`; confirm there is one complete JSON-RPC object per physical line and Python boot/runtime/stop `print` output is captured only on stderr. Confirm docs prohibit native fd 1, pre-captured stdout, and child stdout rather than claiming to quarantine them.
5. Inspect explicit-scope/lifecycle tests: a second session, concurrent second prompt, non-empty `mcpServers`, relative cwd, invalid ResourceLink, and failed Core turn each produce the named error path. Confirm blocked coordinator/prompt writes cannot hold shutdown; FIFO terminal batches remain adjacent; Agent shutdown-first/cancel-second emits no late prompt frame; close generation invalidates not-yet-started frames; queue full/serialization/short-write/write/flush failure aborts; Windows `.exe` duplicate detection precedes signal cleanup; timed stop retains services/heartbeat/lease and ACP hard-exits while ownership is held; a poisoned worker that reaches `STOPPED` releases the lease, performs no later workdir log, and still hard-exits with code 0.

### Expected evidence
- [ ] Step 1 reports all focused tests passing with no network/provider call.
- [ ] Normal wire order is update-before-final-response and terminal reason is exactly `end_turn`.
- [ ] Cancel has no response of its own and the original prompt settles exactly once as `cancelled`; no later agent update is emitted for it.
- [ ] Every Adapter-authored stdout line parses independently as JSON-RPC 2.0; Python diagnostic prints are stderr-only and unsupported native/child fd 1 paths are documented.
- [ ] Baseline ResourceLink reaches Core as validated compact metadata; unsupported rich content/session/MCP/concurrency inputs fail explicitly, and Core failure uses the fixed `LingTai turn failed` wire message.
- [ ] Agent shutdown cannot wait on EOF or any client write; not-yet-started prompt frames are invalidated, fatal queue/write failures abort, typed timeout retains liveness/lease until ACP process termination, a successful poisoned stop emits no post-release workdir log before exit 0, and invalid UTF-8 has a fixed Parse error only.

### Pass / Fail
Pass when all evidence is observed, every handle reaches one terminal result, and
no provider/network/config mutation is needed. Fail on a hanging handle,
duplicate terminal response, uncorrelated cancellation, stdout contamination,
implicit second session, ignored non-empty session MCP input, leaked internal
failure text, or any claimed remote/v2/permission/workspace capability; record
the evidence trail in the task report.
