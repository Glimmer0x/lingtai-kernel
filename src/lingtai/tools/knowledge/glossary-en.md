---
kind: tool-glossary
schema_version: 1
tool_package: lingtai.tools.knowledge
language: en
related_files:
- docs.yaml
- src/lingtai/kernel/tool_glossary.py
- src/lingtai/tools/glossary_validator.py
- src/lingtai/tools/knowledge/glossary-zh.md
- src/lingtai/tools/knowledge/glossary-wen.md
maintenance: |
  English glossary for the `knowledge` tool package (lingtai.tools.knowledge); the English body must stay empty per tool_glossary.py's language contract — update only the identity/schema fields here, and update the zh/wen bodies in lockstep when the Knowledge capability's private lifecycle ownership or its routing through `substrate(action='knowledge')` changes. Knowledge registers no public tool root.
  Body policy: maintain only a minimal term mapping plus at most one or two sentences of naming rationale; do not translate or duplicate the tool schema, parameters, action behavior, manual, contract, or anatomy.
---
