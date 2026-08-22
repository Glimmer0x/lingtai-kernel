---
name: lingtai-tool-protocol-behavior-tests
behavior_version: 1
labt_version: 2
contract: CONTRACT.md
anatomy: ANATOMY.md
related_files:
  - src/lingtai/tools/CONTRACT.md
  - src/lingtai/tools/ANATOMY.md
  - src/lingtai/tools/_catalog.py
  - src/lingtai/tools/_manual.py
  - src/lingtai/tools/registry.py
  - src/lingtai/tools/plugin/CONTRACT.md
  - src/lingtai/mcp_servers/_plugin.py
  - src/lingtai/services/plugin_registry.py
  - src/lingtai/kernel/base_agent/tools.py
  - scripts/check_docs_governance.py
  - tests/test_architecture_documents.py
maintenance: |
  Created during the every-contract-needs-behaviors sweep. Keep this file
  reciprocal with CONTRACT.md and ANATOMY.md (tridirectional loop): when an LTP
  envelope or settings rule changes, update the guarding LABT here in the same
  change. LP002 guards the additive `### Tool-to-MCP Plugin Contract` section:
  it verifies only what is true today (the section's status wording, the
  document graph, and the cited current evidence). When a family actually
  recuts onto a plugin wrapper, replace LP002's "no family is wrapped" evidence
  with that family's own proof in the same change rather than leaving a stale
  pass.
---
# LingTai Tool Protocol (LTP) Behavior Tests

Self-contained agent behavior tasks guarding the observable behavior clauses of
`src/lingtai/tools/CONTRACT.md` (closed root envelope, strict per-action input,
manual action, two-level settings). Pinned pytest commands must run from the
repo root with the project's Python.

## Behavior LP001 — a migrated family's model-facing root is exactly action/input/reasoning/summarize and closed

- **id**: LP001
- **title**: a migrated family's model-facing root is exactly action/input/reasoning/summarize and closed
- **guards**: `lingtai-tool-protocol` § Behavior
- **runner**: any LingTai agent with `shell` and `file` access to this repository
- **prerequisites**: a clean checkout of `<repo>`; one migrated family to probe (e.g. `file`, `knowledge`, or `mcp`)
- **estimate**: ≈ 20 minutes

### Steps
1. From `<repo>`, run `python -m pytest tests/test_tool_family_wire_parity.py -q` and capture the outcome.
2. Fetch a migrated family's advertised schema (`get_schema()` on the family) and verify the root properties are exactly `action`, `input`, `reasoning`, and `summarize` with `additionalProperties: false`, and that `reasoning`/`summarize` never appear nested under `input`.
3. Confirm `ToolExecutor` strips root `summarize` before handler dispatch and that the root boolean survives through result post-processing on both single and parallel call paths.

### Expected evidence
- [ ] Step 1: the wire-parity suite passes, pinning envelope correlation on both Chat Completions and Responses wires.
- [ ] Step 2: the schema's root is closed with exactly the four properties; no `parameters`/`payload` alias appears; action branches are closed per action.
- [ ] Step 3: `_reasoning` never appears in the model-facing schema or nested `input`; raw output is durably recorded before any visible summary replacement, and tool errors stay exact and unmodified.

### Pass / Fail
Pass when the suite passes and the closed-envelope observation holds for a real migrated family. Fail on an extra root property, on `reasoning`/`summarize` leaking into `input`, or on a summary replacing the recorded raw output; record the evidence trail in the task report.

## Behavior LP002 — the Tool-to-MCP Plugin Contract is a documented migration target, not a shipped wrapper

- **id**: LP002
- **title**: the Tool-to-MCP Plugin Contract is a documented migration target, not a shipped wrapper
- **guards**: `lingtai-tool-protocol` § Tool-to-MCP Plugin Contract
  (`CONTRACT.md` `### Tool-to-MCP Plugin Contract`)
- **runner**: any LingTai agent with `shell` and `file` access to a clean
  checkout of the `lingtai-kernel` repository
- **prerequisites**: a clean checkout of the repository; a working repository
  virtual environment at `.venv/` (`uv venv --python 3.11 && uv pip install -e
  . pytest`, per `AGENTS.md`). Run every command below from the repository root
  (`git rev-parse --show-toplevel`). No network, no agent runtime, and no MCP
  server is needed: this task inspects documents and source text only.
- **estimate**: ≈ 15 minutes

### Steps

1. Read `src/lingtai/tools/CONTRACT.md`, section `### Tool-to-MCP Plugin
   Contract` (it sits under `## Contract rules`, between `### Non-goals` and
   `### Relationship to current runtime`). Confirm its opening **Status**
   paragraph says the section is a migration target, that no LingTai-owned
   family ships as an MCP plugin today, and that the families listed under
   `### Relationship to current runtime` are LTP *envelope* migrations rather
   than plugin wrappers or a compatible universal runtime.
2. Check that every use of the phrase is a negation, not a claim:
   `grep -n "MCP plugin" src/lingtai/tools/CONTRACT.md`. Expect exactly two
   matches, both inside that section (at authoring time, lines 277 and 430),
   one saying no family ships as an MCP plugin today and one listing
   "any first-party built-in family shipping as an MCP plugin" under
   *not evidenced*.
3. Prove no first-party family is wrapped today:
   `grep -n "lingtai.mcp_servers\|CuratedMcpPlugin" src/lingtai/tools/registry.py`.
   Expect no output and shell exit status 1.
4. Prove the packaging precedent the section cites exists and is not a runtime:
   `grep -n "plugin runtime" src/lingtai/mcp_servers/_plugin.py` (expect
   exactly one match, at authoring time line 11, reading "It deliberately is
   **not** a plugin runtime.") and
   `grep -n "must not declare the reserved" src/lingtai/mcp_servers/_plugin.py`
   (expect exactly one match, at authoring time line 201, raising
   `CuratedMcpPluginError`).
5. Prove the live-collision clause is still an open decision rather than a
   shipped promise:
   `grep -n "Remove any existing schema with same name" src/lingtai/kernel/base_agent/tools.py`.
   Expect exactly one match (at authoring time line 162) inside `_add_tool`,
   immediately followed by a line rebuilding `agent._tool_schemas` with
   `s.name != name` — i.e. last registration replaces an existing tool of the
   same name. Confirm the contract records this as current behavior and an
   implementation target, and does **not** claim reject-before-mount,
   namespacing, or any deterministic precedence already holds.
6. Prove the tridirectional graph edges exist exactly once each:
   `grep -c "src/lingtai/tools/BEHAVIORS.md" BEHAVIORS.md
   src/lingtai/tools/CONTRACT.md src/lingtai/tools/ANATOMY.md` (expect `1` for
   each of the three files) and
   `grep -n "behavior-lp002" src/lingtai/tools/CONTRACT.md` (expect exactly one
   `Guarded by: [LP002](BEHAVIORS.md#behavior-lp002)` line directly under the
   section heading).
7. Run the governed-graph validation with the repository venv:
   `.venv/bin/python -m pytest -q
   tests/test_architecture_documents.py::test_root_architecture_documents_are_reciprocal_and_well_formed
   tests/test_architecture_documents.py::test_governed_child_contracts_have_reciprocal_anatomy_pairs
   tests/test_architecture_documents.py::test_governed_cross_document_links_are_reciprocal`.
   Expect `3 passed`.
8. Run the documentation governance checker:
   `.venv/bin/python scripts/check_docs_governance.py --check`. At authoring
   time it exits 1 with exactly five violations, none of them under
   `src/lingtai/tools/`: `IMPLEMENTATION_REPORT.md` (no frontmatter),
   `src/lingtai/kernel/llm/ANATOMY.md` (duplicate `related_files` entries), and
   `src/lingtai/mcp_servers/feishu/reference/{capability-matrix,diagnostics,setup}.md`
   (no frontmatter). These are pre-existing defects owned elsewhere. Any
   violation naming a path under `src/lingtai/tools/` — or the root
   `BEHAVIORS.md` — is a failure of this task, not a pre-existing one. The same
   `src/lingtai/kernel/llm/ANATOMY.md` duplicate is also why
   `tests/test_architecture_documents.py::test_every_tracked_file_climbs_the_anatomy_graph`
   fails at authoring time; treat a `src/lingtai/tools/` path in that failure
   as a failure of this task.

### Expected evidence

- [ ] Step 1: the section exists in `src/lingtai/tools/CONTRACT.md` and opens
      with a Status paragraph declaring it a migration target that converts
      nothing and claims no shipped wrapper.
- [ ] Steps 1-2: the section names its governed surface as first-party
      LingTai-owned families and explicitly excludes external/third-party MCP
      schemas and legacy MCP transport/catalog paths from conversion; both
      "MCP plugin" occurrences are negations.
- [ ] Step 3: `src/lingtai/tools/registry.py` contains no `lingtai.mcp_servers`
      import and no `CuratedMcpPlugin` reference (grep exit status 1).
- [ ] Step 4: `src/lingtai/mcp_servers/_plugin.py` states it is not a plugin
      runtime and refuses a package that declares the reserved `manual` action.
- [ ] Step 5: `_add_tool` in `src/lingtai/kernel/base_agent/tools.py` replaces a
      same-named schema, and the contract's identifier clause presents the live
      collision policy as an explicit open maintainer decision.
- [ ] Step 6: root `BEHAVIORS.md`, the tools Contract, and the tools Anatomy
      each reference `src/lingtai/tools/BEHAVIORS.md` exactly once, and the
      contract section carries exactly one `LP002` guard link.
- [ ] Step 7: the three reciprocity/pairing tests report `3 passed`.
- [ ] Step 8: the governance checker reports no violation under
      `src/lingtai/tools/` or in the root `BEHAVIORS.md`.

### Pass / Fail

Pass when every box above is observed. **Fail loudly** — do not soften the
report — if the contract section asserts that any LingTai tool family already
ships as an MCP plugin wrapper, that a wrapper runtime, universal compiler, or
conformance suite exists, that live model-facing tool-name collisions are
already fail-closed, or that external/third-party MCP schemas and legacy
transport paths have been converted; if step 3 finds plugin packaging wired
into `src/lingtai/tools/registry.py` while the contract still says no family is
wrapped; if any graph edge in step 6 is missing or duplicated; or if steps 7-8
report a failure naming a path under `src/lingtai/tools/` or the root
`BEHAVIORS.md`. Record the evidence trail, including the exact grep output and
test summary lines, in the task report. This task performs no writes: creating
a plugin package, editing a contract to make an assertion pass, or running the
code/package test suites to imply a wrapper works are forbidden side effects.
