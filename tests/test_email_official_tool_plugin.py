"""Focused real-Agent proof for Email's declared host-plugin recut."""
from __future__ import annotations

import json

import pytest

from lingtai.agent import Agent
from tests._service_helpers import make_gemini_mock_service


@pytest.fixture
def email_agent(tmp_path):
    agent = Agent(
        service=make_gemini_mock_service(),
        agent_name="email-official-plugin",
        working_dir=tmp_path / "agent",
        capabilities={},
    )
    try:
        yield agent
    finally:
        agent.stop(timeout=1.0)


def test_official_email_mount_keeps_real_agent_runtime_and_package_manual(email_agent):
    """The official handler uses the existing manager, not a synthetic stand-in."""
    from lingtai.tools.email import DECLARATION
    from lingtai.tools.email._family_schema import ACTION_ORDER

    assert DECLARATION.actions == ACTION_ORDER[:-1]
    assert DECLARATION.requires == ("workdir", "intrinsic_dispatch")
    assert email_agent.official_tool_plugins["email"] is DECLARATION
    # The kernel retains the key for internal callers, but its handler is the
    # official handler and the model-facing inventory has only the official tool.
    assert "email" in email_agent._intrinsics
    assert "email" in email_agent._intrinsic_modules
    assert email_agent._intrinsics["email"] is email_agent._tool_handlers["email"]
    assert [schema.name for schema in email_agent._tool_schemas].count("email") == 1
    assert [schema.name for schema in email_agent._build_tool_schemas()].count("email") == 1

    handler = email_agent._tool_handlers["email"]
    assert handler({"action": "check", "input": {}, "reasoning": "inspect"}) == {
        "status": "ok", "total": 0, "showing": 0, "emails": []
    }

    manual = handler({"action": "manual", "input": {}, "reasoning": "procedure"})
    assert manual["status"] == "ok"
    assert "# Email Manual" in manual["manual"]
    assert manual["manual_path"].endswith("capabilities/email/SKILL.md")


@pytest.mark.parametrize(
    ("capabilities", "disable"),
    [
        ({"email": None}, None),
        ({}, ["email"]),
    ],
    ids=["null-capability", "disable-list"],
)
def test_email_opt_out_forms_keep_one_official_surface_on_construction_and_refresh(
    tmp_path, capabilities, disable
):
    """Email's former mandatory surface cannot fall back to a generic intrinsic."""
    workdir = tmp_path / "agent"
    agent = Agent(
        service=make_gemini_mock_service(),
        agent_name="email-opt-out",
        working_dir=workdir,
        capabilities=capabilities,
        disable=disable,
    )
    try:
        init_data = {
            "manifest": {
                "agent_name": "email-opt-out",
                "language": "en",
                "llm": {
                    "provider": "gemini",
                    "model": "gemini-test",
                    "api_key": "test-key",
                    "base_url": None,
                },
                "capabilities": capabilities,
                "disable": disable or [],
                "soul": {"delay": 60},
                "context_limit": None,
                "admin": {"karma": True},
                "streaming": False,
            },
            "principle": "",
            "covenant": "",
            "pad": "",
            "lingtai": "",
            "soul": "",
        }
        (workdir / "init.json").write_text(json.dumps(init_data), encoding="utf-8")

        from lingtai.tools.email import DECLARATION

        for phase in ("construction", "refresh"):
            if phase == "refresh":
                agent._setup_from_init()
            assert agent.official_tool_plugins["email"] is DECLARATION
            assert [schema.name for schema in agent._tool_schemas].count("email") == 1
            assert [schema.name for schema in agent._build_tool_schemas()].count("email") == 1
            assert agent._tool_handlers["email"] is agent._intrinsics["email"]
    finally:
        agent.stop(timeout=1.0)
