# PR #1236 Audit — feat(telegram): blanket 1s taskcard rebuild with fingerprint edit dedupe

- **Branch:** `feat/taskcard-blanket-rebuild` (1 commit, `4cdce1fc`) vs `main`
- **Auditor:** Claude (Fable 5), 2026-08-08
- **Files:** `src/lingtai/mcp_servers/telegram/manager.py` (+53/−11), `tests/test_telegram_task_card_event_tail.py` (+48), `tests/test_telegram_task_card_toggle.py` (±4)

## Verdict: **changes-needed (minor)**

The design is sound: one render + sha256 per tick, per-target dedupe, `force=True` on
truncation/replacement, and Telegram's `"message is not modified"` already classified as
`EDIT_OK` (`manager.py:1966-1967`) so a forced identical edit can never cascade into the
delete/replace path. The blanket loop is also a genuine behavioral improvement — settings
changes (`taskcard_normal_rows`), agent lifecycle transitions (stuck/offline), and model
changes now reach the card within 1s instead of waiting for the next event append.

Two small correctness fixes should land before merge (findings M1, M2). Both are one- or
two-line changes. Everything else is comment accuracy, test hardening, or design polish.

**Test status:** the two touched test files pass (75/75). The wider task-card sweep
(351 passed) has exactly one failure, `test_telegram_task_card_transport.py::
test_public_telegram_action_reaches_manager`, which fails identically on `main`
(`_FakeService` lacks `list_accounts`) — pre-existing, not caused by this PR. Feishu test
collection errors are a missing `lark_channel` module in the local venv, also unrelated.

---

## Findings

### M1 (Medium, correctness): suppressed delivery caches a fingerprint that was never delivered

`manager.py:2818` treats any `status == "ok"` as "frame is now on screen":

```python
if result.get("status") == "ok":
    self._task_card_automatic_fingerprints[key] = fingerprint
```

But `TaskCardResident.project` returns `{"status": "ok", "suppressed": True, "taskcard": False}`
when the toggle is disabled (`resident.py:202`) — and delivers nothing. The broadcast's own
enabled check at `manager.py:2795` runs *before* the per-route lock, so a `/taskcard off`
landing between that check and `project()` hits this path.

**Failure sequence:** frame A delivered, fp(A) cached → events advance to frame B → toggle
flips off mid-broadcast → `project()` suppresses, but fp(B) is cached anyway → `/taskcard on`
fires the reprojection in `_on_taskcard_changed` (`manager.py:647`) → fp matches B, resident
exists → **skipped**. The card shows A until the window content changes again — the exact
stale-state class the blanket rebuild was built to eliminate, made sticky by the dedupe.

**Fix (one line):**

```python
if result.get("status") == "ok" and not result.get("suppressed"):
```

### M2 (Medium-low, concurrency): fingerprint check/store is not atomic with delivery

`_broadcast_task_card_event_window` runs on at least three threads: the 1s tail loop
(`manager.py:2849`), the taskcard-changed listener (`manager.py:647`), and the rehydrate
path inside `_poll_event_tail` (`manager.py:2536`). Delivery itself is serialized by the
per-route `RLock` inside `TaskCardResident.project`, but the fingerprint read
(`manager.py:2806`) and write (`manager.py:2819`) happen outside it.

**Interleaving that sticks:** T2 delivers newer frame B (lock held), releases, pauses before
storing; T1 delivers older frame A, stores fp(A); T2 stores fp(B). Screen shows A (delivered
last), cache says B. Next tick renders B → fp matches → skip → the stale frame A survives
until the next content change. Pre-PR the same delivery inversion could occur, but the next
broadcast unconditionally re-edited; the dedupe now pins the stale frame, so the race got
strictly worse.

**Fix (two lines):** wrap the check + deliver + store per target in the route lock — it is
an `RLock`, so the nested acquisition inside `project()` is free:

```python
with self._task_card_delivery_lock(account, chat_id):
    if not force and ...:  # existing check/skip
        ...
    result = self._deliver_channel_frame(...)
    if result.get("status") == "ok" and not result.get("suppressed"):
        self._task_card_automatic_fingerprints[key] = fingerprint
```

### L1 (Low, comment accuracy): "deleted externally" overclaims what the resident check detects

The skip-guard comment at `manager.py:2807-2809` says "if it was deleted externally, the
next tick must re-send". `_get_resident_task_card` (`manager.py:3076`) reads the tracked
in-memory id and the durable `state.json` id — it never probes whether the Telegram message
still exists, and the Bot API emits no deletion events. A user deleting the card in-chat
leaves the tracked id set, so the skip continues; the card heals only on the next content
change (edit fails → `replace_after_probe`). That matches pre-PR behavior and is fine, but
the guard actually catches *tracked-map clears* (e.g. a peer process rotating the resident
in `state.json`, per the docstring at `manager.py:3079-3094`), not in-chat deletions.
Reword the comment so nobody later relies on 1s self-healing of a deleted message.

### L2 (Low, design): the fingerprint cache duplicates state the resident owner already holds, and other automatic-channel writers bypass it

`_task_card_create` (`manager.py:2980`), `_task_card_update` (`:3221`),
`_task_card_finalize` (`:3263`), and `_ensure_task_card_resident` (`:2945`) all deliver
automatic frames through `_deliver_channel_frame` without touching
`_task_card_automatic_fingerprints`. Today the desync is benign — their frame simply
survives on screen until the window content changes, same as pre-PR — but the invariant
"cache == what's displayed" is silently false after any of these paths, which is exactly the
kind of thing the next contributor trips over.

`TaskCardResident` already commits the delivered automatic frame via `set_frame` on every
successful delivery (`resident.py:276-283, 293-300, 311-317`). Fingerprinting
`self._resident.frames.get(key, {}).get("automatic")` (or having the resident expose the
committed slot) instead of maintaining a second dict would make the dedupe read the single
source of truth, eliminate this desync class outright, and subsume M2's store-side race.
Worth doing now while the cache is one release old; acceptable to defer with a comment.

Related behavior change worth documenting in the PR description: after a manager restart the
fingerprint cache is empty, so the *first* blanket tick re-edits every resident with the
rehydrated window. A finalize "✅ TASK CARD · DONE" frame that previously survived until the
next event append now gets stomped within 1s of restart.

### L3 (Low, tests): the advertised "resident loss re-sends on same frame" path has no test

The banner comment above the new tests (`test_telegram_task_card_event_tail.py:1086-1089`)
promises three behaviors; only two are tested. The third — fingerprint matches but
`_get_resident_task_card` returns `None` → deliver anyway (`manager.py:2810-2812`) — is
untested. Add:

```python
def test_blanket_resends_when_resident_lost_on_same_frame(tmp_path):
    ...  # same setup as test_blanket_rebuild_skips_unchanged_frame
    acct.clear_task_card(555)
    manager._broadcast_task_card_event_window()
    assert [c[0] for c in acct.calls] == ["send_message"]
```

### L4 (Low, tests): the `Last Updated` exclusion — the load-bearing part of the fingerprint — is not pinned

`format_current_time` renders second precision (`event_projection.py:49`), and the two
renders in `test_blanket_rebuild_skips_unchanged_frame` execute microseconds apart, so the
frames are almost always byte-identical: the test passes even if the `TIME_PREFIX` filter in
`_task_card_automatic_fingerprint` (`manager.py:2776-2780`) is deleted. Yet that filter is
what prevents the blanket loop from firing a real Telegram edit every single second (each
tick's render differs by the timestamp). Pin it directly:

```python
def test_fingerprint_ignores_last_updated_line_only(manager):
    a = "⚙ WORKING\n• row\n\nfooter\nLast Updated: 10:00:00 UTC+08"
    b = "⚙ WORKING\n• row\n\nfooter\nLast Updated: 10:00:01 UTC+08"
    c = "⚙ WORKING\n• other\n\nfooter\nLast Updated: 10:00:00 UTC+08"
    assert manager._task_card_automatic_fingerprint(a) == \
        manager._task_card_automatic_fingerprint(b)
    assert manager._task_card_automatic_fingerprint(a) != \
        manager._task_card_automatic_fingerprint(c)
```

### L5 (Low, resources): steady-state tick cost is acceptable but not free

Every 1s tick in the skip path performs: event-groups deep copy (`manager.py:2171-2178`),
metadata snapshot — `socket.gethostname()`, an `init.json` read+parse when `LINGTAI_SHELL`
is unset (`manager.py:2210`), an `.agent.json` read+parse (`manager.py:2230`) — full window
render including `redact_text` regex passes over every row, sha256, plus **per target** a
durable `state.json` read+parse inside `_get_resident_task_card` (`manager.py:3106`). Call
it 3–4 file reads + JSON parses per second per manager. For a single-agent daemon this is
fine; flagging so it's a conscious decision. If it ever matters: mtime-cache the
`.agent.json`/`init.json` reads, and consult the durable resident only on fingerprint miss
(the skip path only needs "tracked id exists", which the in-memory map answers).

### Nits

- `import hashlib` is inserted after `import json` (`manager.py:15-16`), breaking the
  otherwise-sorted stdlib block.
- `_task_card_automatic_fingerprints` entries are never pruned when a chat/account drops its
  card. Growth is bounded by the number of routes ever seen — negligible, but a
  `pop(key, None)` where residents are cleared would keep it honest.

---

## Audit-question summary

1. **Correct skips only?** Yes, with the M1/M2 caveats. Settings changes, resident-map
   loss, lifecycle/model changes all alter the render → fingerprint differs → edit fires.
   No render line can collide with the `Last Updated: ` prefix: every event row is prefixed
   (`• `/`✓ `/`⚠️ `/divider — `event_projection.py:530-539`) and metadata lines are group-
   joined, so exactly one line (the render's own time line) is excluded. Row `elapsed_s`/
   `started_at` come from stored events, not wall clock, so renders are stable between file
   changes — the fingerprint doesn't oscillate.
2. **Concurrency:** delivery is route-locked, but the fingerprint check/store is not — see
   M2 (real, sticky, cheap to fix). Plain dict ops are GIL-safe; no deadlock risk — the new
   `force=True` call at `manager.py:2568` runs outside `_task_card_event_lock` (all lock
   scopes in `_poll_event_tail` are short reads), verified.
3. **Last Updated exclusion vs freshness:** semantics are unchanged from pre-PR — the
   displayed timestamp reflects the last *content* change, since pre-PR also only edited on
   change. The exclusion is what keeps the blanket loop from editing every second (second-
   precision timestamps would otherwise change every tick). Correct trade-off; L4 asks for
   a test pinning it.
4. **Resource use:** acceptable; see L5 for the per-tick I/O inventory and cheap mitigations.
5. **Test quality:** the two new tests genuinely exercise the skip path and the force
   bypass, and the toggle-test update correctly reflects the new contract (re-enable
   reprojection is still asserted at `test_telegram_task_card_toggle.py:390` before the
   dedupe assertion). Gaps: L3 (resident-loss re-send untested) and L4 (exclusion untested).
6. **Edge cases:** disabled toggle → early return before render (cheap); disable does not
   delete the resident, and the re-enable reprojection dedupes correctly once M1 is fixed.
   Empty window renders header+footer+metadata+time (never empty text, so no
   empty-edit hazard). Multi-account is correct: one shared render, per-(account, chat_id)
   fingerprint keys, per-target delivery-failure isolation preserved. Truncation/replacement
   correctly forces; `force` deliveries still update the cache so the next tick dedupes.

## Required before merge

1. **M1** — guard the fingerprint store with `not result.get("suppressed")` (`manager.py:2818`).
2. **M2** — take the route delivery lock around check + deliver + store (`manager.py:2804-2819`).

Recommended in the same PR: L3 and L4 tests (both are ~10 lines), L1 comment reword.
