---
name: declared-host-tool-plugin-behavior-tests
behavior_version: 1
labt_version: 2
contract: CONTRACT.md
anatomy: ANATOMY.md
related_files:
  - src/lingtai/kernel/tool_plugin/CONTRACT.md
  - src/lingtai/kernel/tool_plugin/ANATOMY.md
  - src/lingtai/kernel/tool_plugin/__init__.py
  - src/lingtai/adapters/tool_plugin_host.py
  - src/lingtai/tools/mcp/__init__.py
  - src/lingtai/tools/avatar/__init__.py
  - src/lingtai/tools/context/__init__.py
  - src/lingtai/tools/daemon/__init__.py
  - src/lingtai/tools/email/__init__.py
  - src/lingtai/tools/file/__init__.py
  - tests/test_tool_plugin_declaration.py
  - tests/test_tool_family_avatar_migration.py
  - tests/test_context_declared_tool_plugin.py
  - tests/test_daemon.py
  - tests/test_email_official_tool_plugin.py
  - tests/test_file_tool_plugin_package.py
  - tests/test_file_tool_family.py
maintenance: |
  Created with the declared host-plugin primitive. Keep this file reciprocal
  with CONTRACT.md and ANATOMY.md (tridirectional loop): when a behavior clause
  of the declared host-plugin contract changes — the static-declaration rule,
  the least-privilege grant, the reserved official name list, or the
  check-before-bind ordering — update the guarding LABT here in the same change.
  Keep every command copy-paste executable from the repository root. When a
  further family recuts onto the contract, or when authoring-time line numbers
  drift, extend the affected evidence with that family's own focused proof rather
  than leaving a stale pass. The shared C register is family-generic and distinguishes
  target reserved names from candidate merge evidence. `mcp` is the shared-C base
  reference; Avatar, Context, Daemon, Email, and File are current vertical
  evidence. Ports remain least-privilege and tool-specific, while registrar
  mounts are runtime-bound rather
  than per-call Agent dispatch.
---
# Declared Host Tool Plugin Behavior Tests

Self-contained agent behavior tasks guarding the observable behavior clauses of
`src/lingtai/kernel/tool_plugin/CONTRACT.md`. Run every command from the
repository root (`git rev-parse --show-toplevel`) with the repository virtual
environment (`uv venv --python 3.11 && uv pip install -e . pytest`, per
`AGENTS.md`). No network, no agent runtime, and no MCP server is needed.

## Behavior TP001 — an official declaration is static, least-privilege, and never receives the Agent

- **id**: TP001
- **title**: an official declaration is static, least-privilege, and never receives the Agent
- **guards**: `declared-host-tool-plugin` §
  [Purpose](CONTRACT.md#purpose), § Behavior, § Port
- **runner**: any LingTai agent with `shell` and `file` access to a clean
  checkout of the `lingtai-kernel` repository
- **prerequisites**: a clean checkout; a working `.venv/`
- **estimate**: ≈ 15 minutes

### Steps

1. Prove the declaration exists and validates before any Agent does:

   ```bash
   PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -c "import sys; sys.path.insert(0, 'src'); from lingtai.tools.mcp import DECLARATION as mcp; from lingtai.tools.file import DECLARATION as file; print(mcp.name, mcp.actions, mcp.public_actions, mcp.requires); print(file.name, file.actions, file.public_actions, file.requires)"
   ```

   Expect `mcp ('info',) ('info', 'manual') ('workdir', 'prompt_section')` and
   `file ('read', 'write', 'edit', 'glob', 'grep') ('read', 'write', 'edit',
   'glob', 'grep', 'manual') ('workdir', 'file_io')`. No `Agent` was constructed;
   each reserved `manual` action is appended, not declared.

2. Prove the public model-facing surface is unchanged by the recut:

   ```bash
   PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -c "import sys; sys.path.insert(0, 'src'); from lingtai.tools.mcp import get_schema; s = get_schema(); print(sorted(s['properties']), s['properties']['action']['enum'], s['additionalProperties'])"
   ```

   Expect `['action', 'input', 'reasoning', 'summarize'] ['info', 'manual']
   False`.

3. Prove a declaration is granted exactly its `requires` and nothing more:

   ```bash
   PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -c "import sys; sys.path.insert(0, 'src'); from lingtai.kernel.tool_plugin import GRANTABLE_HOST_PORTS, ToolPluginHost; from lingtai.tools.file import DECLARATION; h = ToolPluginHost.grant(DECLARATION, {'workdir': object(), 'file_io': object(), 'prompt_section': object()}); print(GRANTABLE_HOST_PORTS, h.granted); h.prompt_section"
   ```

   Expect `('workdir', 'prompt_section', 'avatar_parent', 'context_runtime',
   'daemon_runtime', 'email_runtime', 'file_io') ('workdir', 'file_io')` printed,
   then an `AttributeError` whose message says the plugin *did not require host
   port* `'prompt_section'`. Confirm `tool_mount` is absent from
   `GRANTABLE_HOST_PORTS`: File receives exactly `WorkdirPort` plus `FileIOPort`,
   even when the host table contains another grantable port.

4. Prove the family reaches the live Agent body only through granted ports:

   ```bash
   grep -n "def _reconcile\|def _build_family\|def _bind" src/lingtai/tools/mcp/__init__.py
   grep -n "working_dir = host.workdir.path" src/lingtai/tools/mcp/__init__.py
   grep -n "host.prompt_section.write_protected_section(xml)" src/lingtai/tools/mcp/__init__.py
   grep -n "host.workdir, host.file_io" src/lingtai/tools/file/__init__.py
   grep -n "class AgentFileIOAdapter\|extra_ports_for" src/lingtai/adapters/tool_plugin_host.py src/lingtai/tools/file/__init__.py
   ```

   Expect MCP's three internals to take `host`, then exactly one match each for
   its two port calls. Expect File's operations to receive only `host.workdir`
   and `host.file_io`, and its setup to supply `AgentFileIOAdapter` only through
   `extra_ports_for`. Read that adapter and confirm it has no `Any`-typed File
   method/result, `__getattr__`, generic dispatch, Agent slot, or mount method.
   Each `setup(agent, **_ignored)` still takes the Agent because it *is* the
   composition wiring; no binder or bound family does.

5. Prove the kernel still owns only the shape — no import of any tool package
   anywhere under `src/lingtai/kernel/`:

   ```bash
   grep -rnE "^[[:space:]]*(from|import)[[:space:]]+.*lingtai\.tools" src/lingtai/kernel/
   PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider \
     tests/test_kernel_isolation.py::test_kernel_has_no_lingtai_submodules
   ```

   Expect no grep output (exit status 1), then `1 passed` from the AST-based
   kernel isolation sweep, which permits kernel-relative imports while refusing
   imports of the outer `lingtai` or `tools` packages.

6. Prove the declared surface and the shipped surface are the same surface,
   not two literals that happen to match:

   ```bash
   grep -n "DECLARATION.manual\|DECLARATION.name\|DECLARATION.input_schemas\|DECLARATION.manual_input_schema" src/lingtai/tools/mcp/__init__.py src/lingtai/tools/file/__init__.py
   PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider \
     tests/test_tool_plugin_declaration.py::test_official_mcp_mount_uses_controlled_host_and_real_dispatch \
     tests/test_file_tool_plugin_package.py::test_file_declaration_is_static_and_derives_the_public_surface \
     tests/test_file_tool_plugin_package.py::test_file_bind_accepts_only_its_narrow_ports \
     tests/test_file_tool_plugin_package.py::test_official_file_mount_preserves_real_operations_and_packaged_manual
   ```

   Expect both families' builders/binds to read name, per-action schemas, and
   installed-manual destination back out of `DECLARATION`, then `4 passed`.
   File's live proof also asserts the package body returns from
   `capabilities/file-manual` and no `capabilities/file` destination exists.

7. Run the contract suite:

   ```bash
   PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider \
     tests/test_tool_plugin_declaration.py tests/test_tool_family_avatar_migration.py \
     tests/test_context_declared_tool_plugin.py tests/test_daemon.py \
     tests/test_email_official_tool_plugin.py tests/test_file_tool_plugin_package.py \
     tests/test_file_tool_family.py
   ```

### Expected evidence

- [ ] Step 1: MCP and File `DECLARATION`s import and validate with no Agent;
      `manual` is in each `public_actions` but not in either `actions`.
- [ ] Step 2: the closed LTP root and the `["info", "manual"]` enum are
      unchanged.
- [ ] Step 3: only `requires` ports are granted; an ungranted port raises
      `AttributeError`; `tool_mount` is not grantable at all.
- [ ] Step 4: MCP's workdir/prompt operations and File's workdir/file-I/O
      operations go only through granted ports; `AgentFileIOAdapter` has no Any,
      generic dispatch, whole Agent, or mount surface; each `setup` is wiring only.
- [ ] Step 5: no file under `src/lingtai/kernel/` imports `lingtai.tools`, by
      grep and by the AST sweep.
- [ ] Step 6: MCP and File derive name, `input` schemas, and manual destination
      from their declarations; the four named live/static tests pass, including
      File's established `file-manual` destination and absent `file` destination.
- [ ] Step 7: the shared suite plus Avatar's, Context's, Daemon's, Email's, and
      File's focused declared slices pass.

### Pass / Fail

Pass when every box above is observed. **Fail loudly** if a declaration needs a
live Agent to construct, if an official family's public surface changed, if an
ungranted port is reachable, if `tool_mount` becomes grantable, if any code path hands a
whole `Agent` to a plugin, if File's adapter uses `Any`, generic dispatch, or a
mount operation, if a family restates its name, its per-action input schemas, or
its manual destination instead of deriving them from its own declaration, if
File installs anywhere except `file-manual`, or if the kernel package imports
`lingtai.tools`.
Record the exact command output in the task report. This task performs no
writes.

## Behavior TP002 — a reserved official name is claimed once and a conflict is refused before any bind or mount

- **id**: TP002
- **title**: a reserved official name is claimed once and a conflict is refused before any bind or mount
- **guards**: `declared-host-tool-plugin` §
  [Contract rules](CONTRACT.md#contract-rules)
- **runner**: any LingTai agent with `shell` and `file` access to a clean
  checkout of the `lingtai-kernel` repository
- **prerequisites**: a clean checkout; a working `.venv/`
- **estimate**: ≈ 15 minutes

### Steps

1. Read the kernel-owned reserved list and confirm it holds names only:

   ```bash
   grep -n "OFFICIAL_TOOL_PLUGIN_NAMES" src/lingtai/kernel/tool_plugin/__init__.py
   ```

   Expect the module docstring, `__all__`, module-level tuple, and registrar check/error as the relevant matches.
   Confirm the literal is exactly `('mcp', 'avatar', 'context', 'daemon',
   'email', 'file')` in that order and contains bare names only — no module path,
   import, or family behavior.

2. Prove a conflicting declaration is refused with nothing bound and nothing
   mounted:

   ```bash
   PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider \
     tests/test_tool_plugin_declaration.py::test_unreserved_name_is_refused_before_any_bind_or_mount \
     tests/test_tool_plugin_declaration.py::test_duplicate_name_in_one_batch_is_refused_before_any_mount \
     tests/test_tool_plugin_declaration.py::test_a_second_different_declaration_cannot_take_a_claimed_name \
     tests/test_tool_plugin_declaration.py::test_repeat_registration_of_the_same_declaration_is_idempotent \
     tests/test_tool_plugin_declaration.py::test_activation_runs_before_mount_and_only_after_the_name_checks
   ```

   Expect `5 passed`.

3. Prove the refusal reaches a live agent's tool surface, including the
   review's forged transaction and mutable-claim-map attempts:

   ```bash
   PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider \
     tests/test_tool_plugin_declaration.py::test_boot_claims_the_official_name_and_mounts_exactly_one_mcp_tool \
     tests/test_tool_plugin_declaration.py::test_a_foreign_declaration_cannot_take_the_live_mcp_name \
     tests/test_tool_plugin_declaration.py::test_registration_after_the_tool_surface_is_sealed_raises \
     tests/test_tool_plugin_declaration.py::test_public_mount_bypass_cannot_publish_a_foreign_bound_plugin \
     tests/test_tool_plugin_declaration.py::test_a_constructed_transaction_cannot_replace_the_canonical_mcp_binding \
     tests/test_tool_plugin_declaration.py::test_clearing_the_backing_claim_cannot_admit_a_foreign_declaration \
     tests/test_tool_plugin_declaration.py::test_public_claim_view_cannot_clear_the_live_claim_or_admit_a_foreign_declaration
   ```

   Expect `7 passed`: boot claims the official name, foreign registration and
   post-seal registration are refused, an arbitrary bound plugin and a directly
   constructed transaction cannot replace handler/schema/claim, clearing the
   mutable backing map cannot admit a foreign declaration, and the public claim
   view cannot be used to unlock one. The provenance promise is for ordinary
   public/declared and extension paths; Python trusted internals are not an
   absolute security boundary.

4. Confirm the registrar's ordering is structural, not incidental: read
   `register_official_tool_plugins` in
   `src/lingtai/kernel/tool_plugin/__init__.py` and verify the name-checking
   loop over the whole batch completes before the second loop performs the
   first `ToolPluginHost.grant` / `bind` / `activate` / `mount_tool`; verify
   issuance records the exact bind result and claims receive only the mounted
   transaction.

5. Prove the refusal is *observable* — that it fails the boot instead of being
   absorbed as a skipped capability:

   ```bash
   grep -n "class ToolPluginError" src/lingtai/kernel/tool_plugin/__init__.py
   grep -n "except (ValueError, ImportError, TypeError)" src/lingtai/agent.py
   PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider \
     tests/test_tool_plugin_declaration.py::test_an_official_name_conflict_is_not_swallowed_as_capability_skipped \
     tests/test_tool_plugin_declaration.py::test_an_unreserved_official_name_fails_the_boot_rather_than_skipping_mcp \
     tests/test_tool_plugin_declaration.py::test_a_missing_host_port_fails_the_boot_rather_than_skipping_mcp \
     tests/test_tool_plugin_declaration.py::test_only_name_conflicts_are_all_or_nothing_across_a_batch \
     tests/test_tool_plugin_declaration.py::test_a_refresh_that_disables_the_capability_drops_its_official_claim \
     tests/test_tool_plugin_declaration.py::test_a_refresh_that_keeps_the_capability_re_claims_the_official_name
   ```

   Expect `ToolPluginError(Exception)` — **not** `ValueError` — beside the two
   Composition-Root capability guards that catch
   `(ValueError, ImportError, TypeError)` and log `capability_skipped`, then
   `6 passed`: a conflict, an unreserved name, and a missing host port each
   reach the caller of `_setup_capability` (two of them failing a real
   `Agent(...)` boot), a mid-batch host-port failure is *not* rolled back, and
   the claim map tracks the live namespace across refresh.

6. Confirm the non-official mount path is untouched:

   ```bash
   grep -n "Remove any existing schema with same name" src/lingtai/kernel/base_agent/tools.py
   ```

   Expect one match inside `_add_tool`,
   immediately followed by the line rebuilding `agent._tool_schemas` with
   `s.name != name`. The reserved-name check is at this common model-facing
   boundary: generic `add_tool` refuses `mcp`, while the registrar-issued
   canonical one-use transaction is the sole official route. External
   stdio/HTTP catalogs are preflighted and rejected before publication, and
   same-name replacement remains for nonreserved tools.

### Expected evidence

- [ ] Step 1: `OFFICIAL_TOOL_PLUGIN_NAMES` is the exact ordered static tuple
      `mcp, avatar, context, daemon, email, file` of bare names.
- [ ] Step 2: `5 passed` — an unreserved name, an in-batch duplicate, and a
      second declaration against a live claim are each refused with zero binds,
      zero mounts, and an unchanged claim map; the same declaration re-registers
      idempotently; `activate` precedes `mount`.
- [ ] Step 3: `7 passed` — boot claims `mcp` and mounts exactly one `mcp` tool,
      a foreign declaration cannot take it, a post-seal mount raises, the old
      public adapter/factory bypass and a forged transaction are unavailable,
      backing-map tampering cannot admit a foreign declaration, and the public
      claim view cannot unlock one.
- [ ] Step 4: the batch-wide check loop precedes the bind/mount loop in source
      order.
- [ ] Step 5: `6 passed` — official-plugin failures propagate past the
      capability skip-guard, the all-or-nothing promise is scoped to names, and
      the claim map matches the live namespace across refresh and disable.
- [ ] Step 6: `_add_tool`'s same-name replacement is still present and
      unmodified.

### Pass / Fail

Pass when every box above is observed. **Fail loudly** if a name conflict is
detected only after a bind, an activate, or a mount; if a second declaration can
overwrite a claimed official name; if a refused batch leaves any tool mounted or
any claim recorded; if any of these failures is downgraded to a
`capability_skipped` log line instead of failing the boot; if a claim outlives
the tool it claims across a refresh; if the reserved list grows a module path,
an import, or a discovery mechanism; or if third-party mount semantics in
`_add_tool` changed.
Record the exact command output in the task report. This task performs no
writes.
