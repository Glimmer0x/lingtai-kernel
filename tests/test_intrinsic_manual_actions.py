"""Focused coverage for built-in tools that expose installed manual skills."""
from __future__ import annotations

from pathlib import Path

from lingtai.tools import daemon as daemon_tool
from lingtai.tools import file as file_tool
from lingtai.tools import email as email_tool
from lingtai.tools import psyche as psyche_tool
from lingtai.tools import soul as soul_tool
from lingtai.tools import system as system_tool
from lingtai.tools import web_search as web_tool
from lingtai.tools import bash as shell_tool


class _StubAgent:
    def __init__(self, working_dir: Path):
        self._working_dir = working_dir
        self.handlers: dict[str, object] = {}

    def add_tool(self, name: str, *, handler=None, **_kwargs) -> None:
        self.handlers[name] = handler


def _install_manual(workdir: Path, skill_name: str) -> tuple[str, Path]:
    path = (
        workdir
        / ".library"
        / "intrinsic"
        / "capabilities"
        / skill_name
        / "SKILL.md"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    body = f"---\nname: {skill_name}\n---\n\n# {skill_name} sentinel\n"
    path.write_text(body, encoding="utf-8")
    return body, path


def test_manual_actions_return_their_installed_skills(tmp_path: Path) -> None:
    agent = _StubAgent(tmp_path)
    expected = {
        skill: _install_manual(tmp_path, skill)
        for skill in (
            "shell",
            "daemon",
            "email",
            "psyche-manual",
            "read-manual",
            "soul-manual",
            "system-manual",
            "web",
            "file-manual",
        )
    }

    # The five old file roots are gone; the one ``file`` family owns a single
    # ``manual`` action returning ``file-manual``.
    file_tool.setup(agent)

    shell_manager = shell_tool.ShellManager.__new__(shell_tool.ShellManager)
    shell_manager._agent = agent
    daemon_manager = daemon_tool.DaemonManager.__new__(daemon_tool.DaemonManager)
    daemon_manager._agent = agent
    web_manager = web_tool.setup(agent)

    calls = {
        "shell": ("shell", lambda: shell_manager.handle({"action": "manual"})),
        "daemon": ("daemon", lambda: daemon_manager.handle({"action": "manual"})),
        "email": ("email", lambda: email_tool.handle(agent, {"action": "manual"})),
        "psyche": ("psyche-manual", lambda: psyche_tool.handle(agent, {"action": "manual"})),
        "soul": ("soul-manual", lambda: soul_tool.handle(agent, {"action": "manual"})),
        "system": ("system-manual", lambda: system_tool.handle(agent, {"action": "manual"})),
        "web": ("web", lambda: web_manager.handle({"action": "manual", "input": {}})),
        "file": ("file-manual", lambda: agent.handlers["file"](
            {"action": "manual", "input": {}, "reasoning": "load file guidance"}
        )),
    }

    for tool_name, (skill_name, call) in calls.items():
        body, path = expected[skill_name]
        result = call()
        if tool_name == "web":
            assert result["status"] == "ok"
            assert result["action"] == "manual"
            assert result["manual"] == body
            assert result["manual_path"] == str(path)
            assert isinstance(result["current_setting"], dict)
        elif tool_name == "file":
            # ``file`` returns the generic ManualTool canonical child result
            # verbatim (no double wrap): body at content[0].text, host-local
            # path at structuredContent.manual_path.
            assert result == {
                "status": "ok",
                "content": [{"type": "text", "text": body}],
                "structuredContent": {"manual_path": str(path)},
            }
        else:
            assert result == {
                "status": "ok",
                "manual": body,
                "manual_path": str(path),
            }, tool_name


def test_manual_schemas_preserve_runtime_checks_for_ordinary_file_calls(
    tmp_path: Path,
) -> None:
    modules = (
        shell_tool,
        daemon_tool,
        email_tool,
        psyche_tool,
        soul_tool,
        system_tool,
        web_tool,
        file_tool,
    )
    for module in modules:
        schema = module.get_schema()
        action = schema["properties"]["action"]
        assert "manual" in action.get("enum", ()) or "manual" in action["description"]

    assert shell_tool.get_schema()["required"] == []
    assert psyche_tool.get_schema()["required"] == ["action"]
    web_schema = web_tool.get_schema()
    assert web_schema["required"] == ["action", "input", "reasoning"]
    assert len(web_schema["properties"]["input"]["oneOf"]) == 3
    file_schema = file_tool.get_schema()
    assert file_schema["required"] == ["action", "input", "reasoning"]
    assert len(file_schema["properties"]["input"]["oneOf"]) == 6

    agent = _StubAgent(tmp_path)
    agent._file_io = _ActionFileIO(tmp_path)
    file_tool.setup(agent)

    def call(action, **input_):
        return agent.handlers["file"](
            {"action": action, "input": input_, "reasoning": "runtime check"}
        )

    # A schema-required field omitted at runtime still fails at the operation
    # boundary, before any write lands.
    assert call("read")["message"] == "file_path is required"
    assert call("write", file_path=str(tmp_path / "x"))["message"] == "content is required"
    assert call("edit", file_path=str(tmp_path / "x"), old_string="a")["message"] == "new_string is required"
    assert call("glob")["message"] == "pattern is required"
    assert call("grep")["message"] == "pattern is required"
    assert not (tmp_path / "x").exists()


def test_missing_installed_manual_degrades_without_side_effects(tmp_path: Path) -> None:
    agent = _StubAgent(tmp_path)
    expected_path = (
        tmp_path
        / ".library"
        / "intrinsic"
        / "capabilities"
        / "system-manual"
        / "SKILL.md"
    )

    assert system_tool.handle(agent, {"action": "manual"}) == {
        "status": "degraded",
        "manual": "",
        "manual_path": str(expected_path),
        "error": (
            "system-manual manual missing — initializer may have failed or "
            "capability not installed correctly"
        ),
    }
    assert not (tmp_path / ".library").exists()


class _ActionFileIO:
    def __init__(self, root: Path):
        self.root = root
        self.last_traversal = None

    def read(self, path):
        return Path(path).read_text(encoding="utf-8")

    def write(self, path, content):
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def glob(self, pattern, *, root):
        return sorted(str(path) for path in Path(root).glob(pattern))

    def grep(self, pattern, *, path, max_results, glob_filter):
        import re
        result = []
        target = Path(path)
        paths = [target] if target.is_file() else sorted(target.rglob(glob_filter or "*"))
        for current in paths:
            if not current.is_file():
                continue
            for number, line in enumerate(current.read_text(encoding="utf-8").splitlines(), 1):
                if re.search(pattern, line):
                    result.append(type("Match", (), {"path": str(current), "line_number": number, "line": line})())
                    if len(result) >= max_results:
                        return result
        return result


def test_file_action_modes_require_explicit_action_and_fail_loudly(tmp_path: Path) -> None:
    """Every operation is now an explicit action of the one ``file`` family.

    The pre-migration "omit action for the legacy ordinary call" dual mode is
    gone with the five standalone roots: ``action`` is required, each action
    name is canonical, and an unknown one fails with the family's stable typed
    envelope error rather than a per-tool string.
    """
    agent = _StubAgent(tmp_path)
    agent._file_io = _ActionFileIO(tmp_path)

    schema = file_tool.get_schema()
    assert schema["properties"]["action"]["enum"] == [
        "read", "write", "edit", "glob", "grep", "manual",
    ]
    assert schema["required"] == ["action", "input", "reasoning"]
    description = file_tool.get_description()
    for action in ("read", "write", "edit", "glob", "grep", "manual"):
        assert f"action='{action}'" in description
    assert "after the manual result" in description.lower()
    assert "error loop" in description

    file_tool.setup(agent)

    def call(action, **input_):
        return agent.handlers["file"](
            {"action": action, "input": input_, "reasoning": "action mode test"}
        )

    source = tmp_path / "source.txt"
    source.write_text("alpha\n", encoding="utf-8")
    assert call("read", file_path=str(source))["total_lines"] == 1
    assert call("write", file_path=str(tmp_path / "written.txt"), content="beta")["status"] == "ok"
    assert call("edit", file_path=str(source), old_string="alpha", new_string="gamma")["status"] == "ok"
    assert call("glob", pattern="*.txt", path=str(tmp_path))["count"] >= 2
    assert call("grep", pattern="gamma", path=str(source))["count"] == 1

    unsupported = call("unsupported")
    assert unsupported["status"] == "failed"
    assert unsupported["error_code"] == "ACTION_REQUIRED"
    assert "read, write, edit, glob, grep, manual" in unsupported["message"]

    missing_action = agent.handlers["file"]({"input": {}, "reasoning": "no action"})
    assert missing_action["error_code"] == "ACTION_REQUIRED"


def test_file_manual_bodies_explain_one_time_manual_guidance() -> None:
    """Both bodies keep the one-time manual rule after the family migration.

    The pre-migration "omit action for backward compatibility" dual mode is
    gone — ``action`` is now always required — so that phrase is no longer
    asserted. The guidance that still matters is: manual is a one-time lookup,
    ordinary work resumes after it, and repeating it is an error loop.
    """
    file_body = Path("src/lingtai/intrinsic_skills/file-manual/SKILL.md").read_text(encoding="utf-8")
    read_body = Path("src/lingtai/intrinsic_skills/read-manual/SKILL.md").read_text(encoding="utf-8")
    for body in (file_body, read_body):
        assert "ordinary" in body
        assert "one-time" in body
        assert "After" in body
        assert "error loop" in body
        # No body may still teach the retired omit-action mode.
        assert "omit `action`" not in body

    # file-manual is the single family manual; read-manual is nested under it.
    assert "read-manual" in file_body
    assert "nested reference" in read_body
