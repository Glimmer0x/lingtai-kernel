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
  - src/lingtai/kernel/execution_workspace.py
  - src/lingtai/kernel/turn_events.py
  - src/lingtai/kernel/tool_executor.py
  - src/lingtai/services/session_mcp.py
  - src/lingtai/kernel/base_agent/lifecycle.py
  - tests/test_acp_stdio.py
  - tests/test_correlated_turns.py
  - tests/test_execution_workspace.py
  - tests/test_turn_events.py
  - tests/test_tool_executor.py
  - tests/test_session_mcp.py
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
- **guards**: `acp-local-stdio` § Behavior and Contract rules 1–9 — see [CONTRACT.md](CONTRACT.md#contract-rules)
- **supersedes**: `tests/test_acp_stdio.py`, `tests/test_correlated_turns.py` (retained as bottom asserts)
- **runner**: any LingTai coding agent with shell access to this repository
- **prerequisites**: a clean checkout at `<repo>`; a project Python with installed runtime/test dependencies; no live agent sharing a pytest scratch directory
- **estimate**: ≈ 5 minutes

### Steps
1. From `<repo>`, run `python -m pytest -q -x tests/test_turn_events.py tests/test_tool_executor.py tests/test_correlated_turns.py tests/test_execution_workspace.py tests/test_session_mcp.py tests/test_acp_stdio.py` with the project Python.
2. Inspect the captured normal-turn frames in the passing wire test: initialize result, session/new result, one `session/update` with `sessionUpdate=agent_message_chunk` and Text content, then the original prompt result with `stopReason=end_turn`; inspect the ResourceLink case and confirm validated link metadata reaches the Core text boundary.
3. Inspect lifecycle tests: serial, parallel, denied, and failed tools emit minimal ordered `tool_call`/`tool_call_update` status frames before terminal response; collector-owned future exceptions, timeout boundaries after worker return, and cancellation each produce one FAILED terminal with no late completion; arguments/results/raw payloads are absent; observer exceptions, late terminal events, and close do not leak or alter Core execution.
4. Inspect the cancellation test: while the original prompt is unresolved, send a no-id `session/cancel` for the same session and confirm only the original prompt id receives `stopReason=cancelled`.
5. Inspect every Adapter-authored stdout line with `json.loads`; confirm there is one complete JSON-RPC object per physical line and Python boot/runtime/stop `print` output is captured only on stderr. Confirm docs prohibit native fd 1, pre-captured stdout, and child stdout rather than claiming to quarantine them.
6. Inspect explicit-scope/lifecycle tests: malformed cwd/MCP, a second session, concurrent prompt, invalid ResourceLink, and failed Core turn each produce the named error path. Confirm canonical outside-agent workspace rooting, parent/symlink refusal, parallel propagation without later leakage, atomic stdio MCP publication/rollback/collision refusal, and lease teardown on close/EOF. Confirm the existing blocked-write and typed-stop lifecycle evidence remains intact.

### Expected evidence
- [ ] Step 1 reports all focused tests passing with no network/provider call.
- [ ] Normal wire order is tool lifecycle updates, then optional agent-message update, then final response; terminal reason is exactly `end_turn`.
- [ ] Tool lifecycle frames use session-unique ids and only title/status metadata; no arguments, results, content, locations, rawInput/rawOutput, or internal error detail is projected.
- [ ] Cancel has no response of its own and the original prompt settles exactly once as `cancelled`; no later agent update is emitted for it.
- [ ] Every Adapter-authored stdout line parses independently as JSON-RPC 2.0; Python diagnostic prints are stderr-only and unsupported native/child fd 1 paths are documented.
- [ ] Baseline ResourceLink reaches Core as validated compact metadata; strict stdio MCP publishes atomically while malformed/remote variants fail explicitly, and Core failure uses the fixed `LingTai turn failed` wire message.
- [ ] Agent shutdown cannot wait on EOF or any client write; not-yet-started prompt frames are invalidated, fatal queue/write failures abort, typed timeout retains liveness/lease until ACP process termination, a successful poisoned stop emits no post-release workdir log before exit 0, and invalid UTF-8 has a fixed Parse error only.

### Pass / Fail
Pass when all evidence is observed, every handle reaches one terminal result, and
no provider/network/config mutation is needed. Fail on a hanging handle,
duplicate terminal response, uncorrelated cancellation, stdout contamination,
implicit second session, ignored non-empty session MCP input, leaked internal
failure/tool payload, out-of-order or post-terminal lifecycle updates, or any
claimed remote/v2/permission/workspace capability; record
the evidence trail in the task report.
