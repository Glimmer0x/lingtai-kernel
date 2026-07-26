---
kind: tool-glossary
schema_version: 1
tool_package: lingtai.tools.avatar
language: zh
related_files:
- docs.yaml
- src/lingtai/kernel/tool_glossary.py
- src/lingtai/tools/glossary_validator.py
- src/lingtai/tools/avatar/glossary-en.md
- src/lingtai/tools/avatar/glossary-wen.md
maintenance: |
  Simplified-Chinese (zh) glossary for the `avatar` tool package (lingtai.tools.avatar); body must stay non-empty (tool_glossary.py enforces this). Update in lockstep with glossary-en.md/glossary-wen.md whenever avatar's public tool schema changes.
  Body policy: maintain only a minimal term mapping plus at most one or two sentences of naming rationale; do not translate or duplicate the tool schema, parameters, action behavior, manual, contract, or anatomy.
---
**术语对照**

- `avatar`：唯一公开工具，以 `action` 分派，根含必填 `input`。
- `action`：根级必填，无默认值。`spawn`（化出独立他我）｜`rules`（设置网络法则）｜`manual`（只读，返回已安装手册）。
- `input`：根级必填之严格动作输入；各动作只纳其所属字段。
- `reasoning`：Agent 注入之可选根级元数据，非 `input` 字段；用于 spawn 任务简报。
- `name`：他我之真名（`spawn` 的 `input` 中必填）。兼作 .lingtai/ 下目录名。单段：字母/数字/下划线/连字符，最长64字。
- `type`：`spawn.input` 之 'shallow'（默认，初生）或 'deep'（二重身）。
- `comment`：`spawn.input` 之持久系统注解。不承自父。
- `dry_run`：`spawn.input` 之预览开关，不生进程。
- `confirm`：`spawn.input` 之任务确认开关。
- `rules_content`：`rules.input` 所需之法则内容；`spawn` 不拥有此字段。
