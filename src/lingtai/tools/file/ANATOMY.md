---
related_files:
  - src/lingtai/tools/ANATOMY.md
  - src/lingtai/tools/CONTRACT.md
  - src/lingtai/tools/file/BEHAVIORS.md
  - src/lingtai/tools/file/CONTRACT.md
  - src/lingtai/tools/file/__init__.py
  - src/lingtai/tools/file/_read.py
  - src/lingtai/tools/file/_write.py
  - src/lingtai/tools/file/_edit.py
  - src/lingtai/tools/file/_glob.py
  - src/lingtai/tools/file/_grep.py
  - src/lingtai/tools/_file_paths.py
  - src/lingtai/tools/tool_family/ANATOMY.md
  - src/lingtai/intrinsic_skills/file-manual/SKILL.md
  - src/lingtai/intrinsic_skills/read-manual/SKILL.md
  - src/lingtai/tools/file/glossary-en.md
  - src/lingtai/tools/file/glossary-wen.md
  - src/lingtai/tools/file/glossary-zh.md
maintenance: |
  Keep this public file Anatomy and its Contract reciprocal, and keep the
  parent link bidirectional. This package is the single owner of the file
  surface: schema, dispatch, and all five operations. Do not reintroduce
  per-operation packages, contracts, or glossaries — they were folded in here
  when the five pre-migration packages were deleted. tool_family is generic
  optional infrastructure this package composes onto. Update this map with
  structural code changes and verify citations.
  Capability mentions in any document require explicit bidirectional
  related_files mapping to the implementing code (see root ## Maintenance).
---
# Unified file capability Anatomy

The `file` package is the sole owner of the public `file` tool. It exposes one
model-facing handler over six canonical children — `read`, `write`, `edit`,
`glob`, `grep`, `manual` — and owns their implementations outright. Schema
composition and envelope dispatch delegate to the generic `tool_family`
infrastructure; everything else about the file surface lives here.

## Components

- `__init__.py` — the six child input schemas, the one registry builder, the
  `FileManager` dispatcher, and `setup()` registration
  (`src/lingtai/tools/file/__init__.py:1-273`).
- `_build_family()` — the single handler-parameterized registry builder. Called
  with no arguments it yields the module-level schema-only `_FAMILY` used by
  `get_schema()`; called with bound handlers it yields the dispatching family.
  One builder means the advertised schema and the dispatch registry cannot
  drift apart (`src/lingtai/tools/file/__init__.py:151-169`).
- `_read.py` — the read operation plus its paging/truncation math
  (`_apply_cap`), per-call cap resolution (`_resolve_call_cap`), the
  `DEFAULT_READ_CAP_CHARS`/`READ_HARD_CAP_CHARS` constants, and the spill-aware
  missing-file hint.
- `_write.py`, `_edit.py`, `_glob.py`, `_grep.py` — the remaining four
  operations, each self-contained: the write receipt, the edit
  ambiguity/missing discipline, the sorted glob list, and the grep match cap
  with its pushed-down glob filter. `_glob`/`_grep` own the issue-#164
  traversal-budget blocks.
- `_strip_nulls` — the one boundary translating a strict-schema `null` back to
  "absent" so each operation applies its own historical defaults
  (`src/lingtai/tools/file/__init__.py:207-211`).

## Connections

`registry.py` maps public `file` to this package. There are no capability
aliases for the five pre-migration names: `read`, `write`, `edit`, `glob`, and
`grep` are unknown capabilities and fail loudly. `FileManager` binds each
operation once at construction; no import or closure rebuild happens per call.
Every operation reaches the working tree only through the injected
`agent._file_io` service, resolving relative paths via the shared
`_file_paths.resolve_workdir_path`; this package performs no I/O of its own.
`write` and `edit` stop at that durable I/O boundary: they have no prompt-manager
or context-reconstruction connection and never hot-load a changed prompt source.
Activation is owned separately by `context.rebuild` and passive refresh/molt.
The reserved `manual` child loads the `file-manual` intrinsic skill bundle
through `tool_family.manual`, which reads it from the agent's installed
`.library/intrinsic/capabilities/` tree.

## Composition

The parent [`src/lingtai/tools/ANATOMY.md`](../ANATOMY.md) owns capability
registry composition. The generic
[`src/lingtai/tools/tool_family/ANATOMY.md`](../tool_family/ANATOMY.md) owns
the reusable schema-composition/dispatch infrastructure this package builds its
`ToolFamily` instances from; it has no knowledge of file's operations. The
shared [`src/lingtai/tools/CONTRACT.md`](../CONTRACT.md) owns the canonical
public call shape. The paired [`CONTRACT.md`](CONTRACT.md) is the single
contract for this surface — family envelope, risk posture, manual promise, and
every per-action input, output, cap, and error string.

## State

No mutable state lives here. `FileManager` holds only its agent reference, its
bound operations, and its child registry; it owns no cache, no cursor, and no
settings. The read cap's runtime ceiling is observed from the executor rather
than stored. The family surfaces no LTP settings file, and its manual says so.

## Notes

Per `../CONTRACT.md` "Implementation independence", the six children share
nothing but the family name and the wire envelope: no operation module imports
another, and each could change shape without touching its siblings. Their
co-location in one package is ownership, not coupling.
