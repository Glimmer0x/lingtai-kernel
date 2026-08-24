---
related_files:
  - crates/lingtai-search-sidecar/ANATOMY.md
  - src/lingtai/tools/ANATOMY.md
  - src/lingtai/tools/CONTRACT.md
  - src/lingtai/tools/file/BEHAVIORS.md
  - src/lingtai/tools/file/CONTRACT.md
  - src/lingtai/tools/file/__init__.py
  - src/lingtai/tools/file/manual/SKILL.md
  - src/lingtai/intrinsic_skills/file-manual/SKILL.md
  - src/lingtai/kernel/tool_plugin/CONTRACT.md
  - src/lingtai/adapters/tool_plugin_host.py
  - src/lingtai/tools/file/_read.py
  - src/lingtai/tools/file/_write.py
  - src/lingtai/tools/file/_edit.py
  - src/lingtai/tools/file/_glob.py
  - src/lingtai/tools/file/_grep.py
  - src/lingtai/tools/_file_paths.py
  - src/lingtai/tools/tool_family/ANATOMY.md
  - src/lingtai/intrinsic_skills/read-manual/SKILL.md
  - src/lingtai/tools/file/glossary-en.md
  - src/lingtai/tools/file/glossary-wen.md
  - src/lingtai/tools/file/glossary-zh.md
  - tests/test_file_tool_family.py
  - tests/test_file_tool_plugin_package.py
maintenance: |
  Keep this public file Anatomy and its Contract reciprocal, and keep the
  parent link bidirectional. This package is the single owner of the file
  surface: schema, dispatch, all five operations, and the package-owned manual
  body. Do not reintroduce per-operation packages, contracts, or glossaries.
  The retained intrinsic file-manual path is a compatibility marker only; it
  must continue to point back to the package manual and never become a second
  body owner. Update this map with structural code changes and verify citations.
  Capability mentions in any document require explicit bidirectional
  related_files mapping to the implementing code (see root ## Maintenance).
---
# Unified file capability Anatomy

The `file` package is the sole owner of the public `file` tool and its
operational manual body. It exposes one model-facing handler over six canonical
children — `read`, `write`, `edit`, `glob`, `grep`, `manual` — and owns their
implementations outright. The old `file-manual` source path remains only as a
compatibility marker; the integrated installer copies the package manual to that
established runtime path and excludes the marker from standalone copying.

## Components

- `__init__.py` — the static `DECLARATION`, six child input schemas, the one
  declaration-derived family builder, the explicit manual path compatibility
  loader, pure bind step, and official-registrar `setup()` wiring
  (`src/lingtai/tools/file/__init__.py:142-198`, `:205-252`, `:311-345`).
- `_load_file_manual()` / `_build_manual_child()` — prefer the established
  `file-manual` installation, reject a retained redirect marker as an
  operational body, and accept the candidate-era `file` installation only as
  a transitional fallback (`src/lingtai/tools/file/__init__.py:142-198`).
- `_read.py` — the read operation plus paging/truncation math, per-call cap
  resolution, and spill-aware missing-file hint (`_apply_cap` and
  `_resolve_call_cap` at `src/lingtai/tools/file/_read.py:33-65`).
- `_write.py`, `_edit.py`, `_glob.py`, `_grep.py` — the remaining four
  operations, each self-contained: write receipt, edit ambiguity/missing
  discipline, sorted glob list, and grep match/traversal cap.
- `_strip_nulls()` — the one boundary translating strict-schema `null` back to
  “absent” so each operation applies its historical defaults
  (`src/lingtai/tools/file/__init__.py:293-295`).

## Connections

`registry.py` maps public `file` to this package. There are no capability aliases
for the five pre-migration names: `read`, `write`, `edit`, `glob`, and `grep`
are unknown capabilities and fail loudly. The kernel registrar binds the static
declaration once per setup; the bound family closes over only `WorkdirPort` and
`FileIOPort`. Every operation reaches the working tree through that narrow port
and resolves relative paths via `_file_paths.resolve_workdir_path`; this package
performs no target-file I/O of its own.

The reserved `manual` child reads the installed package-owned body through its
explicit compatibility loader. Integrated agents return
`.library/intrinsic/capabilities/file-manual/SKILL.md`, preserving the public
path; a stale candidate installer may still expose `capabilities/file`, which
is accepted only as a transition fallback. The retained source at
`src/lingtai/intrinsic_skills/file-manual/SKILL.md` is a marker and is never a
manual body owner.

## Composition

The parent [`src/lingtai/tools/ANATOMY.md`](../ANATOMY.md) owns capability
registry composition. The generic
[`src/lingtai/tools/tool_family/ANATOMY.md`](../tool_family/ANATOMY.md) owns the
reusable schema-composition/dispatch infrastructure this package composes; it
has no knowledge of File operations. The shared
[`src/lingtai/tools/CONTRACT.md`](../CONTRACT.md) owns the canonical public call
shape. The paired [`CONTRACT.md`](CONTRACT.md) is the single contract for this
surface — family envelope, risk posture, manual promise, and every per-action
input, output, cap, and error string.

## State

No mutable state lives here. The bound family holds only closures over granted
ports and its child registry; it owns no Agent reference, cache, cursor, or
settings. The read cap’s runtime ceiling is observed through `FileIOPort`
rather than stored. Manual path selection is a stateless lookup; the package
owns no installation mutation or duplicate manual cache.

## Notes

Per `../CONTRACT.md` “Implementation independence”, the six children share
nothing but the family name and wire envelope: no operation module imports
another, and each could change shape without touching its siblings. Their
co-location in one package is ownership, not coupling. The package manual and
its legacy-path marker are intentionally separate files with one operational
body source, so a future edit cannot silently create two manuals.
