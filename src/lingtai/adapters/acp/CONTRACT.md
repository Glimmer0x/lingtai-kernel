---
name: acp-local-stdio
contract_version: 1
root_contract: CONTRACT.md
related_files:
  - src/lingtai/adapters/acp/ANATOMY.md
  - src/lingtai/adapters/acp/BEHAVIORS.md
  - src/lingtai/adapters/acp/MANUAL.md
  - src/lingtai/adapters/acp/__init__.py
  - src/lingtai/adapters/acp/server.py
  - src/lingtai/cli_acp.py
  - src/lingtai/cli.py
  - src/lingtai/kernel/turns.py
  - src/lingtai/kernel/execution_workspace.py
  - src/lingtai/services/session_mcp.py
  - src/lingtai/kernel/base_agent/lifecycle.py
  - src/lingtai/kernel/process_match.py
  - src/lingtai/kernel/base_agent/CONTRACT.md
  - pyproject.toml
  - tests/test_acp_stdio.py
  - tests/test_correlated_turns.py
  - tests/test_execution_workspace.py
  - tests/test_session_mcp.py
  - tests/test_process_match.py
  - tests/test_lifecycle_daemon_shutdown.py
  - tests/test_lingtai_facade.py
  - tests/test_tools_package_data.py
maintenance: |
  Keep this contract reciprocal with its Anatomy and root CONTRACT.md. Update
  ACP translation, the Core turn boundary, composition, manual, and settlement/
  wire tests together. This is the v1 local-stdio slice only; widening sessions,
  content, MCP, workspace, permissions, or transport requires an explicit
  contract change rather than an undocumented fallback.
---
# ACP local stdio

## Purpose

Expose one existing LingTai agent to a local Agent Client Protocol v1 client
through newline-delimited JSON-RPC on stdio. ACP is a driving Adapter: it
translates protocol messages into the protocol-neutral correlated inbound-turn
API owned by Core and never reaches into provider/session/tool internals.

This slice implements stable ACP v1's baseline session `cwd` and stdio MCP
requirements alongside Text and ResourceLink prompts. It remains deliberately
narrow: remote MCP, additional directories, rich content, permissions, and
multi-session persistence are not advertised.

## Behavior

Guarded by: [ACP001](BEHAVIORS.md#behavior-acp001).

A successful process negotiates ACP protocol version `1`, creates exactly one
opaque session, accepts baseline Text and ResourceLink prompt blocks, emits the
completed LingTai response as one `agent_message_chunk` session update, and settles the original prompt with
`end_turn`. `session/cancel` targets only the active handle and the original
prompt eventually settles `cancelled`; cancellation is cooperative and does not
claim hard provider abort or running-tool preemption. Each Adapter-authored wire
line is one compact UTF-8 JSON object. The composition root redirects Python
`sys.stdout`/`print` diagnostics to stderr; native fd 1 writes, pre-captured stdout
objects, and child-process stdout are not quarantined in this slice and are
therefore prohibited while ACP owns the transport.

## Port

The Adapter consumes `BaseAgent.submit_turn(content, sender, correlation_id,
execution_workspace) -> TurnHandle` and `TurnHandle.cancel()/result()` from
`src/lingtai/kernel/turns.py`. The terminal `TurnResult` distinguishes
`normal`, `cancelled`, and `failed` and carries the complete response text for
normal settlement. This Port contains no ACP method, JSON-RPC object, session
identifier, ACP method, MCP configuration, permission, or transport vocabulary.
It may carry the generic immutable `ExecutionWorkspace` value attached to a
correlated turn.

## Adapters

`AcpStdioServer` is the production local stdio Adapter. `cli_acp.run_acp` is the
outer composition root behind `lingtai-agent acp --agent-dir <existing-dir>`: it
captures the original Python stdout wire, redirects `sys.stdout` to stderr before
Agent construction, loads and starts the existing agent, serves ACP, and requests
a typed bounded stop on EOF or interrupt. A timed-out/non-quiescent stop retains
services, heartbeat, and lease until the process owner hard-exits; no later Python
state write can occur after OS release. It adds no dependency and uses standard
library JSON/threading streams directly.

## Contract rules

1. `acp-local-stdio.protocol.v1` — initialization requires an integer
   `protocolVersion` and negotiates by returning this Agent's latest supported
   `protocolVersion: 1`, plus empty
   `agentCapabilities`, LingTai `agentInfo`, and `authMethods: []`. Unsupported
   methods/params use JSON-RPC errors; notifications receive no response.
2. `acp-local-stdio.session.v1` — one process owns at most one initialized ACP
   session and one active prompt. A second `session/new` or concurrent prompt
   fails explicitly. `cwd` must be absolute, exist, and be a directory; it is
   canonicalized once and attached to each correlated turn without changing the
   Agent identity/config/history workdir or process cwd. `mcpServers` uses the
   stable-v1 stdio `{name, command, args, env}` shape. Names are unique, command
   is absolute, args are strings, and env is an array of unique string
   `{name,value}` records. Malformed/unknown fields and HTTP/SSE are rejected.
   Every server starts and lists tools before one atomic publication; duplicate,
   existing, or reserved tool names reject the session and close all clients.
   Non-empty `additionalDirectories` fails explicitly because extra roots are not
   advertised in this slice.
3. `acp-local-stdio.turn.v1` — prompt input is a non-empty list of baseline
   Text/ResourceLink blocks. Text is concatenated in order; each validated
   ResourceLink is projected into the Core text boundary as compact JSON metadata
   without fetching it. Images/audio, embedded resources, permission requests,
   tool/event projection, and rich streaming are unsupported. Normal output is
   at most one completed-response
   `agent_message_chunk` followed by `{stopReason: "end_turn"}`; no hidden
   thoughts or tool internals are projected.
4. `acp-local-stdio.cancel.v1` — `session/cancel` calls only the active
   correlated handle. Cancellation requested before exact terminal settlement
   wins and the original prompt returns `{stopReason: "cancelled"}`. The reader
   stays live while the prompt worker waits, but cancellation remains the Core
   cooperative latch boundary, not a provider-abort guarantee.
5. `acp-local-stdio.failure.v1` — a failed Core turn settles the original request
   with a bounded fixed JSON-RPC Internal error; provider/internal detail is not
   copied to the wire. EOF/close cancels active work and invalidates every prompt
   frame that has not crossed the writer's start check. A frame already inside an
   OS write may finish, so close between update/final can leave the update without
   the final response. Agent shutdown is checked before terminal claim, enqueue,
   and each physical prompt frame. Typed stop proves run-loop plus retained
   poisoned-provider Future quiescence before service/heartbeat/lease teardown.
   If poison recovery reaches `STOPPED` and releases the workdir lease before the
   process-owner poison exit, no later Python workdir log is permitted. The shared
   poison helper logs only while ownership remains, then best-effort flushes and
   exits 0; ACP's earlier incomplete-stop branch still exits 70 while retaining
   ownership and never reaches this successful-stop poison path.
6. `acp-local-stdio.framing.v1` — input and output are UTF-8 newline-delimited
   JSON-RPC 2.0, one object per physical line. Batch messages and non-standard
   JSON constants are invalid. Producers only serialize and `put_nowait` one
   atomic batch into a bounded FIFO; a single disposable daemon writer owns the
   stream. Queue saturation, serialization failure, short write, write failure,
   or flush failure aborts the whole transport with no retry/fallback frame. The
   writer is never joined or made teardown authority, so blocked stdout cannot
   hold the coordinator, Agent stop, or lease teardown. Python `sys.stdout` and
   `print` diagnostics are stderr-only; native/pre-captured/child fd 1 output is
   prohibited rather than quarantined. The bounded reader queue prevents an
   unbounded line backlog, and Agent shutdown returns the coordinator even with
   stdin open. The duplicate-host guard recognizes module/console/legacy ACP
   forms including quoted Windows `lingtai-agent.exe` before stale signal cleanup;
   the workdir lease remains authoritative.
7. `acp-local-stdio.scope.v1` — local stdio and ACP v1 only. Multi-session
   persistence/load, additional workspace roots, permission brokerage, event
   streaming, remote MCP/transports, authentication, and ACP v2 are non-goals.
8. `acp-local-stdio.workspace-mcp-lifecycle.v1` — relative/default File paths,
   Shell cwd validation/defaults, risky-action canonicalization, and parallel
   dispatch observe the canonical turn workspace. Parent and symlink escapes
   fail. Context is reset between turns and copied to worker threads. The ACP
   server owns one idempotent session-MCP lease and closes it on close, EOF,
   fatal abort, startup rollback, or Agent stop.

## Contract tests

`tests/test_acp_stdio.py` pins initialize/session/prompt/update/end-turn framing,
cancel settlement, ResourceLink projection, fixed failure redaction, single-
session/busy/unsupported errors, strict JSON line framing, invalid UTF-8, EOF,
blocked coordinator/prompt output, FIFO/generation/queue-full/write-failure paths,
Agent-stop-with-open-stdin, Windows duplicate-before-cleanup, typed quiescence,
and CLI Python-stdout quarantine/hard-exit ownership.
`tests/test_execution_workspace.py`, `tests/test_session_mcp.py`, and the ACP
wire tests pin workspace rooting/escape/isolation, stdio validation, atomic
publication/rollback, collisions, and close/EOF ownership.
`tests/test_correlated_turns.py` pins the consumed Core Port's normal, matching
active cancel, pending-cancel isolation, failure, and shutdown settlement.

## Maintenance

Follow the frontmatter maintenance block and the
[`MANUAL.md`](MANUAL.md) operator procedure. Check the current stable ACP v1
specification before changing any method or wire shape; record deliberate scope
limits rather than advertising omitted capabilities. Do not introduce an ACP SDK
or optional-dependencies section for this standard-library slice.
