"""Compact vertical proof for File's declared official host-plugin slice."""
from __future__ import annotations

import inspect
from pathlib import Path
from types import SimpleNamespace

import pytest

from lingtai.adapters.tool_plugin_host import AgentFileIOAdapter
from lingtai.agent import Agent
from lingtai.kernel.tool_plugin import (
    GRANTABLE_HOST_PORTS,
    OFFICIAL_TOOL_PLUGIN_NAMES,
    ToolPluginHost,
)
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
    assert OFFICIAL_TOOL_PLUGIN_NAMES == (
        "mcp", "avatar", "context", "daemon", "email", "file"
    )
    assert GRANTABLE_HOST_PORTS == (
        "workdir",
        "prompt_section",
        "avatar_parent",
        "context_runtime",
        "daemon_runtime",
        "email_runtime",
        "file_io",
    )
    assert "tool_mount" not in GRANTABLE_HOST_PORTS
    assert DECLARATION.name == "file"
    assert DECLARATION.manual == "file-manual"
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


def test_agent_file_io_adapter_is_concrete_and_holds_no_agent_or_generic_dispatch():
    """File's production port is typed vocabulary, not Agent/service forwarding."""
    writes: list[tuple[str, str]] = []
    stats = SimpleNamespace(
        visited=3,
        elapsed_ms=2,
        truncated_reason=None,
        files_skipped_size=0,
        files_skipped_binary=0,
        dirs_pruned=1,
    )
    match = SimpleNamespace(path="source.txt", line_number=4, line="needle")
    adapter = AgentFileIOAdapter(
        read=lambda path: f"read:{path}",
        write=lambda path, content: writes.append((path, content)),
        glob=lambda pattern, root=None: [f"{root}/{pattern}"],
        grep=lambda pattern, path=None, max_results=50, *, glob_filter=None: [match],
        last_traversal=lambda: stats,
        max_result_chars=lambda: 1234,
    )

    assert adapter.read("x") == "read:x"
    adapter.write("x", "body")
    assert writes == [("x", "body")]
    assert adapter.glob("*.py", root="repo") == ["repo/*.py"]
    assert adapter.grep("needle", path="repo", glob_filter="*.txt") == [match]
    assert adapter.last_traversal is stats
    assert adapter.max_result_chars == 1234
    assert not hasattr(adapter, "_agent")
    assert not hasattr(adapter, "tool_mount")
    source = inspect.getsource(AgentFileIOAdapter)
    assert "Any" not in source
    assert "__getattr__" not in source
    assert not hasattr(adapter, "dispatch")


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
        "capabilities/file-manual/SKILL.md"
    )
    assert Path(manual["structuredContent"]["manual_path"]).is_file()
    assert not (
        file_agent.working_dir
        / ".library"
        / "intrinsic"
        / "capabilities"
        / "file"
    ).exists()


def test_foreign_file_declaration_fails_before_bind_and_preserves_live_identity(file_agent):
    """A different File declaration cannot replace handler, schema, or claim."""
    from lingtai.adapters.tool_plugin_host import register_agent_tool_plugins
    from lingtai.kernel.tool_plugin import (
        BoundToolPlugin,
        DuplicateToolPluginNameError,
        ToolPluginDeclaration,
    )

    bind_calls: list[object] = []

    def foreign_bind(host):
        bind_calls.append(host)
        return BoundToolPlugin(
            name="file",
            schema={"properties": {"action": {"enum": ["other", "manual"]}}},
            handler=lambda _args: {"status": "wrong"},
            description="foreign File",
        )

    foreign = ToolPluginDeclaration(
        name="file",
        actions=("other",),
        input_schemas={
            "other": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            }
        },
        manual_input_schema=DECLARATION.manual_input_schema,
        manual="file-manual",
        description="foreign File declaration",
        binder=foreign_bind,
        requires=("workdir",),
    )
    original_handler = file_agent._tool_handlers["file"]
    original_schema = next(s for s in file_agent._tool_schemas if s.name == "file")

    with pytest.raises(DuplicateToolPluginNameError, match="different declaration"):
        register_agent_tool_plugins(file_agent, [foreign])

    assert bind_calls == []
    assert file_agent.official_tool_plugins["file"] is DECLARATION
    assert file_agent._tool_handlers["file"] is original_handler
    assert next(s for s in file_agent._tool_schemas if s.name == "file") is original_schema
    assert [s.name for s in file_agent._tool_schemas].count("file") == 1


def _manual_call(handler):
    return handler(
        {"action": "manual", "input": {}, "reasoning": "load File manual"}
    )


def test_file_manual_prefers_established_legacy_install_path(tmp_path):
    """A real legacy install wins over the transitional candidate destination."""
    body = Path("src/lingtai/tools/file/manual/SKILL.md").read_text(encoding="utf-8")
    workdir = tmp_path / "agent"
    legacy = workdir / ".library" / "intrinsic" / "capabilities" / "file-manual" / "SKILL.md"
    transitional = workdir / ".library" / "intrinsic" / "capabilities" / "file" / "SKILL.md"
    legacy.parent.mkdir(parents=True)
    transitional.parent.mkdir(parents=True)
    legacy.write_text(body, encoding="utf-8")
    transitional.write_text("wrong transitional body", encoding="utf-8")

    host = ToolPluginHost(
        "file",
        {"workdir": SimpleNamespace(path=workdir), "file_io": object()},
    )
    result = _manual_call(DECLARATION.bind(host).handler)

    assert result["status"] == "ok"
    assert result["content"][0]["text"] == body
    assert result["structuredContent"]["manual_path"] == str(legacy)


def test_file_manual_redirect_marker_never_becomes_the_operational_body(tmp_path):
    """A retained marker falls through to the package-owned body explicitly."""
    body = Path("src/lingtai/tools/file/manual/SKILL.md").read_text(encoding="utf-8")
    marker = Path("src/lingtai/intrinsic_skills/file-manual/SKILL.md").read_text(encoding="utf-8")
    workdir = tmp_path / "agent"
    legacy = workdir / ".library" / "intrinsic" / "capabilities" / "file-manual" / "SKILL.md"
    transitional = workdir / ".library" / "intrinsic" / "capabilities" / "file" / "SKILL.md"
    legacy.parent.mkdir(parents=True)
    transitional.parent.mkdir(parents=True)
    legacy.write_text(marker, encoding="utf-8")
    transitional.write_text(body, encoding="utf-8")

    host = ToolPluginHost(
        "file",
        {"workdir": SimpleNamespace(path=workdir), "file_io": object()},
    )
    result = _manual_call(DECLARATION.bind(host).handler)

    assert result["status"] == "ok"
    assert result["content"][0]["text"] == body
    assert result["structuredContent"]["manual_path"] == str(transitional)


def test_file_manual_has_one_source_body_and_explicit_package_data_routes():
    """The source marker is retained while wheel/sdist routes name the package body."""
    body_path = Path("src/lingtai/tools/file/manual/SKILL.md")
    marker_path = Path("src/lingtai/intrinsic_skills/file-manual/SKILL.md")
    body = body_path.read_text(encoding="utf-8")
    marker = marker_path.read_text(encoding="utf-8")
    assert body != marker
    assert "redirect: src/lingtai/tools/file/manual/SKILL.md" in marker
    assert "# File Manual" in body
    assert "# File Manual" not in marker

    wheel_rules = Path("pyproject.toml").read_text(encoding="utf-8")
    sdist_rules = Path("MANIFEST.in").read_text(encoding="utf-8")
    assert '"*/manual/**/*"' in wheel_rules
    assert "graft src/lingtai/tools/file/manual" in sdist_rules
