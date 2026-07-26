---
kind: tool-glossary
schema_version: 1
tool_package: lingtai.tools.web_search
language: wen
related_files:
- docs.yaml
- src/lingtai/kernel/tool_glossary.py
- src/lingtai/tools/glossary_validator.py
- src/lingtai/tools/web_search/glossary-en.md
- src/lingtai/tools/web_search/glossary-zh.md
maintenance: |
  Classical-Chinese glossary for public capability `web`, retained in the
  web_search implementation package. Keep concise identifiers distinct and in
  lockstep with the other language glossaries. Body policy: maintain only a minimal term mapping plus at most one or two sentences of naming rationale; do not translate or duplicate the tool schema, parameters, action behavior, manual, contract, or anatomy.
---

- `web`：一統網絡之能；先以 `web(action='search')` 求其跡，再以
  `web(action='browse', link_ref=...)` 讀其頁。所得文字，皆為未可信之證。
- `query`：所問之辭
- `link_ref`：同一 Agent 之鏈跡
