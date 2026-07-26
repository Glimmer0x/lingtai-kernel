---
kind: tool-glossary
schema_version: 1
tool_package: lingtai.tools.read
language: zh
related_files:
- docs.yaml
- src/lingtai/kernel/tool_glossary.py
- src/lingtai/tools/glossary_validator.py
- src/lingtai/tools/read/glossary-en.md
- src/lingtai/tools/read/glossary-wen.md
maintenance: |
  Simplified-Chinese (zh) glossary for the `read` tool package (lingtai.tools.read); body must stay non-empty. Update when read's public action/input schema or user-visible terminology changes.
  Body policy: maintain only a minimal term mapping plus at most one or two sentences of naming rationale; do not translate or duplicate the tool schema, parameters, action behavior, manual, contract, or anatomy.
---
**术语对照**

- `action`：明确操作名；仅为 `read` 或 `manual`
- `input`：封闭的操作输入对象；`manual` 的输入必须为空
- `summary`：嵌套于 `input` 的精确布尔摘要控制，默认 `false`，不改变读取行为
- `current_setting`：每次结果附带的严格设置快照，仅作证据而不改变读取

`file_path`、`offset`、`limit`、`max_chars`、`next_offset` 与 `line_truncated` 保持英文标识；不提供省略 `action`、扁平参数或兼容别名。
