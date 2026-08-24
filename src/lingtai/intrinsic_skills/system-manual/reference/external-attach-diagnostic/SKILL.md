---
name: external-attach-diagnostic
description: >
  Guarded macOS-only external attach diagnostic: verifies a live LingTai PID and
  incarnation against an exact agent directory, captures bounded /usr/bin/sample
  stacks plus content-free runtime facts, and optionally performs one controlled
  external mcp.* burst without exercising NotificationStore locking.
version: 1.0.0
last_changed_at: "2026-08-24T02:20:00Z"
tags: [lingtai, diagnostic, external, attach, sample, stack, pid, privacy, notification]
related_files:
- src/lingtai/intrinsic_skills/system-manual/reference/external-attach-diagnostic/scripts/external_attach_diagnostic.py
- src/lingtai/adapters/posix/process_identity.py
- src/lingtai/adapters/posix/process_scan.py
- src/lingtai/kernel/process_match.py
- src/lingtai/kernel/runtime_identity.py
maintenance: |
  Keep host support, process-incarnation checks, data-minimization boundaries, and
  controlled-burst semantics synchronized with the named runtime helpers.
---

# External Attach Diagnostic

Use this **only for an authorized, live macOS incident investigation** when an
external observer needs bounded process stacks. It is a reusable script, not an
in-process debug mode and not a timing profiler: its samples are **stacks, not
semantic stage timings**.

The script is at `scripts/external_attach_diagnostic.py`. Run it from a Python
environment that can import the target LingTai runtime. It requires exact
`--agent-dir` and `--pid`, plus an **absent** absolute `--artifact-dir`:

```bash
python3 scripts/external_attach_diagnostic.py \
  --agent-dir /absolute/path/to/agent \
  --pid 12345 \
  --artifact-dir /absolute/empty-parent/attach-20260824
```

## Preconditions and refusal rules

1. It is macOS-only and requires executable `/usr/bin/sample`. Unsupported
   host/tool failure happens **before** it creates the artifact directory or
   mutates the agent directory.
2. `--agent-dir` and the artifact parent must be canonical absolute directories;
   the artifact target itself must not exist. The script creates only that new
   evidence directory (mode `0700`).
3. The supplied PID is verified through the existing process-table adapter and
   canonical `match_agent_run`, then bound to a stable existing
   `process_identity` before and after each capture. It never trusts PID alone
   or a command substring.
4. Default mode is observational with respect to the agent: it writes only the
   requested evidence directory and **refuses any notification mutation** unless
   the explicit controlled-burst flag is present.

Artifacts contain bounded `/usr/bin/sample` stack files and an `evidence.json`
record with a hashed start-identity token, kernel identity, heartbeat age, and
safe file counts. They do **not** read or record prompt, notification, tool, or
secret bodies. Stack capture does not infer semantic stages or timings.

Optional related PIDs are operator-supplied only and must each have a stable
incarnation identity:

```bash
python3 scripts/external_attach_diagnostic.py \
  --agent-dir /absolute/path/to/agent --pid 12345 \
  --related-pid 12361 --related-pid 12372 \
  --sample-seconds 3 --artifact-dir /absolute/empty-parent/attach-20260824
```

`--sample-seconds` is bounded to 1–10 seconds; at most eight related PIDs are
accepted. The script suppresses `/usr/bin/sample` stdout/stderr from the
artifact record and stores only stack outputs.

## Controlled external producer burst (exceptional)

This is a **separate, explicitly opt-in** simulation of an external producer;
it does not call the Store and therefore does **not** exercise Store locking.
After all read-only preflight and stack capture succeeds, it atomically creates
exactly one unique, content-free file:

```bash
python3 scripts/external_attach_diagnostic.py \
  --agent-dir /absolute/path/to/agent --pid 12345 \
  --artifact-dir /absolute/empty-parent/attach-control \
  --controlled-burst --burst-run-id incident-20260824-a
```

The target is exactly
`.notification/mcp.external-attach-diagnostic.<run-id>.json`. Its exclusive
creation refuses an existing target rather than overwriting or merging any
notification. The payload is only a control marker/run ID; it contains no
prompt, notification, or tool body. The script never creates `.notification/`
for this purpose: a canonical existing directory is required.

If cleanup is authorized after observing the burst, use the same exact run ID:

```bash
python3 scripts/external_attach_diagnostic.py \
  --agent-dir /absolute/path/to/agent --pid 12345 \
  --artifact-dir /absolute/empty-parent/attach-cleanup \
  --cleanup-controlled-burst --burst-run-id incident-20260824-a
```

Cleanup is deliberately narrow: it revalidates the exact filename and its own
content-free marker before deleting it. It cannot enumerate, clear, or touch
any other notification file, and it refuses an absent, malformed, altered, or
foreign target.

## Limits

- No in-process debug mode, cache, notification cap, database, refresh, restart,
  or daemon-manager operation is involved.
- It cannot establish causality from stacks. Preserve external timing/incident
  context separately if authorized.
- A changed PID incarnation during preflight or sampling makes the invocation
  fail rather than attributing output to a recycled PID.
- Do not use this script as a notification Store concurrency test. The focused
  cross-process Store tests own real native lock-path coverage.
