---
kind: tool-glossary
schema_version: 1
tool_package: lingtai.tools.task_card
language: wen
related_files:
- docs.yaml
- src/lingtai/kernel/tool_glossary.py
- src/lingtai/tools/glossary_validator.py
- src/lingtai/tools/task_card/glossary-en.md
- src/lingtai/tools/task_card/glossary-zh.md
maintenance: |
  Classical-Chinese (wen) glossary for the `task_card` tool package (lingtai.tools.task_card); body must stay non-empty and distinct from glossary-zh.md. Update in lockstep with glossary-en.md/glossary-zh.md whenever task_card's public tool schema changes.
  Body policy: maintain only a minimal term mapping plus at most one or two sentences of naming rationale; do not translate or duplicate the tool schema, parameters, action behavior, manual, contract, or anatomy.
---
**名相对照**

- `task_card`：任务牌。唯一公开之器，以 `action` 分遣；每 agent 至多存一声明之产、一路之监。
- `action`：必填。`start`（启，始一路监）｜`inspect`（查，视其现状）｜`retry`（续，复运渲染之脚）｜`stop`（止，暂监而存其文）｜`remove`（撤，终清而删其文）｜`manual`（手册，还此器手册全文）。
- `renderer_path`：`start` 必填，渲染之脚在工作之境内者，其径。
- `watch_id`：`inspect`/`retry`/`stop` 用以指既存之监，其识。
- `interval_s`：刷新之隔，以秒计。
- `timeout_s`：一渲之限时，以秒计，为安全之限。
- `max_refreshes`：刷新之至多次数，亦为安全之限。
