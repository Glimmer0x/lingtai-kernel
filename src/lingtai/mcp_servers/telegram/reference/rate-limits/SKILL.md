---
name: telegram-rate-limits
description: |
  Current official Telegram Bot API flood-control guidance: published quotas,
  `retry_after` semantics, documented unknowns, and safe client policy. Read
  before changing Telegram send cadence, programmable Task Card cadence, or 429
  recovery behavior.
version: 1.0.0
last_changed_at: 2026-07-29T00:00:00Z
related_files:
  - src/lingtai/mcp_servers/telegram/SKILL.md
  - src/lingtai/mcp_servers/telegram/account.py
  - src/lingtai/mcp_servers/telegram/manager.py
  - tests/test_telegram_rate_limit.py
maintenance: |
  Re-check the two official Telegram sources before changing any quoted quota or
  retry semantics. Keep provider facts distinct from LingTai product policy and
  keep the parent manual as the concise progressive-disclosure entry point.
---

# Telegram Bot API rate limits

This reference records Telegram's current published guidance. It is not a
second tool contract and it does not make undocumented provider behavior into a
LingTai guarantee. Re-check the official links before changing cadence or
recovery policy.

## Official sources

- [`ResponseParameters`](https://core.telegram.org/bots/api#responseparameters)
- [`Bots FAQ — Broadcasting to Users`](https://core.telegram.org/bots/faq#broadcasting-to-users)

Last verified against both pages: **2026-07-29 UTC**.

## Currently documented quotas

Telegram's FAQ says:

- In one chat, avoid sending more than **one message per second**. Short bursts
  may pass, but continued excess eventually produces HTTP 429 errors.
- In a group, bots cannot send more than **20 messages per minute**.
- For bulk notifications, bots cannot broadcast more than **about 30 messages
  per second** unless paid broadcasts are enabled.
- Paid broadcasts can raise the published bulk ceiling to 1000 messages per
  second for eligible bots at the documented Stars cost. This is opt-in billing,
  never an automatic LingTai fallback.
- Without paid broadcasts, Telegram recommends spreading large notification
  batches over longer intervals such as 8–12 hours.

These are provider guidelines, not permission to run every source of traffic at
its individual maximum. Normal messages, automatic card updates, and
programmable card updates can share a chat and bot account, so presentation
traffic should coalesce and leave headroom for human communication.

## What `retry_after` means

Telegram defines `ResponseParameters.retry_after` as an optional Integer: in
case of flood control, it is the number of seconds left to wait before the
request can be repeated.

LingTai therefore distinguishes two facts:

- `retryable: true` means Telegram supplied a valid nonnegative integer
  `retry_after`, so a caller may start a **new** action after waiting at least
  that long.
- `auto_retry: false` means the addon never sleeps inside the current tool call,
  never holds the MCP worker for the cooldown, and never schedules a hidden
  second side effect.

If Telegram omits or malforms `retry_after`, LingTai omits both `retry_after`
and `retryable` rather than turning an unknown wait into a false promise or an
invented default.

## What Telegram does not document

`ResponseParameters` does not identify whether a particular cooldown is scoped
to a chat, group, method, bot account, or another provider bucket. It also does
not publish the penalty formula or promise whether requests during a cooldown
reset or extend it. A result must therefore not invent `retry_scope`, infer a
global ban from one method, or claim a long penalty's cause from its duration.

## Safe client policy

- A definite 429 is a definite failed request: do not persist it as delivered.
- Return the provider's valid cooldown immediately and release the worker.
- Do not send a second Telegram message saying that Telegram is rate limited;
  that notice itself consumes the rate-limited route. Surface the countdown in
  the tool result, local UI, or another healthy channel.
- Any durable wait, cancellation, coalescing, Task Card pause, or later retry is
  an orchestrator/controller policy outside the one-request adapter. It needs
  explicit authorization and must remain distinguishable from automatic retry.
- Because the provider does not disclose `retry_scope`, throttle presentation
  traffic conservatively and prefer normal human communication over automatic
  or programmable updates.
