"""ManualTool stable contract: reserved name, strict empty input, dual return.

Covers the generic ``lingtai.tools.tool_family.manual`` builder in isolation
(fake agent, no real Web/browser wiring) plus its use as ``web``'s own
``manual`` child, so both the infra and its first real consumer are proven.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from lingtai.tools.tool_family import RESERVED_MANUAL_NAME, ChildTool, ToolFamily, ToolFamilyError
from lingtai.tools.tool_family.manual import MANUAL_INPUT_SCHEMA, build_manual_child


class _FakeAgent:
    def __init__(self, working_dir: Path) -> None:
        self._working_dir = working_dir


def _install_manual(working_dir: Path, skill_name: str, body: str) -> Path:
    manual_dir = working_dir / ".library" / "intrinsic" / "capabilities" / skill_name
    manual_dir.mkdir(parents=True)
    path = manual_dir / "SKILL.md"
    path.write_text(body, encoding="utf-8")
    return path


def test_manual_child_reserved_name_is_exactly_manual():
    agent = _FakeAgent(Path("/nonexistent"))
    child = build_manual_child(agent, "widget")
    assert child.name == RESERVED_MANUAL_NAME == "manual"


def test_manual_child_input_schema_is_strict_empty():
    agent = _FakeAgent(Path("/nonexistent"))
    child = build_manual_child(agent, "widget")
    # Strict empty: no properties admitted, and closed. Pinned by identity with
    # the exported canonical constant, so a consumer that references it (this
    # builder; ``avatar``) cannot drift from a restated literal. This asserts
    # only the generic constant — it makes no claim about how many families
    # still keep a local copy, so a family collapsing onto the export is a
    # separate, independently reviewable change.
    assert child.input_schema is MANUAL_INPUT_SCHEMA
    assert child.input_schema == {
        "type": "object", "properties": {}, "required": [], "additionalProperties": False,
    }


def test_manual_child_actual_handler_returns_body_at_content_text_and_path_at_structured_content(tmp_path):
    """Invokes the ACTUAL generic manual child handler (not an unused
    presentational helper) and proves the two fields the approved v0.4
    ManualTool acceptance requires of the real, dispatched-to child result:
    full body at ``content[0].text``, host-local path at
    ``structuredContent.manual_path`` (model-visible, not only in a
    ``_meta``-style side channel)."""
    manual_path = _install_manual(tmp_path, "widget", "# Widget manual\nFull body here.")
    agent = _FakeAgent(tmp_path)
    child = build_manual_child(agent, "widget")
    result = child.handler({})
    assert result["status"] == "ok"
    assert result["content"] == [{"type": "text", "text": "# Widget manual\nFull body here."}]
    assert result["structuredContent"] == {"manual_path": str(manual_path)}
    assert "error" not in result


def test_manual_child_missing_manual_fails_honestly_no_io_error(tmp_path):
    agent = _FakeAgent(tmp_path)  # no manual installed
    child = build_manual_child(agent, "widget")
    result = child.handler({})
    assert result["status"] == "degraded"
    assert result["content"] == [{"type": "text", "text": ""}]
    assert "manual_path" in result["structuredContent"]
    assert "error" in result


def test_reserved_manual_name_collision_across_two_manual_children_fails_loudly(tmp_path):
    agent = _FakeAgent(tmp_path)
    first = build_manual_child(agent, "widget")
    second = build_manual_child(agent, "widget")  # a second, distinct manual child
    with pytest.raises(ToolFamilyError):
        ToolFamily("widget", [first, second])


def test_a_family_without_any_manual_child_is_still_valid():
    def handler(_input):
        return {"status": "ok"}

    fam = ToolFamily("widget", [ChildTool("spin", {"type": "object", "properties": {}, "additionalProperties": False}, handler)])
    assert not fam.has_manual()


def test_web_manual_child_shares_the_same_reserved_contract(tmp_path):
    from lingtai.tools.web_search import setup

    class _Agent:
        def __init__(self, working_dir):
            self._working_dir = working_dir

        def add_tool(self, *args, **kwargs):
            pass

    class _Port:
        def handle(self, args):
            return {"status": "ok"}

    manual_dir = tmp_path / ".library" / "intrinsic" / "capabilities" / "web"
    manual_dir.mkdir(parents=True)
    (manual_dir / "SKILL.md").write_text("web manual body", encoding="utf-8")

    manager = setup(_Agent(tmp_path), browser_port=_Port())
    result = manager.handle({"action": "manual", "input": {}, "reasoning": "load web guidance"})
    assert result["status"] == "ok"
    assert result["manual"] == "web manual body"
    assert result["manual_path"] == str(manual_dir / "SKILL.md")
    assert result["action"] == "manual"
    assert "current_setting" in result
    # The generic child's canonical MCP-compatible fields must not leak into
    # Web's own pre-migration public flat shape — that adaptation is Web's
    # own Host/presentation job (``WebManager._adapt_manual_result``),
    # applied strictly after ``self._family.handle(...)`` dispatch.
    assert "content" not in result
    assert "structuredContent" not in result


def test_web_family_handle_returns_canonical_manual_result_verbatim_before_host_adaptation(tmp_path):
    """Proves the ownership boundary directly: ``manager._family.handle(...)``
    — the real ``ToolFamily`` this family registers its ``manual`` child in —
    returns the child's own canonical ``content``/``structuredContent``
    result verbatim (no double wrap, no legacy flat fields), while
    ``manager.handle(...)`` on the exact same envelope returns Web's
    pre-migration public flat shape with no canonical fields. This is the
    no-double-wrap/Host-owns-presentation contract: dispatch produces the
    canonical result; Web's own Host layer adapts it strictly afterward."""
    from lingtai.tools.web_search import setup

    class _Agent:
        def __init__(self, working_dir):
            self._working_dir = working_dir

        def add_tool(self, *args, **kwargs):
            pass

    class _Port:
        def handle(self, args):
            return {"status": "ok"}

    manual_dir = tmp_path / ".library" / "intrinsic" / "capabilities" / "web"
    manual_dir.mkdir(parents=True)
    (manual_dir / "SKILL.md").write_text("web manual body", encoding="utf-8")

    manager = setup(_Agent(tmp_path), browser_port=_Port())
    envelope = {"action": "manual", "input": {}, "reasoning": "load web guidance"}

    canonical = manager._family.handle(envelope)
    assert canonical["status"] == "ok"
    assert canonical["content"] == [{"type": "text", "text": "web manual body"}]
    assert canonical["structuredContent"] == {"manual_path": str(manual_dir / "SKILL.md")}
    assert "manual" not in canonical
    assert "manual_path" not in canonical
    assert "action" not in canonical
    assert "current_setting" not in canonical

    flat = manager.handle(envelope)
    assert flat["status"] == "ok"
    assert flat["manual"] == "web manual body"
    assert flat["manual_path"] == str(manual_dir / "SKILL.md")
    assert flat["action"] == "manual"
    assert "current_setting" in flat
    assert "content" not in flat
    assert "structuredContent" not in flat


def test_web_manual_missing_manual_keeps_exact_public_degraded_shape(tmp_path):
    """Web's own public ``handle()`` result for a missing/degraded manual
    keeps its exact pre-migration flat shape — this is the Host-side
    adaptation of the generic canonical child result, proven for the
    missing-manual case specifically (the success case is covered above)."""
    from lingtai.tools.web_search import setup

    class _Agent:
        def __init__(self, working_dir):
            self._working_dir = working_dir

        def add_tool(self, *args, **kwargs):
            pass

    class _Port:
        def handle(self, args):
            return {"status": "ok"}

    manager = setup(_Agent(tmp_path), browser_port=_Port())  # no manual installed
    result = manager.handle({"action": "manual", "input": {}, "reasoning": "load web guidance"})
    assert result["status"] == "degraded"
    assert result["manual"] == ""
    assert "manual_path" in result
    assert result["action"] == "manual"
    assert "current_setting" in result
    assert "error" in result
    assert "content" not in result
    assert "structuredContent" not in result


def test_web_manual_rejects_nonempty_input(tmp_path):
    from lingtai.tools.web_search import setup

    class _Agent:
        def __init__(self, working_dir):
            self._working_dir = working_dir

        def add_tool(self, *args, **kwargs):
            pass

    class _Port:
        def handle(self, args):
            return {"status": "ok"}

    manager = setup(_Agent(tmp_path), browser_port=_Port())
    result = manager.handle({"action": "manual", "input": {"topic": "search"}, "reasoning": "x"})
    assert result["status"] == "failed"
    assert result["error_code"] == "INVALID_ARGUMENT"
