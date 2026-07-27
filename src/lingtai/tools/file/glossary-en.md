---
kind: tool-glossary
schema_version: 1
tool_package: lingtai.tools.file
language: en
related_files:
- docs.yaml
- src/lingtai/kernel/tool_glossary.py
- src/lingtai/tools/glossary_validator.py
- src/lingtai/tools/file/glossary-zh.md
- src/lingtai/tools/file/glossary-wen.md
maintenance: |
  English glossary for the unified `file` tool family (lingtai.tools.file); the English body must stay empty per tool_glossary.py's language contract — update only the identity/schema fields here, and update the zh/wen bodies in lockstep when the family's public action set or envelope changes. The five retained implementation packages (read/write/edit/glob/grep) keep their own glossaries for their internal identifiers; this one covers the public family surface only.
  Body policy: maintain only a minimal term mapping plus at most one or two sentences of naming rationale; do not translate or duplicate the tool schema, parameters, action behavior, manual, contract, or anatomy.
---
