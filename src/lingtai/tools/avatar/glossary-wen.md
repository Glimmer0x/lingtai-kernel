---
kind: tool-glossary
schema_version: 1
tool_package: lingtai.tools.avatar
language: wen
related_files:
- docs.yaml
- src/lingtai/kernel/tool_glossary.py
- src/lingtai/tools/glossary_validator.py
- src/lingtai/tools/avatar/glossary-en.md
- src/lingtai/tools/avatar/glossary-zh.md
maintenance: |
  Classical-Chinese (wen) glossary for the `avatar` tool package; body must stay non-empty and distinct from glossary-zh.md. Update when avatar's public identifiers change.
  Body policy: maintain only a minimal term mapping plus at most one or two sentences of naming rationale; do not translate or duplicate the tool schema, parameters, action behavior, manual, contract, or anatomy.
---
**名相对照**

- `avatar`：唯一公开之器，以 `action` 分遣，根必具 `input`。
- `action`：根必填，无默认。`spawn`｜`rules`｜`manual`。
- `input`：根必填之严整动作输入，各动作各守其字段。
- `reasoning`：Agent 所注之根级可选元数，非 `input` 所属；为 spawn 之使命简报。
- `name`：他我真名（`spawn.input` 必填），亦为 .lingtai/ 下目录之名；单段字母/数/下划线/连字，至长六十四。
- `type`：`spawn.input` 之 `shallow`（默认，初生）或 `deep`（二重身）。
- `comment`：`spawn.input` 之恒注，不承自父。
- `dry_run`：`spawn.input` 之预览，不化进程。
- `confirm`：`spawn.input` 之任务确认。
- `rules_content`：`rules.input` 所需法则之文；`spawn` 不属此字段。
