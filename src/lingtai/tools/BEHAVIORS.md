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
  - src/lingtai/kernel/tool_plugin/CONTRACT.md
  - src/lingtai/tools/mcp/__init__.py
  - src/lingtai/tools/avatar/__init__.py
  - src/lingtai/tools/context/__init__.py
  - src/lingtai/tools/daemon/__init__.py
  - src/lingtai/tools/email/__init__.py
  - src/lingtai/tools/file/__init__.py
  - src/lingtai/tools/plugin/__init__.py
  - tests/test_tool_plugin_declaration.py
  - tests/test_tool_family_avatar_migration.py
  - tests/test_context_declared_tool_plugin.py
  - tests/test_email_official_tool_plugin.py
  - tests/test_file_tool_plugin_package.py
  - tests/test_plugin_tool.py
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
  change. LP002 guards the `### Tool-to-MCP Plugin Contract` section: it
  verifies only what is true today (the section's scope-qualified status
  wording — current `mcp` base evidence, Avatar's, Context's, Daemon's,
  Email's, File's, Plugin's, Notification's, Shell's, Soul's, System's,
  Task Card's, and Vision's separately landed vertical evidence, plus the
  family-generic C integration register's remaining targets —
  wording — current `mcp` base evidence, Avatar's, Context's, Daemon's, Email's, and Notification's
  separately landed vertical evidence, and the family-generic C integration register's remaining targets —
  its two-class governed surface, its single selected form as the kernel-owned declared
  host-plugin contract, the retained
  and reclassified curated transport route, the resolved official-name
  collision decision and its exact scope, the document graph, and the cited
  current evidence). Its steps inspect the
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

## Behavior LP002 — the shared declared host-plugin contract is family-generic; `mcp` is base evidence, Avatar, Context, Daemon, Email, and File are landed evidence, and the remaining C register is a target

- **id**: LP002
- **title**: the shared declared host-plugin contract is family-generic; `mcp` is base evidence, Avatar, Context, Daemon, Email, and File are landed evidence, and the remaining C register is a target
## Behavior LP002 — the shared declared host-plugin contract is family-generic; `mcp` is current base evidence, Avatar, Context, Daemon, Email, and Notification are landed evidence, and the remaining C register is a target

- **id**: LP002
- **title**: the shared declared host-plugin contract is family-generic; `mcp` is current base evidence, Avatar, Context, Daemon, Email, and Notification are landed evidence, and the remaining C register is a target
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
   `### Relationship to current runtime`).
   Confirm its opening **Status** paragraph distinguishes the current base `mcp`
   evidence and the family-generic C integration register's remaining targets
   from the separately landed `avatar`, `context`, `daemon`, `email`, `file`, and
   `plugin` evidence; that `mcp` is the base reference and the `DECLARATION`
   values in
   `src/lingtai/tools/{avatar,context,daemon,email,file,plugin}/__init__.py` are
   actual landed vertical proof; that File is sixth after Email and requires only
   `workdir`/`file_io`; that Plugin is seventh and requires only
   `workdir`/`prompt_section`/`plugin_catalog`; that Task Card is twelfth and
   requires only `workdir`/`shutdown`/`task_card_lifecycle`/
   `task_card_notifications` with its notification port closed to five
   operations; that Vision is thirteenth and requires only
   `workdir`/`active_provider`/`configuration`; that the C register's remaining
   name (`web`) is a target rather
   than candidate-merge claims; and that each claim is scoped to the declaration
   clauses only; that every remaining negative claim
   is **scope-qualified** — every other family registered through
   `src/lingtai/tools/registry.py` is a future migration unit and none ships as
   an MCP plugin package today; that the kernel-shipped curated MCP families
   are named as evidence for the *external stdio transport* route rather than
   as conformance; and that the families listed under
   `### Relationship to current runtime` are LTP *envelope* migrations rather
   than a compatible universal runtime.
2. Prove the old unqualified global negative is gone and that every surviving
   use of the phrase is scope-qualified:

   ```bash
   grep -n "No LingTai-owned family ships as an MCP plugin" src/lingtai/tools/CONTRACT.md
   grep -n "MCP plugin" src/lingtai/tools/CONTRACT.md
   ```

   The first command must print nothing and exit 1. The second must print
   exactly three matches, all inside this section and all scope-qualified: line
   327 closes the **Status** paragraph's sentence about every other registry
   family; line 346 is inside the **Registry families** bullet; and line 662 names
   the registry path on the matched line itself. None may be a bare global
   negative.
3. Confirm the section classifies the **whole** first-party boundary, not just
   the registry, and that exactly one form is selected:

   ```bash
   grep -n "Registry families\|Kernel-shipped MCP families" src/lingtai/tools/CONTRACT.md
   grep -n "Selected wrapper form" src/lingtai/tools/CONTRACT.md
   grep -n "remain a \*\*separate standard\*\*" src/lingtai/tools/CONTRACT.md
   grep -n "plugin-admission engine" src/lingtai/tools/CONTRACT.md
   ```

   Expect: two governed-surface class bullets (lines 341 and 348); two `Selected
   wrapper form` references (the normative paragraph at 372 and back-reference at
   656); exactly one `remain a **separate standard**` line (426); and exactly
   three `plugin-admission engine` lines (433, 594, 604) disclaiming a generic
   manifest compiler, admission engine, and wrapper runtime.

   Read the `**Selected wrapper form.**` paragraph and confirm the selected
   form is the kernel-owned declared host-plugin contract
   (`src/lingtai/kernel/tool_plugin/CONTRACT.md`): one static
   `ToolPluginDeclaration` per official family, a name reserved in the
   kernel-owned `OFFICIAL_TOOL_PLUGIN_NAMES` list, and least-privilege host
   ports instead of the whole `Agent`. Confirm the paragraph then states
   explicitly that the previously selected mandatory external-stdio package
   form was **wrong** and is corrected, and that the curated
   `CuratedMcpPlugin` + `src/lingtai/mcp_catalog.json` route is **retained
   unchanged and reclassified** as one external-transport/launcher adapter over
   a declaration — not the required form of every official tool. Confirm the
   `**Non-goals**` paragraph bans a generic wrapper *runtime* while stating
   that the one shared declared contract type is deliberately not banned.
4. Inspect the **registry class** of the governed surface — no family there is
   wrapped as an MCP plugin package, and the registry is still a hand-edited
   static table with no plugin packaging and no discovery:

   ```bash
   grep -n "lingtai\.mcp_servers\|CuratedMcpPlugin" src/lingtai/tools/registry.py
   ```

   Expect no output and shell exit status 1.

   Then prove all thirteen landed declarations — the current base `mcp`, Avatar,
   Context, Daemon, Email, File, Plugin, Notification, Shell, Soul, System,
   Task Card, and Vision — none of which goes through packaging; the C register
   is broader but its remaining candidate-local proof stays separate:

   ```bash
   PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -c "import sys; sys.path.insert(0, 'src'); from lingtai.tools.mcp import DECLARATION as mcp; from lingtai.tools.avatar import DECLARATION as avatar; from lingtai.tools.context import DECLARATION as context; from lingtai.tools.daemon import DECLARATION as daemon; from lingtai.tools.email import DECLARATION as email; from lingtai.tools.file import DECLARATION as file; from lingtai.tools.plugin import DECLARATION as plugin; from lingtai.tools.notification import DECLARATION as notification; from lingtai.tools.bash._tool_family import DECLARATION as shell; from lingtai.tools.soul import DECLARATION as soul; from lingtai.tools.system import DECLARATION as system; from lingtai.tools.task_card import DECLARATION as task_card; from lingtai.tools.vision import DECLARATION as vision; from lingtai.kernel.tool_plugin import OFFICIAL_TOOL_PLUGIN_NAMES; declarations=(mcp, avatar, context, daemon, email, file, plugin, notification, shell, soul, system, task_card, vision); print(tuple((d.name, d.requires) for d in declarations)); print(OFFICIAL_TOOL_PLUGIN_NAMES); print(tuple(d.name for d in declarations) == OFFICIAL_TOOL_PLUGIN_NAMES)"
   PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider \
     tests/test_file_tool_plugin_package.py tests/test_file_tool_family.py \
     tests/test_plugin_tool.py tests/test_task_card_notifications.py \
     tests/test_tool_family_vision_migration.py
   ```

   Expect thirteen ordered pairs whose names are `mcp, avatar, context, daemon,
   email, file, plugin, notification, shell, soul, system, task_card, vision`,
   with requires respectively `workdir/prompt_section`, `workdir/avatar_parent`,
   `workdir/context_runtime`, `workdir/daemon_runtime`,
   `workdir/email_runtime`, `workdir/file_io`,
   `workdir/prompt_section/plugin_catalog`, `workdir/notification_state`,
   `workdir/notifications/configuration`, `workdir/soul_runtime`,
   `workdir/system_runtime/identity`,
   `workdir/shutdown/task_card_lifecycle/task_card_notifications`, and
   `workdir/active_provider/configuration`; then expect
   exactly `('mcp', 'avatar', 'context', 'daemon', 'email', 'file', 'plugin',
   'notification', 'shell', 'soul', 'system', 'task_card', 'vision')`, then
   `True`. All thirteen declarations construct at import with no Agent, server,
   transport, or catalog record. The two File focused suites pass, proving its narrow
   adapter/grant, one mount, unchanged operations, sole package manual body at
   `file-manual`, absent `capabilities/file`, and package-data source routes;
   Plugin's focused suite passes, proving its read-only action boundary, its
   protected-field skill projection with the vanilla skills catalog left closed,
   and its detached per-read catalog projection; Task Card's typed notification
   suite passes, proving exact error/recovered/limit and reminder wire parity
   through the production five-operation port adapter and foreign
   source/channel/field refusal; Vision's focused suite passes, proving its
   four-action schema/dispatch, active-provider default routing,
   allowed-preset own-credential borrowing with no automatic fallback, and
   `check`/`list`/`manual` no-request boundaries.
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
   `**Governed surface.**` bullets state: the six curated families carry the
   retained external-transport descriptor/catalog form, while the built-in
   daemon MCP families are in that governed external-transport class without a
   descriptor; neither fact is evidence that those packages conform to the
   selected declared host-plugin form.
6. Prove the packaging precedent the section selects exists and is not a
   runtime:

   ```bash
   grep -n "plugin runtime" src/lingtai/mcp_servers/_plugin.py
   grep -n "must not declare the reserved" src/lingtai/mcp_servers/_plugin.py
   ```

   Expect exactly one match each: at authoring time line 11, reading "It
   deliberately is **not** a plugin runtime.", and line 201, raising
   `CuratedMcpPluginError`.
7. Prove the live-collision clause is enforced at the final common model-facing
   boundary, while nonreserved replacement remains intact:

   ```bash
   grep -n "Remove any existing schema with same name" src/lingtai/kernel/base_agent/tools.py
   PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider \
     tests/test_mcp_capability.py::test_direct_generic_mount_cannot_replace_official_mcp_and_nonreserved_replaces \
     tests/test_mcp_capability.py::test_external_mcp_cannot_replace_official_mcp_or_leave_routes \
     tests/test_tool_plugin_declaration.py::test_a_second_different_declaration_cannot_take_a_claimed_name \
     tests/test_tool_plugin_declaration.py::test_public_mount_bypass_cannot_publish_a_foreign_bound_plugin \
     tests/test_tool_plugin_declaration.py::test_a_constructed_transaction_cannot_replace_the_canonical_mcp_binding \
     tests/test_tool_plugin_declaration.py::test_clearing_the_backing_claim_cannot_admit_a_foreign_declaration \
     tests/test_tool_plugin_declaration.py::test_public_claim_view_cannot_clear_the_live_claim_or_admit_a_foreign_declaration \
     tests/test_mcp_capability.py::test_sealed_agent_post_preflight_failure_closes_client_and_rolls_back
   ```

   Expect the parameterized external and sealed-failure tests to run for both
   stdio and HTTP, and the focused set to pass. Expect one grep match inside
   `_add_tool`, immediately followed by a line rebuilding `agent._tool_schemas`
   with `s.name != name` — i.e. last registration still replaces an existing
   tool of the same name for nonreserved mounts — then the focused set passes.
   Confirm the contract's identifier clause states the decision (official names
   reserved first, not overwritable, refused before any bind or generic
   `add_tool`) and its exact scope: `_add_tool` remains the common boundary,
   external stdio/HTTP catalogs are rejected before client metadata/routes are
   published, post-preflight mount failures restore the connection snapshot and
   close/remove the new client, and the registrar issues a canonical one-use
   transaction whose mounted result alone can claim the official name. Private
   Python state remains trusted in-process rather than an absolute security
   boundary.

8. Prove the tridirectional graph edges exist exactly once each:

   ```bash
   grep -c "src/lingtai/tools/BEHAVIORS.md" BEHAVIORS.md src/lingtai/tools/CONTRACT.md src/lingtai/tools/ANATOMY.md
   grep -n "behavior-lp002" src/lingtai/tools/CONTRACT.md
   grep -n "^  \[Tool-to-MCP Plugin Contract\](CONTRACT\.md#tool-to-mcp-plugin-contract)$" src/lingtai/tools/BEHAVIORS.md
   ```

   Expect `1` for each of the three files; exactly one
   `Guarded by: [LP002](BEHAVIORS.md#behavior-lp002)` line directly under the
   section heading (authoring time line 292); and exactly one anchored reverse
   clause link — the continuation line of this LABT's own `guards` annotation
   (authoring time line 91) — satisfying root `BEHAVIORS.md`'s "`guards`
   annotation + relative link back" rule. The anchor pattern deliberately
   excludes this step's own indented command text.

   Then confirm the newly selected form is a governed component in its own
   right, reciprocally linked:

   ```bash
   grep -n "^  - src/lingtai/kernel/tool_plugin/CONTRACT.md$" CONTRACT.md src/lingtai/tools/CONTRACT.md
   grep -n "^  - src/lingtai/tools/CONTRACT.md$" src/lingtai/kernel/tool_plugin/CONTRACT.md
   ```

   Expect exactly one `related_files` entry from each of the three files: the
   root contract indexes the new governed child once (authoring time line 29),
   and the two child contracts list each other once (tools line 7, tool_plugin
   line 13). Prose references to those paths elsewhere in the same files are
   deliberately excluded by the anchored pattern.
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

- [ ] Step 1: the section opens by distinguishing base `mcp` evidence, Avatar's,
      Context's, Daemon's, Email's, File's, Plugin's, Notification's, Shell's,
      Soul's, System's, Task Card's, and Vision's actual landed vertical
      evidence, and the family-generic C register's remaining target
      (`web`), with File sixth after Email, Plugin seventh, Task Card
      twelfth, Vision thirteenth, and every remaining negative claim properly
      scoped.
- [ ] Step 1: the section exists in `src/lingtai/tools/CONTRACT.md` and opens
      by distinguishing current `mcp` evidence, Avatar's, Context's, Daemon's, Email's, and
      Notification's actual landed vertical evidence, and the family-generic C integration register's
      remaining targets, with each remaining negative claim properly scoped.
- [ ] Step 2: no unqualified "No LingTai-owned family ships as an MCP plugin"
      sentence survives (exit 1), and all three remaining `MCP plugin` matches
      are registry-scoped.
- [ ] Step 3: the governed surface names both classes — registry families and
      kernel-shipped MCP families — exactly one form is selected and it is the
      kernel-owned declared host-plugin contract, the previous mandatory
      external-stdio form is named as the corrected error, the curated route is
      retained and reclassified as one transport adapter, external Agent
      Plugins v1.0.0 and raw third-party MCP schemas stay excluded, and no
      manifest compiler, admission engine, or wrapper runtime is introduced.
- [ ] Step 4: `registry.py` contains no MCP-server packaging reference (grep
      exit 1), all thirteen declarations import with no Agent and require only
      their named narrow ports, File is exactly `workdir`/`file_io`, Plugin
      exactly `workdir`/`prompt_section`/`plugin_catalog`, Task Card exactly
      `workdir`/`shutdown`/`task_card_lifecycle`/`task_card_notifications`, and
      Vision exactly `workdir`/`active_provider`/`configuration`; the
      reservation is exactly `('mcp', 'avatar', 'context', 'daemon', 'email',
      'file', 'plugin', 'notification', 'shell', 'soul', 'system',
      'task_card', 'vision')`; both File focused suites pass with one manual
      body/destination and one mount, Plugin's suite passes with its read-only
      boundary, protected-field projection, closed vanilla-skills namespace, and
      detached catalog state, Task Card's typed notification suite passes, and
      Vision's focused suite passes.
- [ ] Step 4: `src/lingtai/tools/registry.py` contains no `lingtai.mcp_servers`
      import and no `CuratedMcpPlugin` reference (grep exit status 1), and all
      thirteen landed `DECLARATION`s import with no Agent: `mcp` requires only
      `workdir`/`prompt_section`, Avatar only `workdir`/`avatar_parent`, Context
      only `workdir`/`context_runtime`, Daemon only `workdir`/`daemon_runtime`,
      Email only `workdir`/`email_runtime`, Notification only
      `workdir`/`notification_state`, Task Card only
      `workdir`/`shutdown`/`task_card_lifecycle`/`task_card_notifications`, and
      Vision only `workdir`/`active_provider`/`configuration`; the
      official reservation is the exact thirteen-name tuple above.
- [ ] Step 5: exactly six curated `plugin.py` descriptors and six
      `lingtai-curated` catalog records exist, and the built-in daemon MCP
      families carry no descriptor (grep exit status 1) — matching the
      Contract's two-class governed-surface statement.
- [ ] Step 6: `src/lingtai/mcp_servers/_plugin.py` states it is not a plugin
      runtime and refuses a package that declares the reserved `manual` action.
- [ ] Step 7: `_add_tool` in `src/lingtai/kernel/base_agent/tools.py` still
      replaces a same-named schema; the two named tests pass; and the
      contract's identifier clause states the decided official-name policy
      together with its exact, narrower scope.
- [ ] Step 8: root `BEHAVIORS.md`, the tools Contract, and the tools Anatomy
      each reference `src/lingtai/tools/BEHAVIORS.md` exactly once; the contract
      section carries exactly one `LP002` guard link; this LABT carries exactly
      one relative link back to the guarded clause; and the declared
      host-plugin contract is indexed by the root contract and reciprocally
      linked with the tools contract.
- [ ] Step 9: the three named reciprocity/pairing node IDs report `3 passed`.
- [ ] Step 10: the governance checker reports no violation under
      `src/lingtai/tools/` or in the root `BEHAVIORS.md`.

### Pass / Fail

Pass when every box above is observed. **Fail loudly** — do not soften the
report — if the contract section asserts that any family other than `mcp`,
`avatar`, `context`, `daemon`, `email`, `file`, or `plugin` is already declared;
if File is not sixth, does not require exactly `workdir`/`file_io`, exposes
Agent/generic dispatch/mount authority, or installs a second/non-`file-manual`
body; if Plugin is not seventh, does not require exactly
`workdir`/`prompt_section`/`plugin_catalog`, gains registration/prune/launch/
config-write/mount authority, or claims its skills enter the vanilla skills
catalog; if it treats a
curated or built-in MCP package as already conforming to the selected declared
host-plugin form merely because an external-transport descriptor, catalog
record, or package exists; if it makes an unqualified global claim that no
LingTai-owned family is packaged as an MCP plugin; if it leaves the first-party form
unselected or admits more than one form, if it re-mandates an external stdio
package for every official tool, if it removes or weakens the curated
`CuratedMcpPlugin`/`mcp_catalog.json` route rather than reclassifying it, if it
claims a wrapper runtime, universal compiler, manifest compiler,
plugin-admission engine, discovery mechanism, or conformance suite exists, if
it claims collisions between a *third-party* MCP tool and a reserved official
name are not fail-closed on the normal public stdio/HTTP external-catalog paths
before publication, or if it mislabels a generic unrelated failure as a
reserved-name collision result instead of requiring focused collision evidence,
or if it claims external/third-party MCP schemas and legacy transport paths have
been converted; if step 4 finds plugin
packaging wired into `src/lingtai/tools/registry.py`; if step 5's
curated/daemon split disagrees with the Contract's governed-surface bullets; if
step 7 shows an official name conflict detected only after a bind or a mount;
if any graph edge in step 8 is missing or duplicated; or if steps 9-10 report a
failure naming a path under `src/lingtai/tools/` or the root `BEHAVIORS.md`.
Record the evidence trail, including the exact grep output and test summary
lines, in the task report. This task performs no writes: creating a plugin
package or editing a contract to make an assertion pass are forbidden side
effects; the pytest node IDs named in steps 4, 7, and 9 are read-only
verification and are the only code the task runs.
