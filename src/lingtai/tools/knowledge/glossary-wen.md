---
kind: tool-glossary
schema_version: 1
tool_package: lingtai.tools.knowledge
language: wen
related_files:
- docs.yaml
- src/lingtai/kernel/tool_glossary.py
- src/lingtai/tools/glossary_validator.py
- src/lingtai/tools/knowledge/glossary-en.md
- src/lingtai/tools/knowledge/glossary-zh.md
maintenance: |
  Classical-Chinese (wen) glossary for the `knowledge` tool package (lingtai.tools.knowledge); body must stay non-empty and distinct from glossary-zh.md. Update in lockstep with glossary-en.md/glossary-zh.md whenever knowledge's public tool schema changes.
  Body policy: maintain only a minimal term mapping plus at most one or two sentences of naming rationale; do not translate or duplicate the tool schema, parameters, action behavior, manual, contract, or anatomy.
---
**名相对照**

- `knowledge`：【路标之器】此器不代汝造经、修经、搜经或载经；`info` 唯重扫 knowledge 之目录并还康状；`manual` 方还 knowledge-manual 之文。汝跨凝蜕长存之私有知识目录——所习、所断、所悟之记。每经卷皆为 knowledge/<名>/ 一匣，内置 KNOWLEDGE.md（YAML frontmatter 须有 name 与 description），可附副件（script、素材、笔记、原始日志）。系统提示中之知识典为 YAML 之列——每经一 `- name:` 块，附 `location:` 与 `description:` 之目；正文按需以 read 工具取之，与 skills 同律。知识乃汝私藏：经卷可引本地之路、邮件之 id、日志之记——此皆 skills 所不可依也。新经以 write/edit 直书 knowledge/<名>/KNOWLEDGE.md；修订同此。呼 `knowledge(action='info', input={}, reasoning='...')` 可重扫目录、验其康；呼 `knowledge(action='manual', input={}, reasoning='...')` 以取手册之文。用此器前，必先读 `knowledge-manual` 一技，无所例外。
- `action`：info：重扫 knowledge/，返当时之康状（卷数、根径、损经之记），不载 manual 全文。manual：唯还 knowledge-manual 之文，且不重扫。
- `input`：所择 action 独有之入参。info 与 manual 二者皆严格空器（strict-empty），不纳一字；有余字者，未及行事而先见拒。
- `reasoning`：根上必具之由，乃宿主稽核之属，终不入 input 之内。
- `summarize`：根上可有之果后处置之钥，默为否；非动作之入参。knowledge 之果本简，寻常不必启之。
