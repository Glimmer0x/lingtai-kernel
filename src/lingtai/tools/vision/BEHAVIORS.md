---
name: vision-behavior-tests
behavior_version: 1
labt_version: 2
contract: CONTRACT.md
anatomy: ANATOMY.md
related_files:
  - src/lingtai/tools/vision/CONTRACT.md
  - src/lingtai/tools/vision/ANATOMY.md
  - src/lingtai/tools/vision/__init__.py
  - src/lingtai/tools/vision/plugin.py
  - src/lingtai/tools/_plugin.py
  - src/lingtai/tools/vision/settings.py
maintenance: |
  Created during the every-contract-needs-behaviors sweep. Keep this file
  reciprocal with CONTRACT.md and ANATOMY.md (tridirectional loop): when a
  vision tool behavior clause changes, update the guarding LABT here in the
  same change.
---
# Vision Capability Behavior Tests

Self-contained agent behavior tasks guarding the observable behavior clauses of
`src/lingtai/tools/vision/CONTRACT.md` (exact analyze/manual success shapes,
manual without provider call, fail-closed identity, and the plugin packaging
that owns the reserved `manual` action and the mount). Pinned pytest commands
must run from the repo root with the project's Python.

## Behavior VN001 — analyze success is exactly {status ok, analysis} and manual performs no analyze operation or provider construction

- **id**: VN001
- **title**: analyze success is exactly {status ok, analysis} and manual performs no analyze operation or provider construction
- **guards**: `vision-contract` § Tool behavior
- **runner**: any LingTai agent with `shell` and `file` access to this repository
- **prerequisites**: a clean checkout of `<repo>`; a small test image `<scratch>/img.png`
- **estimate**: ≈ 20 minutes

### Steps
1. From `<repo>`, run `python -m pytest tests/test_vision_capability.py tests/test_tool_family_vision_migration.py -q` and capture the outcome.
2. Call `vision(action="manual", input={}, reasoning="probe")` and record the flat result; confirm no provider was constructed and no credential was read.
3. Call `vision(action="analyze", input={"image_path": "<scratch>/img.png", "question": null}, reasoning="probe")` through a configured route and confirm the success shape; then call it with a missing image and record the structured error.

### Expected evidence
- [ ] Step 1: the vision capability and migration suites pass, pinning one registered tool, strict envelopes, and wire parity without double wrap.
- [ ] Step 2: `manual` returns `{status: "ok", action: "manual", manual: body, manual_path: path}` (or the degraded shape) and performs no analyze operation, constructs no provider, and reads no credential.
- [ ] Step 3: analyze success is exactly `{status: "ok", analysis: text}`; missing image/empty response/setup/request failures are structured errors pointing to the full accepted envelope; exception messages are never returned.

### Pass / Fail
Pass when the suites pass and the exact-shape/no-provider observations hold. Fail on a nested or double-wrapped manual result, on analyze returning anything but the exact success shape, or on an exception message leaking into the result; record the evidence trail in the task report.

## Behavior VN002 — the vision plugin owns its manual and its mount, and the shipped registry agrees with its declaration

- **id**: VN002
- **title**: the vision plugin owns its manual and its mount, and the shipped registry agrees with its declaration
- **guards**: `vision-contract` § Packaging and mount
- **runner**: any LingTai agent with `shell` and `file` access to this repository
- **prerequisites**: a clean checkout of `<repo>`; a scratch agent working directory `<scratch>`
- **estimate**: ≈ 20 minutes

### Steps
1. From `<repo>`, run `python -m pytest tests/test_local_tool_plugin_package.py tests/test_intrinsic_manual_actions.py -q` and capture the outcome.
2. Read `src/lingtai/tools/vision/plugin.py` and `src/lingtai/tools/registry.py`; confirm `VISION_PLUGIN.capability_declaration()` names the same module and default kwargs the registry publishes for `vision`, and that `manual` appears in `VISION_DECLARED_ACTIONS` nowhere.
3. On a booted agent whose `<scratch>` library was installed, call `vision(action="manual", input={}, reasoning="probe the packaged skill")` and compare the returned `manual_path` with `<scratch>/.library/intrinsic/capabilities/vision/SKILL.md`; then delete that file and call it again.

### Expected evidence
- [ ] Step 1: the packaging and installed-manual suites pass, pinning the declaration/registry agreement, the reserved-`manual` refusals, and the mount refusals.
- [ ] Step 2: the declaration and the registry state the same module and default kwargs, and the declared action list is exactly `analyze`, `check`, `list` with `manual` appended by the plugin.
- [ ] Step 3: the first call returns the installed body at exactly that path; after deletion the call returns the `degraded` shape with an empty body, that same path, and the loader's error — never a silent empty success and never another capability's manual.

### Pass / Fail
Pass when the suites pass, the declaration and the registry agree, and the manual result tracks this capability's own installed skill in both the present and the missing case. Fail on a declaration that disagrees with `registry.py`, on `manual` being declarable or rebindable from the package, on a mount published under another name or without the reserved action, or on a degraded manual reported as `ok`; record the evidence trail in the task report.
