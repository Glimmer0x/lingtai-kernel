---
kind: tool-glossary
schema_version: 1
tool_package: lingtai.tools.write
language: zh
related_files:
- docs.yaml
- src/lingtai/kernel/tool_glossary.py
- src/lingtai/tools/glossary_validator.py
- src/lingtai/tools/write/glossary-en.md
- src/lingtai/tools/write/glossary-wen.md
maintenance: |
  Simplified-Chinese (zh) glossary for the `write` tool package (lingtai.tools.write); body must stay non-empty. Update in lockstep with glossary-en.md/glossary-wen.md whenever write's public tool schema changes.
  Body policy: maintain only a minimal term mapping plus at most one or two sentences of naming rationale; do not translate or duplicate the tool schema, parameters, action behavior, manual, contract, or anatomy.
---
**术语对照**

- `write`：创建或覆盖文件。父目录会自动创建。用于创建新文件或完整重写；小修改优先使用 `edit`。
- `action`：必填操作标识；`write` 与 `manual` 是固定英文标识。
- `input`：必填的封闭操作输入对象。
- `file_path`：文件路径
- `content`：要写入的完整内容
