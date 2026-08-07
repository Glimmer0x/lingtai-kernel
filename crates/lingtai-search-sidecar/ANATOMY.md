---
related_files:
  - ANATOMY.md
  - crates/lingtai-search-sidecar/Cargo.toml
  - crates/lingtai-search-sidecar/Cargo.lock
  - crates/lingtai-search-sidecar/README.md
  - crates/lingtai-search-sidecar/src/main.rs
  - src/lingtai/services/file_io.py
  - src/lingtai/services/file_io_sidecar.py
  - src/lingtai/tools/file/ANATOMY.md
  - setup.py
  - pyproject.toml
  - MANIFEST.in
  - tests/test_file_io_sidecar.py
  - tests/test_wheel_sidecar_smoke.py
  - ENVIRONMENT_VARIABLES.md
maintenance: |
  Keep related_files repo-relative, duplicate-free, and linked to real files.
  This crate is a native Adapter for the Python-owned FileIOBackend seam, so it
  has no local CONTRACT.md; the owning promise lives with the file capability.
  Code is the structural source of truth: update this anatomy in the same change
  that alters the JSON wire shape in src/main.rs, the cargo build hook in
  setup.py, or the resolver order. Keep the README's runtime-selection table and
  this map consistent, and run the architecture-document validation before merge.
  Follow the root Anatomy/Contract pairing rule, report mismatches, and do not duplicate or auto-fix the rule here.
---
# lingtai-search-sidecar (Rust)

The repository's only non-Python compilation unit: an optional native
executable that backs the `glob` and `grep` operations of the public `file`
capability behind the `FileIOBackend` seam. It is an Adapter, not a component
with its own promise — the model-facing behavior it must reproduce is owned by
`src/lingtai/tools/file/`, and the Python `LocalFileIOBackend` remains the
reference implementation it stays semantically interchangeable with.

## Components

- `Cargo.toml` — crate manifest (`lingtai-search-sidecar`, edition 2021,
  `publish = false`). Its dependency set is deliberately the ripgrep stack —
  `ignore` for traversal, `globset` for glob matching, `grep-matcher` /
  `grep-regex` / `grep-searcher` for the regex scan — so the sidecar inherits
  the engineering that makes `rg` fast. `[profile.release]` pins `opt-level = 3`
  and `lto = true`.
- `Cargo.lock` — the committed exact dependency graph. It is tracked because
  wheel builds compile this crate in CI, so the native artifact must be
  reproducible rather than resolved fresh per build.
- `src/main.rs` — the whole program (914 lines). `Request` (`src/main.rs:55`)
  and `Response`/`GrepMatch`/`ErrorBody` (`src/main.rs:112-125`) are the JSON
  wire types; `main`/`run` (`src/main.rs:157-175`) read one request from stdin
  and write one response to stdout; `build_walker` (`src/main.rs:308`),
  `grep` (`src/main.rs:423`), and `glob_walk` (`src/main.rs:624`) are the two
  operations plus their shared bounded traversal, with `over_walltime`
  (`src/main.rs:283`) and the `Stats` accounting (`src/main.rs:252-260`)
  enforcing the caller's `max_results` / `max_visited` / `walltime_ms` /
  `max_file_bytes` budgets.
- `README.md` — the build-and-runtime-selection contract: how the wheel build
  hook produces the binary, how `resolve_sidecar_binary()` finds it, and what
  `LINGTAI_FILE_IO_BACKEND` (`auto` / `rust` / `python`) and
  `LINGTAI_FILE_IO_SIDECAR` (with legacy `LINGTAI_SEARCH_SIDECAR`) select.

## Connections

`setup.py` is the build-side caller: producing a wheel runs
`cargo build --release`, copies the binary to
`src/lingtai/bin/lingtai-search-sidecar`, and marks the wheel
platform-specific. `LINGTAI_SKIP_RUST_BUILD=1` forces a pure-Python universal
wheel; `LINGTAI_REQUIRE_RUST_BUILD=1` turns any cargo failure into a build
abort instead of a fallback, and release CI sets it in
`.github/workflows/wheels.yml`.

At runtime the caller is Python only: `src/lingtai/services/file_io_sidecar.py`
resolves the bundled binary through `importlib.resources`, spawns it, and
speaks the one-request/one-response JSON protocol; `RustFileIOBackend` and
`LocalFileIOBackend` are swappable behind `src/lingtai/services/file_io.py`
without changing any model-facing tool schema. Nothing in the kernel imports
this crate directly, and no `file` action names it.

## Composition

- **Parent:** the repository root ([`ANATOMY.md`](../../ANATOMY.md)), which owns
  `crates/` as a top-level area.
- **Owning capability:** `src/lingtai/tools/file/ANATOMY.md` and its
  `CONTRACT.md` own the `glob`/`grep` promise this Adapter implements. This
  crate therefore has no co-located `CONTRACT.md` of its own.
- **Packaging:** `pyproject.toml` and `MANIFEST.in` carry the crate sources
  into sdists so a source install can still build the sidecar locally.

## State

The crate owns no persistent state. Each invocation is a single stdin request
and a single stdout response in one short-lived process; build outputs
(`target/`) are untracked, and the only durable artifact is the binary copied
into `src/lingtai/bin/` at wheel-build time.

## Notes

- Absence of the binary is a supported configuration, not a defect: `auto`
  silently falls back to pure Python, and only the explicit `rust` backend
  raises `SidecarError(code="not_configured")`.
- Editable installs (`pip install -e .`) skip the cargo step, so a dev tree
  needs one manual `cargo build --release` before the sidecar path resolves.
- Semantic drift between this crate and `LocalFileIOBackend` is the real
  hazard here: the two are swapped per-process, so any change to traversal,
  exclusion, or match semantics on one side must be mirrored on the other and
  covered by `tests/test_file_io_sidecar.py`.
