"""Focused vertical proof for Web's declared host-plugin mount."""
from __future__ import annotations

from lingtai.agent import Agent
from tests._service_helpers import make_gemini_mock_service


def test_official_web_mount_preserves_declared_surface_and_packaged_manual(tmp_path):
    from lingtai.tools.web_search import DECLARATION

    agent = Agent(
        service=make_gemini_mock_service(),
        agent_name="web-official-plugin",
        working_dir=tmp_path / "agent",
        capabilities={"web": {}},
    )
    try:
        assert DECLARATION.requires == ("workdir", "runtime", "provider_identity")
        assert agent.official_tool_plugins["web"] is DECLARATION
        assert [schema.name for schema in agent._tool_schemas].count("web") == 1

        schema = agent._tool_schemas[[s.name for s in agent._tool_schemas].index("web")]
        assert schema.parameters["properties"]["action"]["enum"] == ["search", "browse", "manual"]

        manual = agent._tool_handlers["web"](
            {"action": "manual", "input": {}, "reasoning": "guidance"}
        )
        assert manual["status"] == "ok"
        assert manual["manual"]
        assert manual["manual_path"].endswith("capabilities/web/SKILL.md")
    finally:
        agent.stop(timeout=1.0)
