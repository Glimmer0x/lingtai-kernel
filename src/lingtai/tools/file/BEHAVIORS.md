---
name: file-behavior-tests
behavior_version: 1
labt_version: 2
contract: CONTRACT.md
anatomy: ANATOMY.md
related_files:
  - src/lingtai/tools/file/CONTRACT.md
  - src/lingtai/tools/file/ANATOMY.md
  - src/lingtai/tools/file/__init__.py
  - src/lingtai/tools/file/_read.py
  - tests/test_read_continuation.py
  - tests/test_file_tool_family.py
maintenance: |
  LABT v2, migrated 2026-08 from tests/test_read_continuation.py (previously
  filed as C005 under src/lingtai/tools/telegram/BEHAVIORS.md; re-homed here so
  file owns its own behavior tests). Guards `file-contract` § read
  (`_read.py`) — read-only. Keep this LABT in sync with the read
  caps/continuation clause in CONTRACT.md; update both in the same change when
  `_read.py` caps or next_offset semantics change, and keep ANATOMY.md
  reciprocal.
---
# File Behavior Tests

LABT v2. F001 is a self-contained agent-executable behavioral test for the
`file` tool's read continuation: pagination via `next_offset`, truncation caps,
and long-line truncation. It guards the `read` clause of
`src/lingtai/tools/file/CONTRACT.md` (frontmatter name `file-contract`).

## Behavior F001 — File read continuation via next_offset pagination

- **id**: F001
- **title**: `file` read-only continuation, truncation caps, and next_offset semantics
- **guards**: `file-contract` § read (`_read.py`) — read-only (caps, `next_offset` continuation, `line_truncated` skip) ([CONTRACT.md](CONTRACT.md#read-_readpy--read-only))
- **supersedes**: tests/test_read_continuation.py (CONVERT_BEHAVIOR)
- **runner**: any LingTai agent with the `file` tool
- **prerequisites**: repo checkout with src/lingtai/tools/file; a fixture file larger than one page and a file containing one very long line (or scratch copies the executor creates in a temp dir); operates on fixture files under tests/fixtures — never writes (read-only action only).
- **estimate**: 20 minutes

### Steps

1. Read a file larger than one page: `file(action=read, file_path=<fixture>, offset=1, limit=null, max_chars=null)`.
2. Take `next_offset` from the result and call read again with `offset=<next_offset>, limit=null, max_chars=null`.
3. Repeat with explicit `offset`/`limit` and with `max_chars` smaller than the page.
4. Read a file containing one very long line.

### Expected evidence

- [ ] **Caps**: `DEFAULT_READ_CAP_CHARS == 100_000`, `READ_HARD_CAP_CHARS == 200_000`, `PREVENTIVE_MAX_CHARS == 200_000`.
- [ ] **First page**: when the file exceeds the cap, the result is truncated and reports `next_offset == last_returned_line + 1`, plus `remaining_lines_estimate`, `total_lines`, and `lines_shown`.
- [ ] **Continuation**: reading with `offset == next_offset` starts exactly at that line (no overlap, no gap) and again returns its own `next_offset` for the next page.
- [ ] **Offset/limit**: explicit `offset` and `limit` are honored; a per-call `max_chars` returns `cap_chars == <requested>` and `returned_chars <= cap_chars`.
- [ ] **Single long line**: the line is truncated with `line_truncated: true`, `last_returned_line == 1`, and `next_offset == 2`.
- [ ] **Schema/description**: the read result schema mentions `max_chars`, `read-manual`, `truncated`, `next_offset`, and `line_truncated`, and the limits are documented as `100 000` and `200 000` (spaced thousands) in the tool description.

### Pass / Fail

PASS when pagination is gap-free and overlap-free, caps hold, and the long-line case reports exactly `last_returned_line == 1` / `next_offset == 2`; FAIL on any skipped or repeated line.
