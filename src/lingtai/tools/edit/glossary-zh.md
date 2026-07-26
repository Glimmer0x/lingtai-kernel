---
kind: tool-glossary
schema_version: 1
tool_package: lingtai.tools.edit
language: zh
related_files:
- docs.yaml
- src/lingtai/kernel/tool_glossary.py
- src/lingtai/tools/glossary_validator.py
- src/lingtai/tools/edit/glossary-en.md
- src/lingtai/tools/edit/glossary-wen.md
maintenance: |
  Simplified-Chinese (zh) glossary for the `edit` tool package (lingtai.tools.edit); body must stay non-empty. Update in lockstep with glossary-en.md/glossary-wen.md whenever edit's public tool schema changes.
  Body policy: maintain only a minimal term mapping plus at most one or two sentences of naming rationale; do not translate or duplicate the tool schema, parameters, action behavior, manual, contract, or anatomy.
---
**术语对照**

- `action`：明确的操作名；值为 `edit` 或 `manual`
- `input`：封闭的操作输入对象；`manual` 的输入为空
- `replace_all`：可为 `boolean` 或 `null` 的严格字段；`null` 表示 false
- `current_setting`：每次结果附带的设置快照诊断，不改变编辑行为

`file_path`、`old_string`、`new_string` 保持英文标识，不提供省略 `action` 或扁平输入别名。
