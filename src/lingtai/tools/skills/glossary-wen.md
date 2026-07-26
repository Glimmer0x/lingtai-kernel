---
kind: tool-glossary
schema_version: 1
tool_package: lingtai.tools.skills
language: wen
related_files:
- docs.yaml
- src/lingtai/kernel/tool_glossary.py
- src/lingtai/tools/glossary_validator.py
- src/lingtai/tools/skills/glossary-en.md
- src/lingtai/tools/skills/glossary-zh.md
maintenance: |
  Classical-Chinese (wen) glossary for the `skills` tool package (lingtai.tools.skills); body must stay non-empty and distinct from glossary-zh.md. Update in lockstep with glossary-en.md/glossary-zh.md whenever skills's public tool schema changes. The public root uses `action` and `input`; Agent-injected `reasoning` remains root-only.
  Body policy: maintain only a minimal term mapping plus at most one or two sentences of naming rationale; do not translate or duplicate the tool schema, parameters, action behavior, manual, contract, or anatomy.
---
**名相对照**

- `skills`：【路标之器】此器不代汝书技、固技、发布、安装或施技；`info` 唯重校/重扫技典并还康状，不载 manual 全文；`manual` 方还 skills-manual 之文。尔之器灵技能目录。系统之中技能典为 YAML 之列——每技一 `- name:` 块，附 `location:` 与 `description:` 之目——所列皆此时可取之技。用此器前（凡藏用、固定、出新、料理技能之事），必先读 `skills-manual` 一技——呼 `info` 乃得当时之康状，呼 `manual` 方得其文，无所例外。
- `action`：info：重校/重扫技能目录，并还当时之康状（技数、解径、患记），不载 manual 全文。manual：唯还 skills-manual 之文。
- `input`：二 action 皆受之空对象；路径、目录限及他参，不可平列于根。
- `reasoning`：Agent 所注之根级调用由；非 `input` 分支所有。
