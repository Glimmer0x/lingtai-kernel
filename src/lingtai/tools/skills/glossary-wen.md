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
  Classical-Chinese (wen) glossary for the `skills` tool package (lingtai.tools.skills); body must stay non-empty and distinct from glossary-zh.md. Update in lockstep with glossary-en.md/glossary-zh.md whenever skills's public tool schema changes.
  Body policy: maintain only a minimal term mapping plus at most one or two sentences of naming rationale; do not translate or duplicate the tool schema, parameters, action behavior, manual, contract, or anatomy.
---
**名相对照**

- `skills`：【路标之器】此器不代汝书技、固技、发布、安装或施技；`info` 唯重校/重扫技典并还康状，不载 manual 全文；`manual` 方还 skills-manual 之文。尔之器灵技能目录。系统之中技能典为 YAML 之列——每技一 `- name:` 块，附 `location:` 与 `description:` 之目——所列皆此时可取之技。用此器前（凡藏用、固定、出新、料理技能之事），必先读 `skills-manual` 一技——呼 `info` 即得其文与当时之康状，无所例外。
- `action`：info：重校/重扫技能目录，并还当时之康状（技数、解径、患记），不载 manual 全文。manual：唯还 skills-manual 之文，不动技典。
- `input`：所选 `action` 之严入之匣。此器二 action 皆空匣（`{}`），凡有所纳，未及施行而先败。
- `reasoning`：必具，述此番呼器之由；乃封函之属，绝非 action 之入。
- `summarize`：可有可无之然否，居根位，司果之后治，本为否；绝不入 `input`，亦绝非 action 之入。
