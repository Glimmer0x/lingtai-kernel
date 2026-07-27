from __future__ import annotations

from lingtai.tools.knowledge import get_description as knowledge_description
from lingtai.tools.mcp import get_description as mcp_description
from lingtai.tools.mcp import get_schema as mcp_schema
from lingtai.tools.skills import get_description as skills_description


def test_skills_and_knowledge_descriptions_are_explicit_signposts() -> None:
    skills_desc = skills_description()
    assert skills_desc.startswith("SIGNPOST ONLY:")
    assert "does not author, pin, publish, install, or execute skills" in skills_desc
    knowledge_desc = knowledge_description()
    assert knowledge_desc.startswith("SIGNPOST ONLY:")
    assert "does not create, edit, search, or load knowledge entries" in knowledge_desc


def test_mcp_description_and_actions_are_explicit_signposts() -> None:
    assert mcp_description().startswith("SIGNPOST ONLY:")
    assert "does not register, activate, configure, or troubleshoot MCP servers" in mcp_description()
    assert "`info` only re-reads the registry" in mcp_description()
    assert "`manual` returns the mcp-manual body" in mcp_description()
    schema = mcp_schema()
    prop = schema["properties"]["action"]
    # The ToolFamily migration keeps the public action values byte-identical
    # and preserves the hand-written signpost action description verbatim.
    assert prop["enum"] == ["info", "manual"]
    assert schema["required"] == ["action", "input", "reasoning"]
    assert [b["title"] for b in schema["properties"]["input"]["oneOf"]] == [
        "info input",
        "manual input",
    ]
    action = prop["description"]
    assert "info: signpost-only action" in action
    assert "without the manual body" in action
    assert "manual: return only the mcp-manual skill body" in action
    assert "Neither action mutates MCP configuration" in action
