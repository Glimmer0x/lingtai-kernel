---
related_files:
  - src/lingtai/adapters/acp/CONTRACT.md
  - src/lingtai/adapters/acp/ANATOMY.md
  - src/lingtai/adapters/acp/BEHAVIORS.md
  - src/lingtai/adapters/acp/server.py
  - src/lingtai/cli_acp.py
  - src/lingtai/kernel/turns.py
  - src/lingtai/kernel/execution_workspace.py
  - src/lingtai/kernel/turn_events.py
  - src/lingtai/kernel/turn_permissions.py
  - src/lingtai/kernel/tool_executor.py
  - src/lingtai/services/session_mcp.py
  - src/lingtai/kernel/base_agent/lifecycle.py
  - tests/test_acp_stdio.py
  - tests/test_correlated_turns.py
  - tests/test_execution_workspace.py
  - tests/test_turn_events.py
  - tests/test_turn_permissions.py
  - tests/test_tool_executor.py
  - tests/test_session_mcp.py
  - tests/test_lifecycle_daemon_shutdown.py
maintenance: |
  Keep this manual's launch, wire, cancellation, diagnostics, scope, and
  current-spec limitation aligned with the ACP adapter, Core turn Port, CLI
  composition, governed twins, and tests. This manual must remain reachable from
  both ACP CONTRACT.md and ANATOMY.md; update all three when behavior changes.
---
# LingTai local ACP v1 stdio manual

## What this capability is

`lingtai-agent acp` lets one local ACP client drive one existing LingTai agent
over standard input/output. It is intended for an editor, terminal UI, or other
local process that can launch an ACP subprocess. The implementation speaks ACP
protocol version 1 directly with the standard library; no ACP SDK or optional
package is required.

This slice supports exactly:

- `initialize` negotiation that returns this Agent's supported `protocolVersion: 1`;
- one `session/new` per process;
- one canonical execution workspace from `session/new.cwd`;
- zero or more session-scoped stdio MCP servers mounted all-or-nothing;
- one active `session/prompt` at a time;
- baseline Text and ResourceLink prompt blocks;
- one-shot fail-closed tool permission and minimal lifecycle projection;
- one completed response projected as `agent_message_chunk`;
- terminal `end_turn`, cooperative `cancelled`, or a fixed JSON-RPC failure;
- `session/cancel` for the active turn.

It deliberately does **not** provide session load/persistence, multiple sessions,
remote MCP servers, additional workspace roots, persistent permission choices,
capability-gated image/audio/embedded-resource content, message/usage streaming,
tool arguments/results/content, remote transport,
authentication, or ACP v2.

Stable ACP v1 requires stdio session MCP and applying `cwd`. This slice implements
both: cwd is canonicalized once and scopes execution-facing File, Shell, guard,
and parallel tool work; stdio servers use stable v1's `name`, absolute `command`,
string `args`, and `{name,value}` env-array shape. It remains a narrow local flow,
not complete general-purpose ACP v1 conformance.

## Launch

Use an already initialized agent directory containing a valid `init.json`:

```bash
lingtai-agent acp --agent-dir /absolute/path/to/existing-agent
```

Configure the ACP client to launch that exact command and communicate over its
stdin/stdout. Do not run the command interactively and type prose into stdin:
each input line must be one complete JSON-RPC object. The agent directory keeps
its ordinary workdir lease, so another live LingTai process cannot safely share
it.

## Wire sequence

A minimal client sequence is:

1. Send `initialize` with `protocolVersion: 1`.
2. Send `session/new` with an absolute existing-directory `cwd` and either
   `mcpServers: []` or strict stdio entries. Startup is all-or-nothing.
3. Retain the returned opaque `sessionId`.
4. Send `session/prompt` with that id and a non-empty Text/ResourceLink block
   list. ResourceLink metadata is forwarded to Core as compact text; this slice
   does not fetch the URI.
5. For each tool, answer `session/request_permission` with
   `{"result":{"outcome":{"outcome":"selected","optionId":"allow_once"}}}`
   to permit it, or a nested reject/cancel outcome to deny it. Then read the
   minimal lifecycle `session/update` frames, followed by zero or one
   completed Text `agent_message_chunk`, then the response carrying
   `stopReason: "end_turn"`.
6. While step 4 is unresolved, a client may send the `session/cancel`
   notification for the same session. Keep reading: the original prompt request,
   not the cancel notification, eventually receives `stopReason: "cancelled"`.

Example shapes (one compact object per real line in an actual transport):

```json
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":1}}
{"jsonrpc":"2.0","id":2,"method":"session/new","params":{"cwd":"/absolute/client/cwd","mcpServers":[]}}
{"jsonrpc":"2.0","id":3,"method":"session/prompt","params":{"sessionId":"<returned-id>","prompt":[{"type":"text","text":"Hello"}]}}
```

## Tool lifecycle projection

For each tool call, the server first emits a pending `tool_call` and a
`session/request_permission` carrying a plain `ToolCallUpdate` with the same
safe id/title/status, no `sessionUpdate` discriminator, and only Allow once /
Reject options. Only the exact nested selected Allow once outcome received after the request frame's
physical write+flush boundary dispatches. Response arrival and the post-flush
published bit linearize under the state lock, so a pre-flush response stays denied
even if it resumes after publication. The per-request publication lock does not
hold the global state lock over client stdout. Approval then emits
`tool_call_update` with `in_progress`; later
states use `tool_call_update` with that id and status. Status is only
`in_progress`, `completed`, or `failed`; local guard denial is `failed` without
executing the tool. For parallel dispatch, workers announce only start and the
collector assigns the one terminal state from the outcome it actually accepts;
future exceptions, timeout, or cancellation therefore cannot leave `in_progress`
or be overwritten by a late completion. Accepted updates remain FIFO-before the prompt terminal
response, while events after close, generation change, or terminal claim are
dropped.

This is deliberately metadata-only. The Adapter does not send tool arguments,
results, content, locations, `rawInput`, `rawOutput`, or internal error text.
Observer/projection exceptions cannot change Core tool execution. The initial
pending record becomes announced only after its frame flushes; a pre-emission
denial uses a valid initial failed record. If denial races an already-started
pending write, the writer closes the physically emitted record with an adjacent
failed update and suppresses the request; Core lifecycle observation still never
blocks behind stuck client stdout. Permission
broker errors, timeout, cancellation, or transport failure deny; fatal bounded
queue/framing failure still aborts the transport.

## Cancellation semantics

Cancellation is cooperative. LingTai correlates it to the one active Core turn
and prevents that request from being mistaken for a later turn, but it cannot
promise that a provider HTTP call or already running tool stops immediately.
The reader remains available for cancel while a worker waits for settlement. A
cancel request that linearizes before terminal settlement wins; a cancel after
settlement is a no-op.

EOF or Ctrl-C closes the adapter and requests cancellation. Prompt frames that
have not crossed the writer's start check are suppressed; an OS write already in
progress may finish, so an update can exist without its final response if close
wins between them. The process then requests a bounded typed Agent stop. Services,
heartbeat, and workdir lease are released only after both run loop and any retained
poisoned-provider Future are quiescent; otherwise the ACP owner hard-exits while
ownership is still held. Agent-initiated stop/refresh returns the coordinator even
if stdin remains open; the ACP connection is not preserved across refresh.

## Diagnostics and recovery

The Adapter and Python `sys.stdout`/`print` path are protocol-only. Configure the
client to capture stderr for boot reader outcomes, logs, and diagnostics. This
slice does not redirect native fd 1, previously captured stdout objects, or child
stdout: code launched in this host must not use those paths. Common explicit errors:

- non-integer protocol version: invalid params (a different integer negotiates to
  this Agent's supported version `1`, which the client must accept or close);
- relative, missing, or non-directory `cwd`: invalid params;
- malformed, duplicate, HTTP, or SSE `mcpServers`: invalid params; startup or
  tool-name collision closes earlier clients and publishes nothing;
- non-empty `additionalDirectories`: unsupported (additional roots are not advertised);
- second `session/new`: unsupported;
- second prompt while one is active: session busy;
- ResourceLink without non-empty `uri`/`name` or with invalid metadata: invalid params;
- image/audio/embedded-resource prompt block: unsupported;
- failed Core turn: fixed `LingTai turn failed` Internal error, with details kept
  out of the ACP wire.

After correcting client input, launch a fresh process if session creation already
succeeded; the one-session state is intentionally process-local. For agent boot
or provider problems, inspect stderr and the existing agent `logs/` artifacts.
Do not work around an error by placing logs on stdout or by sending unsupported
fields and assuming they were honored.

## Why the boundary is narrow

ACP is an external driving protocol, while LingTai Core owns turn execution.
The Adapter therefore translates into `BaseAgent.submit_turn` and waits on a
protocol-neutral handle/result instead of reading chat history or provider
objects. This keeps wire/session policy outside Core and makes cancellation and
terminal settlement reusable by later driving adapters. Broader ACP capabilities
should be added as separately accepted vertical slices, not guessed inside this
one.
