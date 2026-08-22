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
  - src/lingtai/mcp_servers/telegram/plugin.py
  - src/lingtai/mcp_catalog.json
  - src/lingtai/services/plugin_registry.py
  - src/lingtai/kernel/base_agent/tools.py
  - scripts/check_docs_governance.py
  - tests/test_architecture_documents.py
maintenance: |
  Created during the every-contract-needs-behaviors sweep. Keep this file
  reciprocal with CONTRACT.md and ANATOMY.md (tridirectional loop): when an LTP
  envelope or settings rule changes, update the guarding LABT here in the same
  change. LP002 guards the additive `### Tool-to-MCP Plugin Contract` section:
  it verifies only what is true today (the section's scope-qualified status
  wording, its two-class governed surface, its single selected wrapper form,
  the document graph, and the cited current evidence). Its steps inspect the
  full governed boundary — the registry surface *and* the kernel-shipped MCP
  packages — so a registry-only grep is never treated as proof about every
  family. Keep every command copy-paste executable (one line, or a fenced block
  with explicit `\` continuations). When a family actually recuts onto a plugin
  wrapper, or when authoring-time line numbers drift, replace the affected
  evidence with that family's own proof in the same change rather than leaving
  a stale pass.
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
- **guards**: `lingtai-tool-protocol` §
  [Tool-to-MCP Plugin Contract](CONTRACT.md#tool-to-mcp-plugin-contract)
- **runner**: any LingTai agent with `shell` and `file` access to a clean
  checkout of the `lingtai-kernel` repository
- **prerequisites**: a clean checkout of the repository; a working repository
  virtual environment at `.venv/` (`uv venv --python 3.11 && uv pip install -e
  . pytest`, per `AGENTS.md`). Run every command below from the repository root
  (`git rev-parse --show-toplevel`). Every command block is copy-paste
  executable as written. No network, no agent runtime, and no MCP server is
  needed: this task inspects documents and source text only.
- **estimate**: ≈ 15 minutes

### Steps

1. Read `src/lingtai/tools/CONTRACT.md`, section `### Tool-to-MCP Plugin
   Contract` (it sits under `## Contract rules`, between `### Non-goals` and
   `### Relationship to current runtime`; at authoring time lines 277-507).
   Confirm its opening **Status** paragraph says the section is a migration
   target that converts nothing; that its negative claim is **scope-qualified**
   — no family registered through `src/lingtai/tools/registry.py` ships as an
   MCP plugin package today; that the kernel-shipped curated MCP families are
   named as the current first-party precedent for the selected form, with that
   stated as packaging evidence only rather than conformance; and that the
   families listed under `### Relationship to current runtime` are LTP
   *envelope* migrations rather than plugin wrappers or a compatible universal
   runtime.
2. Prove the old unqualified global negative is gone and that every surviving
   use of the phrase is scope-qualified:

   ```bash
   grep -n "No LingTai-owned family ships as an MCP plugin" src/lingtai/tools/CONTRACT.md
   grep -n "MCP plugin" src/lingtai/tools/CONTRACT.md
   ```

   The first command must print nothing and exit 1. The second must print
   exactly two matches, both inside this section: at authoring time line 303,
   inside the **Registry families** bullet whose own first line names
   `src/lingtai/tools/registry.py`, and line 501, which names that path on the
   matched line itself. Neither may be a bare global negative.
3. Confirm the section classifies the **whole** first-party boundary, not just
   the registry, and that exactly one wrapper form is selected:

   ```bash
   grep -n "Registry families\|Kernel-shipped MCP families" src/lingtai/tools/CONTRACT.md
   grep -n "Selected wrapper form" src/lingtai/tools/CONTRACT.md
   grep -n "separate standard, excluded" src/lingtai/tools/CONTRACT.md
   grep -n "plugin-admission engine" src/lingtai/tools/CONTRACT.md
   ```

   Expect: two governed-surface class bullets (authoring lines 300 and 305);
   two `Selected wrapper form` references (the normative paragraph at 327 and
   the back-reference at 497); exactly one `separate standard, excluded` line
   (349) putting external Agent Plugins v1.0.0 and raw third-party MCP schemas
   outside this conversion contract; and exactly two `plugin-admission engine`
   lines (353 and 476) disclaiming a generic manifest compiler or admission
   engine. Read the `**Selected wrapper form.**` paragraph and confirm the
   selected form is the `lingtai.mcp_servers._plugin.CuratedMcpPlugin`
   descriptor plus the curated catalog/package route.
4. Inspect the **registry class** of the governed surface — no family there is
   wrapped today:

   ```bash
   grep -n "lingtai\.mcp_servers\|CuratedMcpPlugin" src/lingtai/tools/registry.py
   ```

   Expect no output and shell exit status 1.
5. Inspect the **kernel-shipped MCP class** of the governed surface. A
   registry-only grep proves nothing about these families, so check them
   directly:

   ```bash
   grep -rln "CuratedMcpPlugin" src/lingtai/mcp_servers/*/plugin.py | sort
   grep -c "lingtai-curated" src/lingtai/mcp_catalog.json
   grep -rn "CuratedMcpPlugin" src/lingtai/mcp_servers/daemon_common src/lingtai/mcp_servers/daemon_email
   ```

   Expect exactly these six descriptor paths — `cloud_mail`, `feishu`, `imap`,
   `telegram`, `wechat`, `whatsapp` under `src/lingtai/mcp_servers/<name>/plugin.py`
   — then `6` curated catalog records, then no output and exit status 1 for the
   built-in daemon families. That is exactly the split the Contract's
   `**Governed surface.**` bullets state: the six curated families already ship
   in the selected form, the built-in daemon families are in the governed class
   without a descriptor, and neither fact is a conformance claim.
6. Prove the packaging precedent the section selects exists and is not a
   runtime:

   ```bash
   grep -n "plugin runtime" src/lingtai/mcp_servers/_plugin.py
   grep -n "must not declare the reserved" src/lingtai/mcp_servers/_plugin.py
   ```

   Expect exactly one match each: at authoring time line 11, reading "It
   deliberately is **not** a plugin runtime.", and line 201, raising
   `CuratedMcpPluginError`.
7. Prove the live-collision clause is still an open decision rather than a
   shipped promise:

   ```bash
   grep -n "Remove any existing schema with same name" src/lingtai/kernel/base_agent/tools.py
   ```

   Expect exactly one match (at authoring time line 162) inside `_add_tool`,
   immediately followed by a line rebuilding `agent._tool_schemas` with
   `s.name != name` — i.e. last registration replaces an existing tool of the
   same name. Confirm the contract records this as current behavior and an
   implementation target, and does **not** claim reject-before-mount,
   namespacing, or any deterministic precedence already holds.
8. Prove the tridirectional graph edges exist exactly once each:

   ```bash
   grep -c "src/lingtai/tools/BEHAVIORS.md" BEHAVIORS.md src/lingtai/tools/CONTRACT.md src/lingtai/tools/ANATOMY.md
   grep -n "behavior-lp002" src/lingtai/tools/CONTRACT.md
   grep -n "^  \[Tool-to-MCP Plugin Contract\](CONTRACT\.md#tool-to-mcp-plugin-contract)$" src/lingtai/tools/BEHAVIORS.md
   ```

   Expect `1` for each of the three files; exactly one
   `Guarded by: [LP002](BEHAVIORS.md#behavior-lp002)` line directly under the
   section heading; and exactly one anchored reverse clause link — the
   continuation line of this LABT's own `guards` annotation (authoring time
   line 71) — satisfying root `BEHAVIORS.md`'s "`guards` annotation + relative
   link back" rule. The anchor pattern deliberately excludes this step's own
   indented command text.
9. Run the governed-graph validation with the repository venv:

   ```bash
   .venv/bin/python -m pytest -q \
     tests/test_architecture_documents.py::test_root_architecture_documents_are_reciprocal_and_well_formed \
     tests/test_architecture_documents.py::test_governed_child_contracts_have_reciprocal_anatomy_pairs \
     tests/test_architecture_documents.py::test_governed_cross_document_links_are_reciprocal
   ```

   Expect `3 passed`. This covers only those three node IDs; the fourth test in
   that file is checked in step 10.
10. Run the documentation governance checker:

    ```bash
    .venv/bin/python scripts/check_docs_governance.py --check
    ```

    At authoring time it exits 1 with exactly five violations, none of them
    under `src/lingtai/tools/`: `IMPLEMENTATION_REPORT.md` (no frontmatter),
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
      nothing, whose negative claim is qualified to the
      `src/lingtai/tools/registry.py` surface.
- [ ] Step 2: no unqualified "No LingTai-owned family ships as an MCP plugin"
      sentence survives (exit 1), and both remaining `MCP plugin` matches are
      registry-scoped.
- [ ] Step 3: the governed surface names both classes — registry families and
      kernel-shipped MCP families — and exactly one wrapper form is selected,
      with external Agent Plugins v1.0.0 and raw third-party MCP schemas
      excluded and no manifest compiler or admission engine introduced.
- [ ] Step 4: `src/lingtai/tools/registry.py` contains no `lingtai.mcp_servers`
      import and no `CuratedMcpPlugin` reference (grep exit status 1).
- [ ] Step 5: exactly six curated `plugin.py` descriptors and six
      `lingtai-curated` catalog records exist, and the built-in daemon MCP
      families carry no descriptor (grep exit status 1) — matching the
      Contract's two-class governed-surface statement.
- [ ] Step 6: `src/lingtai/mcp_servers/_plugin.py` states it is not a plugin
      runtime and refuses a package that declares the reserved `manual` action.
- [ ] Step 7: `_add_tool` in `src/lingtai/kernel/base_agent/tools.py` replaces a
      same-named schema, and the contract's identifier clause presents the live
      collision policy as an explicit open maintainer decision.
- [ ] Step 8: root `BEHAVIORS.md`, the tools Contract, and the tools Anatomy
      each reference `src/lingtai/tools/BEHAVIORS.md` exactly once; the contract
      section carries exactly one `LP002` guard link; and this LABT carries
      exactly one relative link back to the guarded clause.
- [ ] Step 9: the three named reciprocity/pairing node IDs report `3 passed`.
- [ ] Step 10: the governance checker reports no violation under
      `src/lingtai/tools/` or in the root `BEHAVIORS.md`.

### Pass / Fail

Pass when every box above is observed. **Fail loudly** — do not soften the
report — if the contract section asserts that any LingTai tool family already
ships as a *conforming* MCP plugin wrapper under this section, if it makes an
unqualified global claim that no LingTai-owned family is packaged as an MCP
plugin, if it leaves the first-party wrapper form unselected or admits more
than one form, if it claims a wrapper runtime, universal compiler, manifest
compiler, admission engine, or conformance suite exists, if it claims live
model-facing tool-name collisions are already fail-closed, or if it claims
external/third-party MCP schemas and legacy transport paths have been
converted; if step 4 finds plugin packaging wired into
`src/lingtai/tools/registry.py` while the contract still says no registry
family is wrapped; if step 5's curated/daemon split disagrees with the
Contract's governed-surface bullets; if any graph edge in step 8 is missing or
duplicated; or if steps 9-10 report a failure naming a path under
`src/lingtai/tools/` or the root `BEHAVIORS.md`. Record the evidence trail,
including the exact grep output and test summary lines, in the task report.
This task performs no writes: creating a plugin package, editing a contract to
make an assertion pass, or running the code/package test suites to imply a
wrapper works are forbidden side effects.
