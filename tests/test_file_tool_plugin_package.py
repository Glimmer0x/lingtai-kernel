"""Compact vertical proof for File's declared official host-plugin slice."""
from __future__ import annotations

import inspect
import stat
import sys
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
from lingtai.services import file_io_sidecar as sidecar_mod
from lingtai.services.file_io_sidecar import default_file_io_service
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
        "mcp", "avatar", "context", "daemon", "email", "file", "plugin",
        "notification", "shell", "soul", "system", "task_card", "vision", "web",
    )
    assert GRANTABLE_HOST_PORTS == (
        "workdir",
        "prompt_section",
        "avatar_parent",
        "context_runtime",
        "daemon_runtime",
        "email_runtime",
        "file_io",
        "plugin_catalog",
        "notification_state",
        "notifications",
        "configuration",
        "soul_runtime",
        "system_runtime",
        "identity",
        "shutdown",
        "task_card_lifecycle",
        "task_card_notifications",
        "active_provider",
        "web_runtime",
        "provider_identity",
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


def _tagged_sidecar(directory: Path, name: str, tag: str) -> Path:
    """Write an executable fake sidecar whose glob/grep results name *tag*."""
    script = directory / name
    script.write_text(
        f"#!{sys.executable}\n"
        "import json, sys\n"
        "request = json.loads(sys.stdin.read())\n"
        "sys.stdout.write(json.dumps({\n"
        "    'ok': True, 'op': request['op'],\n"
        f"    'paths': ['/served/by/{tag}'],\n"
        f"    'matches': [{{'path': '{tag}.txt', 'line_number': 1, 'line': 'served by {tag}'}}],\n"
        "    'visited': 1, 'elapsed_ms': 0, 'truncated_reason': None,\n"
        "    'files_skipped_size': 0, 'files_skipped_binary': 0, 'dirs_pruned': 0,\n"
        "}))\n",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return script


def test_mounted_glob_and_grep_follow_the_live_sidecar_resolution(tmp_path, monkeypatch):
    """Mounted glob/grep must not stay bound to a sidecar copy cleared after boot.

    Reproduces the live outage: ``setup.py`` stages a packaged copy under
    ``lingtai/bin/`` that outranks the dev-tree build, the Agent boots against
    it, and a later ``LINGTAI_SKIP_RUST_BUILD=1`` build clears that staged copy.
    The mounted family must keep serving through the still-present dev-tree
    binary exactly as a freshly built ``default_file_io_service`` does.
    """
    for name in ("LINGTAI_FILE_IO_SIDECAR", "LINGTAI_SEARCH_SIDECAR", "LINGTAI_FILE_IO_BACKEND"):
        monkeypatch.delenv(name, raising=False)
    packaged = _tagged_sidecar(tmp_path, "packaged-sidecar.py", "packaged")
    dev_tree = _tagged_sidecar(tmp_path, "dev-tree-sidecar.py", "dev-tree")
    monkeypatch.setattr(
        sidecar_mod,
        "_packaged_binary",
        lambda: str(packaged) if packaged.is_file() else None,
    )
    monkeypatch.setattr(sidecar_mod, "_dev_tree_binary", lambda: str(dev_tree))

    agent = Agent(
        service=make_gemini_mock_service(),
        agent_name="file-live-sidecar",
        working_dir=tmp_path / "agent",
        capabilities={"file": {}},
    )
    try:
        handler = agent._tool_handlers["file"]

        def glob():
            return handler(
                {
                    "action": "glob",
                    "input": {"pattern": "*.py", "path": None},
                    "reasoning": "exercise mounted glob provenance",
                }
            )

        def grep():
            return handler(
                {
                    "action": "grep",
                    "input": {"pattern": "served", "path": None, "glob": None, "max_matches": None},
                    "reasoning": "exercise mounted grep provenance",
                }
            )

        assert glob() == {"matches": ["/served/by/packaged"], "count": 1}
        assert [m["text"] for m in grep()["matches"]] == ["served by packaged"]

        # What ``setup.py``'s ``_clear_staged_sidecar()`` did to the live tree.
        packaged.unlink()

        assert glob() == {"matches": ["/served/by/dev-tree"], "count": 1}
        assert [m["text"] for m in grep()["matches"]] == ["served by dev-tree"]
        assert default_file_io_service(root=agent.working_dir).glob("*.py") == [
            "/served/by/dev-tree"
        ]
    finally:
        agent.stop(timeout=1.0)


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


def test_file_manual_uses_established_install_path(tmp_path):
    """The manual action loads the established installed File manual."""
    body = Path("src/lingtai/tools/file/manual/SKILL.md").read_text(encoding="utf-8")
    workdir = tmp_path / "agent"
    legacy = workdir / ".library" / "intrinsic" / "capabilities" / "file-manual" / "SKILL.md"
    legacy.parent.mkdir(parents=True)
    legacy.write_text(body, encoding="utf-8")

    host = ToolPluginHost(
        "file",
        {"workdir": SimpleNamespace(path=workdir), "file_io": object()},
    )
    result = _manual_call(DECLARATION.bind(host).handler)

    assert result["status"] == "ok"
    assert result["content"][0]["text"] == body
    assert result["structuredContent"]["manual_path"] == str(legacy)
