---
kind: tool-glossary
schema_version: 1
tool_package: lingtai.tools.tool_family
language: wen
related_files:
- docs.yaml
- src/lingtai/kernel/tool_glossary.py
- src/lingtai/tools/glossary_validator.py
- src/lingtai/tools/tool_family/glossary-en.md
- src/lingtai/tools/tool_family/glossary-zh.md
maintenance: |
  Classical-Chinese glossary for the internal tool_family infrastructure package; keep a distinct, minimal mapping of immutable identifiers and update it with zh/en files. Body policy: maintain only a minimal term mapping plus at most one or two sentences of naming rationale; do not translate or duplicate the tool schema, parameters, action behavior, manual, contract, or anatomy.
---
**名相对照**

- `ToolFamily`：一族聚合工具之内部子 Tool 名籍与 schema 合成者
- `ChildTool`：一子 Tool 之名、`input_schema`、handler 三者所记
- `action`：模型所择子 Tool 之名，即名籍之键
- `input`：所择 action 自有之严输
- `reasoning`：Host 审计之元数据，不入子 Tool 之输
- `summarize`：Host 呈现层之可选后处开关，不入子 Tool 之输
- `manual`：族属保留子 Tool 之名，返所安手册全文与其径
