---
kind: tool-glossary
schema_version: 1
tool_package: lingtai.tools.psyche
language: zh
related_files:
- docs.yaml
- src/lingtai/kernel/tool_glossary.py
- src/lingtai/tools/glossary_validator.py
- src/lingtai/tools/psyche/glossary-en.md
- src/lingtai/tools/psyche/glossary-wen.md
maintenance: |
  Simplified-Chinese (zh) glossary for the `psyche` tool package (lingtai.tools.psyche); body must stay non-empty. Update in lockstep with glossary-en.md/glossary-wen.md whenever psyche's public action inventory or read-only promise changes.
  Body policy: maintain only a minimal term mapping plus at most one or two sentences of naming rationale; do not translate or duplicate the tool schema, parameters, action behavior, manual, contract, or anatomy.
---

**术语对照**

- `psyche`：跨凝蜕长存之四域（pad、灵台、knowledge、skills）唯一公开根；pad + lingtai + knowledge + skills = psyche。调用名保持 canonical English。
- 五个 action 皆为只读手册加载，严格空 input；旧 psyche 之 molt、summarize、name 等动作已归 context 与 system，此根不作别名。
