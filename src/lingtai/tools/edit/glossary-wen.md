---
kind: tool-glossary
schema_version: 1
tool_package: lingtai.tools.edit
language: wen
related_files:
- docs.yaml
- src/lingtai/kernel/tool_glossary.py
- src/lingtai/tools/glossary_validator.py
- src/lingtai/tools/edit/glossary-en.md
- src/lingtai/tools/edit/glossary-zh.md
maintenance: |
  Classical-Chinese (wen) glossary for the `edit` tool package (lingtai.tools.edit); body must stay non-empty and distinct from glossary-zh.md. Update in lockstep with glossary-en.md/glossary-zh.md whenever edit's public tool schema changes.
  Body policy: maintain only a minimal term mapping plus at most one or two sentences of naming rationale; do not translate or duplicate the tool schema, parameters, action behavior, manual, contract, or anatomy.
---
**名相对照**

- `action`：所行之名；唯 `edit`、`manual` 二值
- `input`：封闭之行参；`manual` 之参当为空
- `replace_all`：严式字段，可为 `boolean` 或 `null`；`null` 即 false
- `current_setting`：每次结果所附之设置快照，仅为证据而不改编辑

`file_path`、`old_string`、`new_string` 皆守英文名相，不设省略 `action` 或扁平参之别名。
