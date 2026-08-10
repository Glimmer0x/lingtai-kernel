---
name: kernel-behavior-tests
behavior_version: 1
labt_version: 1
contract: ../tools/notification/CONTRACT.md
anatomy: ANATOMY.md
related_files:
  - src/lingtai/kernel/nudge/__init__.py
  - src/lingtai/kernel/nudge/kernel_version.py
  - src/lingtai/kernel/nudge/source_drift.py
  - src/lingtai/kernel/nudge/prompts.py
  - src/lingtai/kernel/meta_block.py
  - src/lingtai/kernel/tool_executor.py
  - src/lingtai/kernel/tool_result_artifacts.py
  - src/lingtai/kernel/notifications.py
  - src/lingtai/tools/context/CONTRACT.md
  - src/lingtai/tools/notification/CONTRACT.md
  - src/lingtai/CONTRACT.md
  - tests/test_kernel_version_nudge.py
  - tests/test_eigen.py
  - tests/test_large_result_no_notification.py
  - tests/test_tool_meta_comment_overflow.py
maintenance: |
  Written by the kernel nudge/notification CONVERT_BEHAVIOR migration (2026-08).
  Keep in sync with the contracts this file guards — `src/lingtai/CONTRACT.md`
  (Contract rules 6–7, Nudge transport and inline cap), `src/lingtai/tools/notification/CONTRACT.md`
  (large-result routing, no large_tool_result source), `src/lingtai/tools/context/CONTRACT.md`
  (eigen retirement, molt input) — and with `src/lingtai/kernel/ANATOMY.md`
  entries for nudge, notifications, and meta_block. When any of those change
  agent-observable behavior, update the matching LABT here in the same change.
---
# Kernel Behavior Tests — nudge / notification family

LABT v1. These are self-contained agent-executable behavioral tests for the
kernel nudge/notification family: the kernel-version nudge (`kernel_version`,
including its source-drift/dev-runtime detection), the source-drift nudge
(`source_drift`), the retired `eigen` identity surface, the promise that a
large tool result never becomes a notification (it is ranked in
`_meta.agent_meta.current_tool_result_chars` instead), and the per-result
`_meta.tool_meta.comment.overflow` hint. Low-level mechanics stay in pytest;
each LABT below is self-contained — the full harness script is inlined — and
executable verbatim by an agent with `shell` and `file` tools at a checkout of
this repository. Replace `<repo-root>` with the checkout path and `<scratch>`
with any empty working directory the executor owns.

All harness scripts set the package path themselves (`sys.path.insert(0,
<repo-root>/src)`) and write into a fresh temp working dir, so they never touch
the executing agent's own `.notification/` or session state.

## Behavior K001 — kernel version nudge emits the local refresh finding on the `release_version` channel

- **id**: K001
- **title**: an installed distribution newer than the running kernel produces a
  `kernel_version` nudge entry (`nudge_channel: release_version`) with a
  safe-refresh suggested action, without any remote probe
- **guards**: `src/lingtai/CONTRACT.md` § Contract rules rule 6 — every declared
  Nudge kind uses the ordinary `.notification/nudge.json` transport and the
  shared global Nudge policy
  ([CONTRACT.md](../CONTRACT.md#contract-rules))
- **supersedes**: `tests/test_kernel_version_nudge.py::test_installed_runtime_refresh_nudge_does_not_hit_remote`
- **runner**: any LingTai agent with `shell` and `file` tools at a checkout of
  this repository (Python 3.10+)
- **prerequisites**: a checkout of this repo at `<repo-root>`; an empty scratch
  dir `<scratch>`; python on PATH
- **estimate**: 2 min

### Steps
1. Write `<scratch>/k001.py` with the following content (self-contained
   harness; `REPO` is the only value to substitute):

```python
import sys, os, json, pathlib, tempfile
REPO = r"<repo-root>"
sys.path.insert(0, os.path.join(REPO, "src"))
os.chdir(REPO)

from lingtai.adapters.posix.notification_store import PosixNotificationStoreAdapter
from lingtai.kernel.nudge import kernel_version as kv

class Agent:
    def __init__(self, workdir):
        self._working_dir = str(workdir)
        self._notification_store = PosixNotificationStoreAdapter(pathlib.Path(workdir))
        self.logs = []
        self._nudge_kernel_version_state = {"last_probe_ts": 0.0}
    def _log(self, event, **fields):
        self.logs.append((event, fields))

def entries(workdir):
    snap = PosixNotificationStoreAdapter(pathlib.Path(workdir)).snapshot(lambda ch: True)
    data = (snap.get("nudge") or {}).get("data") or {}
    return data.get("nudges") or []

d = pathlib.Path(tempfile.mkdtemp(prefix="k001"))
a = Agent(d)
# installed (0.14.2) is newer than running (0.14.1): local refresh, no remote.
kv._runtime_info = lambda: kv._RuntimeInfo(
    running_version="0.14.1", installed_version="0.14.2", dev_reason=None)
kv._fetch_latest_version = lambda: (_ for _ in ()).throw(
    AssertionError("remote must not be queried for a local refresh mismatch"))
kv._today_utc = lambda: "2026-06-30"
kv.check(a)
e = entries(d)
assert len(e) == 1, e
entry = e[0]
assert entry["kind"] == "kernel_version"
assert entry["nudge_channel"] == "release_version"
assert entry["source"] == "installed-distribution"
assert entry["running"] == "0.14.1" and entry["installed"] == "0.14.2"
assert entry["latest"] is None
assert entry["suggested_action"] == "refresh-installed-runtime-if-authorized-and-safe"
assert "already on disk" in entry["detail"]
assert "system(action='refresh')" in entry["detail"]
print("K001 ENTRY:", json.dumps({
    k: entry.get(k) for k in ("kind", "nudge_channel", "source",
                               "running", "installed", "suggested_action")}, ensure_ascii=False))
print("workdir:", d)
```

2. Run `python <scratch>/k001.py` from `<repo-root>`; the script exits 0 and
   prints the entry fields and the workdir path.
3. Read the notification file the script created: `<printed workdir>/.notification/nudge.json`
   and the state file `<printed workdir>/.notification/.nudge_state.json`.

### Expected evidence
- [ ] The script exits 0 (all assertions pass) and prints
      `K001 ENTRY:` with `kind: kernel_version`, `nudge_channel: release_version`,
      `source: installed-distribution`, `suggested_action:
      refresh-installed-runtime-if-authorized-and-safe`.
- [ ] `<workdir>/.notification/nudge.json` exists and its `data.nudges` contains
      exactly one entry whose `title` is `LingTai kernel refresh available:
      0.14.1 -> 0.14.2` and whose `detail` contains `already on disk` and
      `system(action='refresh')`.
- [ ] The remote probe was never invoked (the harness proves it by raising
      inside `_fetch_latest_version`).

### Pass / Fail
Pass when all evidence items hold and no network call occurred. Fail if the
entry is missing, has a different `nudge_channel`/`source`, or the remote fetch
was attempted.

## Behavior K002 — kernel version nudge is fail-safe: diagnostic direction, dev/source-drift runtimes, malformed versions

- **id**: K002
- **title**: running-newer/unparseable runtimes emit a read-only diagnostic
  (`installed-distribution-diagnostic`), dev/editable/source-checkout runtimes
  skip and clear the nudge with a recorded reason, and malformed remote
  versions can never be promoted
- **guards**: `src/lingtai/CONTRACT.md` § Contract rules rule 6 — Nudge
  findings stay on the ordinary `.notification/nudge.json` transport under the
  shared policy
  ([CONTRACT.md](../CONTRACT.md#contract-rules))
- **supersedes**: `tests/test_kernel_version_nudge.py::test_runtime_version_direction_is_fail_safe_and_equal_pairs_probe_remote`,
  `tests/test_kernel_version_nudge.py::test_dev_or_editable_runtime_skips_and_clears_kernel_nudge`,
  `tests/test_kernel_version_nudge.py::test_runtime_info_detects_source_checkout_from_wrapper_file`,
  `tests/test_kernel_version_nudge.py::test_malformed_remote_version_cannot_be_promoted_by_numeric_substrings`
- **runner**: any LingTai agent with `shell` and `file` tools at a checkout of
  this repository
- **prerequisites**: a checkout of this repo at `<repo-root>`; an empty scratch
  dir `<scratch>`; python on PATH
- **estimate**: 3 min

### Steps
1. Write `<scratch>/k002.py` with the following content:

```python
import sys, os, json, pathlib, tempfile
REPO = r"<repo-root>"
sys.path.insert(0, os.path.join(REPO, "src"))
os.chdir(REPO)

from lingtai.adapters.posix.notification_store import PosixNotificationStoreAdapter
from lingtai.kernel.nudge import kernel_version as kv

class Agent:
    def __init__(self, workdir):
        self._working_dir = str(workdir)
        self._notification_store = PosixNotificationStoreAdapter(pathlib.Path(workdir))
        self.logs = []
        self._nudge_kernel_version_state = {"last_probe_ts": 0.0}
    def _log(self, event, **fields):
        self.logs.append((event, fields))

def entries(workdir):
    snap = PosixNotificationStoreAdapter(pathlib.Path(workdir)).snapshot(lambda ch: True)
    data = (snap.get("nudge") or {}).get("data") or {}
    return data.get("nudges") or []

def run_case(prefix, running, installed, dev_reason):
    d = pathlib.Path(tempfile.mkdtemp(prefix=prefix))
    a = Agent(d)
    kv._runtime_info = lambda: kv._RuntimeInfo(
        running_version=running, installed_version=installed, dev_reason=dev_reason)
    kv._fetch_latest_version = lambda: (_ for _ in ()).throw(
        AssertionError("no remote probe expected"))
    kv._today_utc = lambda: "2026-06-24"
    kv.check(a)
    return d, entries(d)

# (a) running newer than installed -> read-only diagnostic, never refresh
_, ea = run_case("k002a", "0.17.0", "0.16.5", None)
assert len(ea) == 1
assert ea[0]["source"] == "installed-distribution-diagnostic"
assert ea[0]["suggested_action"] == "inspect-runtime-interpreter-and-import-paths"
assert "Do not refresh" in ea[0]["detail"]

# (b) unparseable running version -> same diagnostic
_, eb = run_case("k002b", "not-a-version", "0.17.0", None)
assert len(eb) == 1 and eb[0]["source"] == "installed-distribution-diagnostic"

# (c) dev/editable runtime -> nudge skipped AND cleared, reason recorded
d, ec = run_case("k002c", "0.14.1.dev0", "0.14.1.dev0", "editable-install")
assert ec == []
state = json.loads((d / ".notification" / ".nudge_state.json").read_text())
assert state["kernel_version"]["last_skip_date"] == "2026-06-24"
assert state["kernel_version"]["skip_reason"] == "editable-install"

# (d) source checkout (source drift) -> skipped, reason recorded
_, ed = run_case("k002d", "0.14.1", "0.14.1", "source-checkout")
assert ed == []

# (e) malformed remote candidates are never promoted by numeric substrings
assert kv._is_newer("999-not-a-release", "0.16.5") is False
assert kv._is_newer("release-999", "0.16.5") is False
assert kv._is_newer("not-a-version", "0.16.5") is False

print("K002 OK: diagnostic(a,b), dev-skip(c), source-checkout-skip(d), no-promote(e)")
```

2. Run `python <scratch>/k002.py` from `<repo-root>`; it must exit 0.

### Expected evidence
- [ ] The script exits 0 and prints `K002 OK: ...`.
- [ ] Case (a)/(b) entries carry `source: installed-distribution-diagnostic`,
      `suggested_action: inspect-runtime-interpreter-and-import-paths`, and
      `Do not refresh` in `detail` — an ambiguous direction never recommends
      refresh.
- [ ] Case (c) leaves `data.nudges` empty and `kernel_version.skip_reason` is
      `editable-install` (source drift/dev detection recorded). Case (d) leaves
      it empty for `source-checkout`.
- [ ] `kv._is_newer` returns `False` for every malformed candidate.

### Pass / Fail
Pass when all evidence holds. Fail if a diagnostic case recommends refresh, a
dev runtime still emits a nudge, or a malformed remote version is treated as
newer.

## Behavior K003 — `eigen` is retired: LingTai identity lives in `context` + `psyche`, name changes are `system.name_set`

- **id**: K003
- **title**: the `eigen` intrinsic no longer exists; the identity/soul surface
  is `context` (molt owns the identity summary in `input`) plus the
  manual-only `psyche` family, and the true name is set once via
  `system.name_set` / `system.name_nickname`
- **guards**: `context-tool` § Purpose and public ownership — no OLD `psyche`
  action is reachable, `eigen` is gone, name changes remain
  `system.name_set | system.name_nickname`, and `molt` requires `summary` in
  its own strict input branch
  ([CONTRACT.md](../tools/context/CONTRACT.md#purpose-and-public-ownership))
- **supersedes**: `tests/test_eigen.py::test_eigen_is_gone_and_psyche_is_the_durable_domain_root`,
  `tests/test_eigen.py::test_eigen_schema_has_molt`,
  `tests/test_eigen.py::test_eigen_name_sets_agent_name`
- **runner**: any LingTai agent with `shell` tool at a checkout of this
  repository
- **prerequisites**: a checkout of this repo at `<repo-root>`; python on PATH
- **estimate**: 1 min

### Steps
1. Run the following from `<repo-root>` (single command, quoted):

```
python -c "import sys,os,json; sys.path.insert(0, os.path.join(r'<repo-root>','src')); from lingtai.tools.registry import INTRINSICS; from lingtai.tools.context import get_schema; from lingtai.tools.system import get_schema as sys_schema; i=sorted(INTRINSICS); print('intrinsics:', [k for k in i if k in ('context','psyche','eigen','pad','lingtai')]); s=get_schema('en'); print('context actions:', s['properties']['action']['enum']); print('summary-not-root:', 'summary' not in s['properties']); print('summarize-type:', s['properties']['summarize']['type']); print('required:', sorted(s['required'])); ss=sys_schema('en'); print('system name actions:', [a for a in ss['properties']['action']['enum'] if a in ('name_set','name_nickname')])"
```

2. Read the printed values against the checklist below.

### Expected evidence
- [ ] `intrinsics:` prints exactly `['context', 'psyche']` — `eigen`, `pad`,
      and `lingtai` are NOT registered intrinsics.
- [ ] `context actions:` is `['molt', 'summarize', 'rebuild', 'manual']` — no
      `context_molt`/`pad_edit`/`lingtai_update`/`name_set` old spellings.
- [ ] `summary-not-root:` is `True` (the molt summary lives in the `molt`
      action's `input` branch, not on the root), `summarize-type:` is
      `boolean` (the unrelated root post-processing control), and `required:`
      is `['action', 'input', 'reasoning']`.
- [ ] `system name actions:` prints `['name_set', 'name_nickname']` — identity
      naming is owned by the `system` tool.

### Pass / Fail
Pass when every printed value matches. Fail if `eigen` (or `pad`/`lingtai`)
appears as an intrinsic, or `name_set` is absent from the `system` schema.

## Behavior K004 — `context.molt` refuses an empty or missing summary before any context mutation

- **id**: K004
- **title**: `context(action="molt", input={...})` without a non-empty
  `summary` returns the pinned refusal error and sheds nothing
- **guards**: `context-tool` § Molt safety invariants — agent-initiated molt
  requires a nonempty retrospective; validation occurs before snapshot/
  archive/wipe or count mutation
  ([CONTRACT.md](../tools/context/CONTRACT.md#molt-safety-invariants))
- **supersedes**: `tests/test_eigen.py::test_context_molt_rejects_empty_summary`,
  `tests/test_eigen.py::test_context_molt_rejects_missing_summary`
- **runner**: any LingTai agent with `shell` tool at a checkout of this
  repository
- **prerequisites**: a checkout of this repo at `<repo-root>`; python on PATH
- **estimate**: 1 min

### Steps
1. Run the following from `<repo-root>` (single command, quoted):

```
python -c "import sys,os,json,types; sys.path.insert(0, os.path.join(r'<repo-root>','src')); from lingtai.tools.context import handle; stub=types.SimpleNamespace(); empty=handle(stub, {'action':'molt','input':{'summary':''},'reasoning':'t'}); missing=handle(stub, {'action':'molt','input':{},'reasoning':'t'}); print('empty:', json.dumps(empty, ensure_ascii=False)); print('missing:', json.dumps(missing, ensure_ascii=False))"
```

2. Read the printed errors.

### Expected evidence
- [ ] `empty:` prints `{"error": "summary cannot be empty — write what you need to remember."}`.
- [ ] `missing:` prints `{"error": "summary is required — write a briefing to your future self."}`.
- [ ] The refusal happens before any session wipe/snapshot/molt-count mutation
      (the stub has no session at all, yet the error returns cleanly).

### Pass / Fail
Pass when both pinned error strings are returned verbatim. Fail if an empty
summary is accepted or a non-error result is returned.

## Behavior K005 — a large tool result never becomes a notification; `_meta.agent_meta.current_tool_result_chars` ranks it instead

- **id**: K005
- **title**: large tool results produce no `large_tool_result` system
  notification (neither per-result nor at the turn boundary); the same result
  is reported through `_meta.agent_meta.current_tool_result_chars` with
  `total_chars`, `threshold`, `over_threshold_count`, and `top_results`
- **guards**: `notification-tool` § Behavior — agents MUST NOT route
  large-result compaction through the notification tool, and the kernel no
  longer publishes a `large_tool_result` source
  ([CONTRACT.md](../tools/notification/CONTRACT.md#behavior))
- **supersedes**: `tests/test_large_result_no_notification.py::test_rescan_never_publishes_for_huge_result`,
  `tests/test_large_result_no_notification.py::test_large_result_still_reported_by_current_tool_result_chars`,
  `tests/test_large_result_no_notification.py::test_current_tool_result_chars_reports_threshold_and_over_count`
- **runner**: any LingTai agent with `shell` tool at a checkout of this
  repository
- **prerequisites**: a checkout of this repo at `<repo-root>`; python on PATH
- **estimate**: 2 min

### Steps
1. Write `<scratch>/k005.py` with the following content:

```python
import sys, os, json, types
from unittest.mock import MagicMock
REPO = r"<repo-root>"
sys.path.insert(0, os.path.join(REPO, "src"))
os.chdir(REPO)

from lingtai.kernel.llm.interface import ChatInterface, ToolCallBlock, ToolResultBlock
from lingtai.kernel import meta_block
from lingtai.kernel.base_agent.messaging import _rescan_large_tool_results

iface = ChatInterface()
iface.add_assistant_message([ToolCallBlock(id="tc-rank", name="bash", args={})])
iface.add_tool_results([ToolResultBlock(
    id="tc-rank", name="bash", content={"output": "Q" * 40000, "status": "ok"})])

agent = types.SimpleNamespace()
agent._session = types.SimpleNamespace(chat=types.SimpleNamespace(interface=iface))

# Default threshold (no attribute configured) is 3000 chars.
s = meta_block.current_tool_result_chars(agent)
print("summary:", json.dumps({k: s[k] for k in ("total_chars", "threshold",
                                                "over_threshold_count")}))
assert s["total_chars"] >= 40000
assert s["threshold"] == 3000
assert "tc-rank" in [r["id"] for r in s["top_results"]]
assert s["top_results"][0]["tool_name"] == "bash"

# Configured threshold: only results over it are counted.
agent._summarize_notification_threshold = 5000
s2 = meta_block.current_tool_result_chars(agent)
assert s2["threshold"] == 5000 and s2["over_threshold_count"] == 1

# Turn-boundary rescan: never publishes, always returns 0.
class StubChat:
    interface = iface
stub = MagicMock()
stub._chat = StubChat()
stub._log = MagicMock()
stub._summarize_notification_threshold = 5000
published = []
stub._enqueue_system_notification = lambda *, source, ref_id, body, \
    skip_if_ref_id_exists=False, **kw: published.append(source) or "evt001"
count = _rescan_large_tool_results(stub)
print("rescan_count:", count, "published:", published)
assert count == 0 and published == []
print("K005 OK")
```

2. Run `python <scratch>/k005.py` from `<repo-root>`; it must exit 0.

### Expected evidence
- [ ] The script exits 0 and prints `summary:` with `total_chars >= 40000`,
      `threshold: 3000` (default), and `over_threshold_count: 1` (the single
      40000-char result already exceeds the default 3000-char threshold).
- [ ] With `_summarize_notification_threshold = 5000`, the same ranking
      reports `threshold: 5000` and `over_threshold_count: 1`, and
      `top_results` lists `id: tc-rank` with `tool_name: bash`.
- [ ] `rescan_count: 0` and `published: []` — the turn-boundary rescan never
      emits a `large_tool_result` (or any) notification.

### Pass / Fail
Pass when all evidence holds. Fail if any `large_tool_result` notification is
published, the rescan returns a nonzero count, or the ranked summary lacks
`total_chars`/`threshold`/`over_threshold_count`/`top_results`.

## Behavior K006 — capped/large results carry `_meta.tool_meta.comment.overflow`

- **id**: K006
- **title**: spilled and large-but-inline tool results carry exactly one
  machine-generated guidance topic `_meta.tool_meta.comment.overflow` pointing
  at `logs/events.jsonl` by `tool_call_id` (never a sidecar `saved_path`),
  while ordinary small results carry no comment and the `tool_meta` identity
  fields (`id`, `char_count`, `elapsed_ms`) stay intact
- **guards**: `notification-tool` § Behavior — large-result compaction is
  guidance, not notification; the digest action is `system(action="summarize")`
  ([CONTRACT.md](../tools/notification/CONTRACT.md#behavior))
- **supersedes**: `tests/test_tool_meta_comment_overflow.py::test_spilled_result_carries_overflow_comment`,
  `tests/test_tool_meta_comment_overflow.py::test_large_inline_result_carries_overflow_comment`,
  `tests/test_tool_meta_comment_overflow.py::test_small_result_has_no_overflow_comment`
- **runner**: any LingTai agent with `shell` tool at a checkout of this
  repository
- **prerequisites**: a checkout of this repo at `<repo-root>`; python on PATH
- **estimate**: 2 min

### Steps
1. Write `<scratch>/k006.py` with the following content:

```python
import sys, os, json, pathlib, tempfile
from unittest.mock import MagicMock
REPO = r"<repo-root>"
sys.path.insert(0, os.path.join(REPO, "src"))
os.chdir(REPO)

from lingtai.kernel.llm.base import ToolCall
from lingtai.kernel.llm.interface import ToolResultBlock
from lingtai.kernel.loop_guard import LoopGuard
from lingtai.kernel.meta_block import build_tool_meta_overflow_comment
from lingtai.kernel.tool_executor import ToolExecutor, _DEFAULT_MAX_RESULT_CHARS

# The spill hard ceiling (PREVENTIVE_MAX_CHARS, src/lingtai/kernel/tool_result_artifacts.py).
assert _DEFAULT_MAX_RESULT_CHARS == 200_000

# Builder shape: one topic, four subkeys, references the durable log by call id.
c = build_tool_meta_overflow_comment("tc-abc")
blob = json.dumps(c)
assert set(c) == {"summary", "full_original", "how_to_retrieve", "after_consuming"}
assert "logs/events.jsonl" in blob and "tool_call_id=tc-abc" in blob
assert "saved_path" not in blob
assert "grep" in c["how_to_retrieve"] and "lingtai-agent log query" in c["how_to_retrieve"]
assert ("daemon" in c["how_to_retrieve"] or "subagent" in c["how_to_retrieve"])
assert "summarize" in c["after_consuming"]

# Spilled result (payload over the configured 500-char cap) -> status spilled
# + overflow comment + spilled_char_count.
def make_executor(dispatch_fn, workdir, max_result_chars, threshold):
    captured = MagicMock(side_effect=lambda name, result, **kw: ToolResultBlock(
        kw.get("tool_call_id", ""), name, result))
    ex = ToolExecutor(dispatch_fn=dispatch_fn, make_tool_result_fn=captured,
                      guard=LoopGuard(max_total_calls=50), working_dir=workdir,
                      max_result_chars=max_result_chars,
                      summarize_notification_threshold=threshold)
    return ex

ex = make_executor(lambda tc: {"data": "Z" * 1200}, str(tempfile.mkdtemp()),
                   500, None)
block = ex.execute([ToolCall(name="read", args={}, id="tc-spill")])[0][0]
assert block.content["status"] == "spilled"
tm = block.metadata.get("tool_meta", {})
assert set(tm["comment"].keys()) == {"overflow"}
assert tm["id"] == "tc-spill"
assert isinstance(tm["char_count"], int) and isinstance(tm["elapsed_ms"], int)
assert "spilled_char_count" in tm

# Large but inline (over the 100-char hint threshold, under the spill cap)
# -> overflow comment, not spilled.
ex2 = make_executor(lambda tc: {"data": "Q" * 400}, str(tempfile.mkdtemp()),
                   _DEFAULT_MAX_RESULT_CHARS, 100)
block2 = ex2.execute([ToolCall(name="read", args={}, id="tc-large")])[0][0]
assert block2.content.get("status") != "spilled"
tm2 = block2.metadata.get("tool_meta", {})
assert tm2["char_count"] > 100
assert "overflow" in tm2.get("comment", {})
assert "logs/events.jsonl" in tm2["comment"]["overflow"]["full_original"]

# Small result -> no comment at all; identity fields still present.
ex3 = make_executor(lambda tc: {"ok": True}, str(tempfile.mkdtemp()),
                   _DEFAULT_MAX_RESULT_CHARS, 100)
block3 = ex3.execute([ToolCall(name="read", args={}, id="tc-small")])[0][0]
tm3 = block3.metadata.get("tool_meta", {})
assert "comment" not in tm3
assert tm3["id"] == "tc-small"
assert isinstance(tm3["char_count"], int) and isinstance(tm3["elapsed_ms"], int)

print("K006 OK: builder-shape, spilled, large-inline, small-no-comment")
```

2. Run `python <scratch>/k006.py` from `<repo-root>`; it must exit 0.

### Expected evidence
- [ ] The script exits 0 and prints `K006 OK: ...`.
- [ ] `_DEFAULT_MAX_RESULT_CHARS` is `200000` (the preventive spill ceiling).
- [ ] The builder returns exactly `{summary, full_original, how_to_retrieve,
      after_consuming}`; `full_original` names `logs/events.jsonl` and
      `tool_call_id=<id>`; no `saved_path`; `how_to_retrieve` offers `grep`
      and `lingtai-agent log query`; `after_consuming` recommends
      `system(action="summarize")`.
- [ ] A spilled result reports `status: spilled` with
      `tool_meta.comment.overflow` and `spilled_char_count`; a large inline
      result (over the hint threshold) also carries the comment; a small
      result carries no `comment`. Identity fields `id`/`char_count`/
      `elapsed_ms` remain intact in all three.

### Pass / Fail
Pass when all evidence holds. Fail if the comment is split into multiple
headings, references a `saved_path`, appears on a small result, or drops the
identity fields.

## Behavior K007 — source-drift nudge: startup vs on-disk fingerprint mismatch emits the `source_integrity` finding

- **id**: K007
- **title**: when the current on-disk source fingerprint (git rev / source
  digest) differs from the startup fingerprint, the `source_drift` nudge entry
  is emitted on the `source_integrity` channel; when they match again the
  entry is cleared
- **guards**: `src/lingtai/CONTRACT.md` § Contract rules rule 6 — every
  declared Nudge kind uses the ordinary `.notification/nudge.json` transport
  and the shared global policy
  ([CONTRACT.md](../CONTRACT.md#contract-rules))
- **supersedes**: `tests/test_source_drift.py` (emit/clear scenarios)
- **runner**: any LingTai agent with `shell` and `file` tools at a checkout of
  this repository
- **prerequisites**: a checkout of this repo at `<repo-root>`; an empty scratch
  dir `<scratch>`; python on PATH
- **estimate**: 2 min

### Steps
1. Write `<scratch>/k007.py` with the following content:

```python
import sys, os, json, pathlib, tempfile
REPO = r"<repo-root>"
sys.path.insert(0, os.path.join(REPO, "src"))
os.chdir(REPO)

from lingtai.adapters.posix.notification_store import PosixNotificationStoreAdapter
from lingtai.kernel.nudge import source_drift as sd
from lingtai.kernel.base_agent import lifecycle as lc

class Agent:
    def __init__(self, workdir):
        self._working_dir = str(workdir)
        self._notification_store = PosixNotificationStoreAdapter(pathlib.Path(workdir))
        self.logs = []
        self._nudge_source_drift_state = {"last_probe_ts": 0.0}
        self._source_revision_port = None
    def _log(self, event, **fields):
        self.logs.append((event, fields))

def entries(workdir):
    snap = PosixNotificationStoreAdapter(pathlib.Path(workdir)).snapshot(lambda ch: True)
    data = (snap.get("nudge") or {}).get("data") or {}
    return data.get("nudges") or []

d = pathlib.Path(tempfile.mkdtemp(prefix="k007"))
a = Agent(d)
startup = {"git_rev": "abc1234", "source_digest": "digestAAAA",
           "captured_at": "2026-07-01T00:00:00Z"}
a._runtime_fingerprint = startup
# On-disk source changed since startup -> drift.
lc._capture_runtime_fingerprint = lambda port: {
    "git_rev": "def5678", "source_digest": "digestBBBB",
    "captured_at": "2026-07-02T00:00:00Z"}
sd.check(a)
e = entries(d)
assert len(e) == 1, e
entry = e[0]
assert entry["kind"] == "source_drift"
assert entry["nudge_channel"] == "source_integrity"
assert entry["title"] == "Source drift detected \u2014 running code is stale"
assert entry["suggested_action"] == "system(action='refresh')"
assert "git_rev: abc1234 \u2192 def5678" in entry["detail"]
assert "source_digest: digestAAAA \u2192 digestBBBB" in entry["detail"]

# On-disk source matches startup again -> the finding is cleared.
lc._capture_runtime_fingerprint = lambda port: startup
a._nudge_source_drift_state = {"last_probe_ts": 0.0, "emitted": True}
sd.check(a)
assert entries(d) == [], entries(d)
print("K007 OK: source_integrity emit + clear")
```

2. Run `python <scratch>/k007.py` from `<repo-root>`; it must exit 0.

### Expected evidence
- [ ] The script exits 0 and prints `K007 OK: source_integrity emit + clear`.
- [ ] The drift entry has `kind: source_drift`, `nudge_channel:
      source_integrity`, `title: Source drift detected — running code is
      stale`, `suggested_action: system(action='refresh')`, and a `detail`
      listing `git_rev: abc1234 → def5678` and `source_digest: digestAAAA →
      digestBBBB`.
- [ ] After the fingerprints match again, `data.nudges` is empty (the stale
      finding is cleared, not left visible).

### Pass / Fail
Pass when all evidence holds. Fail if no entry is emitted on drift, the
channel/title/action differ, or a matching fingerprint does not clear the
finding.
