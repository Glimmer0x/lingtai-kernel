---
name: file-manual
description: "Operational guide for LingTai's built-in `file` tool: read, write, edit, glob, grep, manual; the UTF-8 policy and how to handle non-UTF-8 text via explicit bash/Python/iconv; safe write/edit discipline; search workflows. Points to `read-manual` for read pagination and truncation depth."
version: 0.3.1
tags: [files, read, write, edit, grep, glob, encoding, utf-8]
last_changed_at: "2026-08-24T00:00:00Z"
related_files:
- src/lingtai/tools/file/__init__.py
- src/lingtai/tools/file/CONTRACT.md
- src/lingtai/tools/file/_read.py
- src/lingtai/tools/file/_write.py
- src/lingtai/tools/file/_edit.py
- src/lingtai/tools/file/_glob.py
- src/lingtai/tools/file/_grep.py
- src/lingtai/intrinsic_skills/read-manual/SKILL.md
- src/lingtai/intrinsic_skills/file-manual/SKILL.md
maintenance: |
  Tracks the tool/capability behavior it teaches; update when that tool's behavior changes.
---

# File Manual

Working guide for LingTai's built-in `file` tool. Use it for ordinary project
text: source code, Markdown, JSON/YAML/TOML, logs, prompts, skills, and notes.

`file` is one tool with six actions. Every call takes the same envelope:

```python
file(action="read", input={"file_path": "/abs/path/x.py"}, reasoning="why you are calling")
```

`action` selects the operation, `input` carries only that action's own fields,
`reasoning` is required and recorded in your diary, and `summarize` is an
optional root boolean (see below). Fields belonging to another action are
rejected before anything is read or written.

## Choosing the right tool

| Need | Tool |
|---|---|
| Read a known text file (returns numbered lines) | `action="read"` |
| Read a large file, paginate, or handle truncation | `action="read"` with `offset`/`limit` — deeper semantics in `read-manual` |
| Create a new text file or replace a whole file | `action="write"` |
| Make a small exact change | `action="edit"` |
| Find files by name/path | `action="glob"` |
| Search file contents by regex | `action="grep"` |
| Decode non-UTF-8 text | `bash` + Python or `iconv` |
| Inspect binary format, archive, media | `bash` or a domain skill/tool |
| Analyze image content | `vision` |

## Encoding policy

LingTai's own text assets are UTF-8, which is why the `read`/`write`/`edit`
actions pin it.

Do not rely on the host locale. Windows Chinese/Japanese/Korean locales may
default Python text I/O to GBK/CP936/Shift-JIS-like encodings; internal LingTai
assets must never be decoded by guessing the locale.

For external or user-provided non-UTF-8 files, keep the `read` action simple
and use `bash` with an explicit encoding instead:

```bash
python - <<'PY'
from pathlib import Path
# encoding: 'gbk', 'shift_jis', 'latin-1', ... ; errors='replace' survives bad bytes
print(Path('file.txt').read_text(encoding='gbk', errors='replace'))
PY
```

Convert to UTF-8 with `iconv`:

```bash
iconv -f gbk -t utf-8 legacy-gbk.txt > legacy-gbk.utf8.txt
iconv -f shift_jis -t utf-8 legacy-sjis.txt > legacy-sjis.utf8.txt
```

Rule: if a file will become part of the project, convert it to UTF-8 before
committing or storing it as a durable LingTai asset.

## Search, then read a region

Prefer `action="read"` for known text files; its line numbers make later edits
and citations easier. If a file may be generated, minified, huge, or noisy,
start broad with `glob` (file names), narrow with `grep` (contents), and read
only the located region:

```python
file(action="glob", input={"pattern": "**/*.py", "path": "/abs/path/project"}, reasoning="list candidate modules")
file(action="grep", input={"pattern": "class Agent|def handle", "path": "/abs/path/src", "glob": "*.py", "max_matches": 50}, reasoning="locate the handler")
file(action="read", input={"file_path": "/abs/path/src/module.py", "offset": 40, "limit": 80}, reasoning="read the located region")
```

For the cap model, continuation via `next_offset`, and `line_truncated`
handling, read `read-manual` rather than improvising.

## Writing and editing safely

`action="write"` is a full-file operation: use it to create a new file, replace
a generated artifact, or deliberately rewrite a small file you already
understand. Before overwriting an important existing file, read it first unless
the human explicitly asked for a blind overwrite. Do not use `write` for tiny
modifications to large files — use `edit`.

`action="edit"` replaces an exact string and fails when the old string is absent
or ambiguous. That failure is a feature: it prevents accidental broad changes.

`write` and `edit` are generic durable mutations only. Even when their target is
`system/*.md` or another configured prompt source, they **never reload or mutate
the current system prompt**. The disk change takes effect at the next canonical
reconstruction. When it must take effect now, finish the file operation first,
then make one `context(action="rebuild", input={}, reasoning="apply durable prompt changes")`
call (passive refresh or molt also reconstructs) — not for ordinary source-code
edits, and never in a loop.

1. `read` the relevant lines.
2. Copy an exact old-string region with enough surrounding context to be unique.
3. Call `edit` once.
4. Re-read the changed region or run tests.

Use `replace_all=true` only when every occurrence is supposed to change and you
have checked the match set with `grep` first.

## File paths and privacy

Use absolute paths with file tools. Paths inside your working directory may be
private to this agent. Do not send local private paths to other agents or
humans unless they are useful and safe for that recipient; another agent cannot
dereference your local path. When sharing file content, quote the relevant
content or attach/export a file through the appropriate communication channel.

## Summarizing results

`summarize` is an optional root boolean on every `file` call, default false. It
never changes what the action does, and the raw result is always recorded
durably before any summary replaces what you see.

- `read`, `grep`, and `glob` can return **bulky** output. Set `summarize=true`
  when you expect a large result and do not need the exact text — and make
  `reasoning` specific, because it drives what the summary keeps. Leave it false
  whenever you need exact line numbers, paths, or literal content to quote or
  edit against.
- `write` and `edit` return **short** receipts (`path`/`bytes`,
  `replacements`). Those receipts are the whole point of the call and must be
  read exactly. Leave `summarize` false for them.
- Leave it false for `manual` too, so exact procedure is not summarized away.

## Settings

`file` has no settings file at either the family or the action level. There is
nothing to configure and nothing to read.

## Manual versus ordinary calls

`action="manual"` with `input={}` is a one-time entry that returns this guide and
performs no file operation; `read-manual` is a nested reference reached from it,
not a separate action. After it returns, continue the original task with an
ordinary call — repeating an identical manual call is an error loop, not
progress.
