"""Compact vertical proof for File's declared official host-plugin slice."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from lingtai.agent import Agent
from lingtai.kernel.tool_plugin import OFFICIAL_TOOL_PLUGIN_NAMES, ToolPluginHost
from lingtai.tools.file import DECLARATION, get_schema
from tests._service_helpers import make_gemini_mock_service


@pytest.fixture
def file_agent(tmp_path):
    agent = Agent(
        service=make_gemini_mock_service(),
        agent_name="file-tool-plugin",
        working_dir=tmp_path / "agent",
        capabilities={"file": {}},
    )
    try:
        yield agent
    finally:
        agent.stop(timeout=1.0)


def test_file_declaration_is_static_and_derives_the_public_surface():
    """The kernel-reserved declaration exists before an Agent and owns identity."""
    assert "file" in OFFICIAL_TOOL_PLUGIN_NAMES
    assert DECLARATION.name == "file"
    assert DECLARATION.requires == ("workdir", "file_io")
    assert DECLARATION.actions == ("read", "write", "edit", "glob", "grep")
    assert DECLARATION.public_actions == (
        "read", "write", "edit", "glob", "grep", "manual"
    )
    assert tuple(get_schema()["properties"]["action"]["enum"]) == DECLARATION.public_actions


def test_file_bind_accepts_only_its_narrow_ports(tmp_path):
    """Composition needs a workdir and File's operation vocabulary, not Agent."""
    host = ToolPluginHost(
        "file",
        {
            "workdir": SimpleNamespace(path=tmp_path),
            "file_io": object(),
        },
    )
    bound = DECLARATION.bind(host)

    assert host.granted == ("workdir", "file_io")
    assert bound.name == "file"
    assert tuple(bound.schema["properties"]["action"]["enum"]) == DECLARATION.public_actions


def test_official_file_mount_preserves_real_operations_and_packaged_manual(file_agent):
    """The controlled host mount dispatches the unchanged write/read/manual paths."""
    assert file_agent.official_tool_plugins["file"] is DECLARATION
    assert [schema.name for schema in file_agent._tool_schemas].count("file") == 1

    handler = file_agent._tool_handlers["file"]
    target = str(file_agent.working_dir / "nested" / "source.txt")
    write = handler(
        {
            "action": "write",
            "input": {"file_path": target, "content": "alpha\nbeta\n"},
            "reasoning": "exercise declared file write",
        }
    )
    assert write == {"status": "ok", "path": target, "bytes": 11}

    read = handler(
        {
            "action": "read",
            "input": {
                "file_path": target,
                "offset": None,
                "limit": None,
                "max_chars": None,
            },
            "reasoning": "exercise declared file read",
        }
    )
    assert read["content"] == "1\talpha\n2\tbeta\n"

    manual = handler(
        {"action": "manual", "input": {}, "reasoning": "read file guidance"}
    )
    assert manual["status"] == "ok"
    assert "name: file-manual" in manual["content"][0]["text"]
    assert manual["structuredContent"]["manual_path"].endswith(
        "capabilities/file/SKILL.md"
    )
    assert Path(manual["structuredContent"]["manual_path"]).is_file()
    assert not (
        file_agent.working_dir
        / ".library"
        / "intrinsic"
        / "capabilities"
        / "file-manual"
    ).exists()
