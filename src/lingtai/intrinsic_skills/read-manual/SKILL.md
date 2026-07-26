---
name: read-manual
description: "Complete guide for the read tool: strict action/input calls, continuation workflow, next_offset pagination, line_truncated handling, runtime tool-result spill vs read-level pagination, 100k read default / 200k runtime hard cap, and when to use bash/grep/sed for truncated lines."
version: 0.2.0
tags: [read, files, continuation, truncation, cap, pagination]
last_changed_at: "2026-07-26T00:00:00Z"
related_files:
- src/lingtai/tools/read/__init__.py
- src/lingtai/tools/read/CONTRACT.md
- src/lingtai/intrinsic_skills/file-manual/SKILL.md
maintenance: |
  Tracks the tool/capability behavior it teaches; update when that tool's behavior changes.
---

# Read Manual

Complete guide for the public `read` capability. The raw tool-owned schema is a
closed root object with required `action` and required nested `input`; `BaseAgent`
adds optional root `reasoning` to the model-facing call shown here:

```json
{
  "action": "read",
  "input": {
    "file_path": "src/example.py",
    "offset": 1,
    "limit": 200,
    "max_chars": 100000,
    "summary": false
  },
  "reasoning": "inspect the requested source window"
}
```

`action` is exactly `read` or `manual`. The `read` input is closed and requires
`file_path`; it preserves the optional `offset` (default `1`, 1-based), `limit`
(default `2000` lines), `max_chars` (per-call character budget), and exact
boolean `summary` (default `false`). `manual` requires the closed empty input
object:

```json
{"action": "manual", "input": {}, "reasoning": "load the installed read guide"}
```

Do not use omitted-action, flat-root, nested `reasoning`, or compatibility-alias
forms. `BaseAgent` may add optional root `reasoning` as call metadata; it is not
part of this tool's nested input. `ToolExecutor` may normalize that metadata to
`_reasoning` for the handler. Neither form changes read behavior.

Every invocation first rereads strict Agent-owned `settings/read.json` and every
result includes a secret-free `current_setting` placeholder diagnostic. The
settings file has no genuine read option: only `{"schema_version": 1}` is valid,
and missing, valid, hot, or invalid settings never change schema, prompts,
path resolution, pagination, caps, or file behavior.

## Two caps

| Cap | Value | Configurable |
|---|---|---|
| `read` per-call page budget | **100 000 chars** (default) | yes, via nested `input.max_chars` |
| Runtime tool-result hard ceiling | **200 000 chars** | no — not by agents or prompts |

`input.max_chars` requests a smaller or larger chunk for one call. Positive
integer values above the hard ceiling are clamped to 200 000; the existing read
cap resolver uses the 100 000 default when the value is absent or otherwise does
not select a positive cap. The runtime hard cap remains the ceiling that prevents
provider-visible tool-result blowups.

These two caps act at different layers:

1. **Read-level pagination** — exceeding the effective per-call budget returns
   `truncated=true` plus continuation metadata. You page on with `next_offset`.
2. **Runtime preventive ceiling** — `ToolExecutor` applies the non-configurable
   200k cap to every tool result just before it reaches the LLM wire. A result
   still over the ceiling is written to `<workdir>/tmp/tool-results/<…>` and
   replaced on the wire by a compact manifest containing `status="spilled"`,
   `spill_path`, `artifact`, `preview`, and `original_char_count`.

A well-formed `read` result normally stays under the outer ceiling because
`max_chars` is clamped to 200k. If you still see a spill manifest from `read`,
inspect the `spill_path` artifact, then re-call `read` with a smaller `limit` or
`max_chars`, or process the artifact via `bash`/`grep`/Python.

## Metadata/stats preflight

For unknown or large files, inspect cheap metadata before reading big chunks.
This replaces a dedicated dry-run action; there is no `dry_run` read input.

```bash
python - <<'PY'
from pathlib import Path
p = Path('/path/to/file')
count = max_len = max_line = 0
with p.open('r', encoding='utf-8', errors='replace') as f:
    for i, line in enumerate(f, 1):
        count = i
        if len(line) > max_len:
            max_len, max_line = len(line), i
print({'bytes': p.stat().st_size, 'lines': count,
       'longest_line': max_line, 'longest_chars': max_len})
PY
```

Use the result to choose the window:

- `input.offset` — where to begin or resume (1-based; default `1`).
- `input.limit` — how many lines to request (default `2000`); a tight `limit`
  (e.g. `50`) narrows the window, and a large offset with a small limit reads an
  arbitrary slice.
- `input.max_chars` — per-call character budget (default 100k, max 200k).
- `input.summary` — exact boolean control metadata only; it does not select a
  different read range or alter the handler's file operation.

## Complete-content workflow

For any file that may exceed the cap:

1. Call `read` with the desired nested input offset and limit.
2. If `truncated` is absent or `false`, the whole requested range was returned —
   done. If `true`, continue.
3. Re-call with `offset=next_offset`, keeping the same `limit` and `max_chars`.

```python
offset = 1
while True:
    result = read({
        "action": "read",
        "input": {
            "file_path": path,
            "offset": offset,
            "limit": 200,
            "max_chars": 100000,
            "summary": False,
        },
        "reasoning": "read the next text window",
    })
    process(result["content"])
    if not result.get("truncated"):
        break
    offset = result["next_offset"]
```

## Continuation metadata fields

When `truncated=true` the result includes:

| Field | Meaning |
|---|---|
| `truncated` | `true` — content was cut |
| `cap_chars` | effective character cap used for this call |
| `returned_chars` | characters actually returned |
| `requested_offset` | 1-based start line you passed |
| `requested_limit` | line limit you passed |
| `last_returned_line` | 1-based line number of the last line shown |
| `next_offset` | pass this as `input.offset` on the next call to continue |
| `remaining_lines_estimate` | approximate lines still unread |
| `line_truncated` | `true` only when a single physical line exceeded the cap |

## Handling `line_truncated=true`

`line_truncated=true` appears when a single physical line is longer than the cap.
Then:

- The result contains only a **prefix** of that line (bounded by the cap).
- `next_offset` points to the **next line**, not to a mid-line continuation.
- The hidden tail of the long line is **not recoverable** through further `read`
  calls.

To inspect a long line fully, use targeted local processing instead of `read`:

```bash
sed -n '42p' /path/to/file                        # print one specific line
awk '{print NR, length($0)}' /path/to/file | head -20   # characters per line
grep -n "pattern" /path/to/file                   # search within a long line

# Extract a byte range from a long line
python - <<'PY'
with open('/path/to/file') as f:
    for i, line in enumerate(f, 1):
        if i == 42:
            print(line[0:2000], "...", line[-500:], sep="\n")
            break
PY
```

## Quick checklist

Before calling `read`:

- Use `{"action":"read","input":{...},"reasoning":"describe the read"}`; never flatten the input or nest reasoning.
- Large file? Probe with `limit=100`–`200`, or run the preflight above.
- Need the whole file? Use the continuation loop.
- `line_truncated=true`? Switch to `bash`/`grep`/`sed`/Python.
- `status="spilled"`? Read the `spill_path` artifact or reduce `limit`.
- Need a specific region? Pass `offset` and a tight `limit` inside `input`.
- Need the installed guide? Use `{"action":"manual","input":{},"reasoning":"load the installed read guide"}` once.

The raw result is preserved before any `summary=true` replacement. Set nested
`summary` to `true` only when a lossy generated summary is acceptable; keep it
`false` when exact line/file content is required.
