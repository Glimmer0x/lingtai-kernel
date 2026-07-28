from __future__ import annotations

from lingtai.tools.mcp import get_description as mcp_description
from lingtai.tools.mcp import get_schema as mcp_schema
from lingtai.tools.substrate import get_description as substrate_description


def test_substrate_description_is_an_explicit_signpost() -> None:
    desc = substrate_description()
    assert desc.startswith("SIGNPOST ONLY:")
    # The four durable domains it routes to, named in the model-facing text.
    for domain in ("pad", "lingtai", "knowledge", "skills"):
        assert domain in desc
    # Every action returns a manual and nothing else.
    assert "never authors, edits, pins, installs, rescans, or loads anything" in desc
    assert "file.write" in desc and "file.edit" in desc
    assert "context.rebuild" in desc


def test_retired_domain_roots_expose_no_tool_description() -> None:
    """The four former public roots are gone, with no compatibility surface."""
    import importlib

    for pkg in ("pad", "lingtai", "knowledge", "skills"):
        module = importlib.import_module(f"lingtai.tools.{pkg}")
        assert not hasattr(module, "get_description"), pkg
        assert not hasattr(module, "get_schema"), pkg
        assert not hasattr(module, "handle"), pkg


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
