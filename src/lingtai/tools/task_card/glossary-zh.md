---
kind: tool-glossary
schema_version: 1
tool_package: lingtai.tools.task_card
language: zh
related_files:
- docs.yaml
- src/lingtai/kernel/tool_glossary.py
- src/lingtai/tools/glossary_validator.py
- src/lingtai/tools/task_card/glossary-en.md
- src/lingtai/tools/task_card/glossary-wen.md
maintenance: |
  Simplified-Chinese (zh) glossary for the `task_card` tool package (lingtai.tools.task_card); body must stay non-empty. Update in lockstep with glossary-en.md/glossary-wen.md whenever task_card's public tool schema changes.
  Body policy: maintain only a minimal term mapping plus at most one or two sentences of naming rationale; do not translate or duplicate the tool schema, parameters, action behavior, manual, contract, or anatomy.
---
**术语对照**

- `task_card`：任务卡。唯一公开工具，以 `action` 分派；每个 agent 至多维护一份声明式产物、一路监视。
- `action`：必填。`start`（启，开始一路监视）｜`inspect`（查，查看现状）｜`retry`（续，重跑渲染脚本）｜`stop`（止，暂停监视并保留正文）｜`remove`（撤，终止清理并删正文）｜`manual`（手册，返回本工具手册全文）。
- `renderer_path`：`start` 必填，渲染脚本在工作目录内之路径。
- `watch_id`：`inspect`/`retry`/`stop` 用以定位既有监视之标识。
- `interval_s`：刷新间隔（秒）。
- `timeout_s`：单次渲染超时（秒），为安全上限。
- `max_refreshes`：最大刷新次数，亦为安全上限。
