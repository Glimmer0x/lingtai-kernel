# agent_readme ANATOMY

## Components

- `README.md.tpl` — packaged static template. Head carries `template_version:`; body is the navigation entry point (Where-to-look table + Notes). No placeholders, no secret values.
- `ensure_agent_readme(layout_or_root)` — idempotent writer: missing or stale (head `template_version` differs) → atomic rewrite via `_fsutil.atomic_write_text`; version match → no-op. Returns written path or None.
- `render_readme(template=None)` — pure renderer (identity for static template), testable without touching the filesystem.
- `template_version(text)` — head-scan regex for `template_version:` (first 2048 bytes).
- `WorkdirLayout.readme` — `<root>/README.md` path (see `kernel/workdir.py`).

## Connections

- Template loaded via `importlib.resources.files(__package__).joinpath("README.md.tpl")`; package-data ships `.tpl` files (pyproject).
- Mount points (each fail-soft): `_perform_refresh` (lifecycle), agent molt (`tools/context/_molt.py`), `BaseAgent` construction — README regeneration must never break lifecycle flow.
- Reciprocal link: `prompts/substrate/substrate.md` frontmatter `related_files` lists `agent_readme/CONTRACT.md` and `agent_readme/README.md.tpl`.
- Contract: `CONTRACT.md` next to this module fixes README/substrate role split and maintenance boundary.
