---
related_files:
  - ANATOMY.md
  - RELEASING.md
  - scripts/generate_release_manifest.py
  - scripts/publish_release_assets.py
  - reports/bash-async-relaunch-durability-20260713.html
  - reports/issue-167-initial-diagnostics-explainer.html
  - reports/kernel-release-v0.13.0-20260620/candidate_head.txt
  - reports/kernel-release-v0.13.0-20260620/commits.md
  - reports/kernel-release-v0.13.0-20260620/previous_tag.txt
  - reports/kernel-release-v0.13.0-20260620/prs.md
  - reports/kernel-release-v0.13.0-20260620/raw/build.log
  - reports/kernel-release-v0.13.0-20260620/raw/commits.tsv
  - reports/kernel-release-v0.13.0-20260620/raw/diffstat.txt
  - reports/kernel-release-v0.13.0-20260620/raw/dist-ls.txt
  - reports/kernel-release-v0.13.0-20260620/raw/dist-sha256.txt
  - reports/kernel-release-v0.13.0-20260620/raw/pr_numbers.txt
  - reports/kernel-release-v0.13.0-20260620/raw/prs.json
  - reports/kernel-release-v0.13.0-20260620/raw/shortstat.txt
  - reports/kernel-release-v0.13.0-20260620/raw/twine-check.log
  - reports/kernel-release-v0.13.0-20260620/release-body.md
  - reports/kernel-release-v0.13.0-20260620/release-log.html
  - reports/kernel-release-v0.13.0-20260620/release_version.txt
  - reports/kernel-release-v0.13.1-20260621/candidate_head.txt
  - reports/kernel-release-v0.13.1-20260621/commits.md
  - reports/kernel-release-v0.13.1-20260621/previous_tag.txt
  - reports/kernel-release-v0.13.1-20260621/prs.md
  - reports/kernel-release-v0.13.1-20260621/raw/diffstat.txt
  - reports/kernel-release-v0.13.1-20260621/raw/shortstat.txt
  - reports/kernel-release-v0.13.1-20260621/raw/validation.log
  - reports/kernel-release-v0.13.1-20260621/release-body.md
  - reports/kernel-release-v0.13.1-20260621/release-log.html
  - reports/kernel-release-v0.13.1-20260621/release_version.txt
  - reports/kernel-release-v0.14.1-20260623/artifact-hashes.txt
  - reports/kernel-release-v0.14.1-20260623/candidate_head.txt
  - reports/kernel-release-v0.14.1-20260623/commits.md
  - reports/kernel-release-v0.14.1-20260623/previous_tag.txt
  - reports/kernel-release-v0.14.1-20260623/release-body.md
  - reports/kernel-release-v0.14.1-20260623/release-log.html
  - reports/kernel-release-v0.14.1-20260623/release_version.txt
  - reports/kernel-release-v0.15.2-20260627/artifact-hashes.txt
  - reports/kernel-release-v0.15.2-20260627/candidate_head.txt
  - reports/kernel-release-v0.15.2-20260627/commits.md
  - reports/kernel-release-v0.15.2-20260627/previous_tag.txt
  - reports/kernel-release-v0.15.2-20260627/raw/diffstat.txt
  - reports/kernel-release-v0.15.2-20260627/raw/shortstat.txt
  - reports/kernel-release-v0.15.2-20260627/release-body.md
  - reports/kernel-release-v0.15.2-20260627/release-report.md
  - reports/kernel-release-v0.15.2-20260627/release_version.txt
  - reports/pr297-tool-result-replay-explainer.html
  - reports/real-plugin-candidates/plugin.md
  - reports/t3-relaunch-watcher-redaction-explainer.html
maintenance: |
  Keep related_files repo-relative, duplicate-free, and linked to real files.
  This directory is an append-only archive, so the normal maintenance rule is
  inverted: never rewrite an existing report to match later code. Add the new
  run's files to related_files when a release or investigation deposits a
  bundle here, and delete entries only when the bundle itself is removed from
  the tree. Keep the parent link to the root anatomy, and run the
  architecture-document validation before merge.
  Follow the root Anatomy/Contract pairing rule, report mismatches, and do not duplicate or auto-fix the rule here.
  Capability mentions in any document require explicit bidirectional
  related_files mapping to the implementing code (see root ## Maintenance).
---
# reports/

The repository's append-only archive of generated run artefacts: one directory
per kernel release cut, plus standalone HTML explainers for individual
investigations. Nothing here is imported, executed, or read by the runtime —
these are frozen evidence of what a release or a debugging session actually
found, kept in-tree so a later agent can reconstruct a decision without
re-running the tooling. This is an archive, not a component, so it owns no
`CONTRACT.md`.

## Components

- `kernel-release-<version>-<yyyymmdd>/` — one bundle per release cut
  (`v0.13.0`, `v0.13.1`, `v0.14.1`, `v0.15.2`). Each carries the same shape:
  - `release_version.txt`, `previous_tag.txt`, `candidate_head.txt` — the three
    scalars that pin exactly what was cut (e.g. `0.15.2`, `v0.15.1`, and the
    base candidate commit SHA).
  - `commits.md` and `prs.md` — the human-readable change inventory between the
    previous tag and the candidate head.
  - `release-body.md` — the text published as the GitHub release body.
  - `release-log.html` / `release-report.md` — the run narrative; later cuts
    switched from the HTML log to a Markdown report.
  - `artifact-hashes.txt` — published artifact digests, present from `v0.14.1`
    onward.
  - `raw/` — the unprocessed tool output the summaries were derived from:
    `commits.tsv`, `pr_numbers.txt`, `prs.json`, `diffstat.txt`,
    `shortstat.txt`, `dist-ls.txt`, `dist-sha256.txt`, `build.log`,
    `twine-check.log`, `validation.log`. Bundles differ in which of these
    exist, because the release tooling changed between cuts.
- `real-plugin-candidates/` — one Markdown record per tool converted to a real
  plugin package, written at the time of the conversion. `plugin.md` covers the
  `plugin` capability: the first tool plugin, and the one where the packaging
  had to be kept clear of the Agent Plugins standard the tool itself reports.
- Standalone explainers — self-contained HTML written for one investigation
  each: `bash-async-relaunch-durability-20260713.html`,
  `issue-167-initial-diagnostics-explainer.html`,
  `pr297-tool-result-replay-explainer.html`, and
  `t3-relaunch-watcher-redaction-explainer.html`. Each embeds its own styling
  and depends on no repository asset.

## Connections

The release bundles are the output side of the process described in
[`RELEASING.md`](../RELEASING.md) and implemented by
`scripts/generate_release_manifest.py` and `scripts/publish_release_assets.py`,
driven from `.github/workflows/wheels.yml`. The flow is one-way: the release
tooling writes here, and nothing in `src/` or `tests/` reads back. The
explainers reference code by path and commit in their prose only.

## Composition

- **Parent:** the repository root ([`ANATOMY.md`](../ANATOMY.md)), which owns
  `reports/` as a top-level area.
- **No children.** Release bundles are sibling directories of frozen files
  rather than architectural components, so none of them earns its own anatomy.

## State

Every file here is durable, committed, and immutable in practice. The directory
grows by whole bundles and is never rewritten in place; git history is the only
record of change. No runtime process writes into `reports/` on a normal agent
run — deposits happen from release automation or an explicit investigation.

## Notes

- A bundle's shape is evidence of the tooling at that date, not a schema. The
  missing `raw/` files in the `v0.14.1` bundle and the `release-log.html` →
  `release-report.md` switch are real history; do not backfill them to make the
  bundles uniform.
- The `.md` files here carry docs-governance frontmatter like every other
  Markdown document in the repository, and their `maintenance` notes already
  say the content is frozen except for factual corrections.
- `reports/` is listed in `.gitignore`, so everything under it — including this
  anatomy — is tracked only because it was force-added. That is the intended
  workflow: scratch output stays ignored by default, and a bundle with a
  durable purpose is force-added with rationale. `git add` without `-f` will
  silently refuse a new file here.
