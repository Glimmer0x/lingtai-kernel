"""Focused acceptance for the action-separated public ``vision`` family.

``vision`` keeps its public tool name and both public action values
(``analyze``/``manual``) while moving to the LTP v2 envelope
(``action``/``input``/``reasoning``/``summarize``) composed and dispatched by
the generic ``lingtai.tools.tool_family`` infrastructure. These tests pin the
migration's own promises: exactly one public model root, both child schemas and
handlers, envelope/cross-action rejection strictly *before* any provider I/O,
a manual route that constructs and calls no provider, the exact preserved
success/failure result shapes, and Chat/Responses wire parity with no double
wrapping of the manual child's canonical result.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from lingtai.services.vision import VisionService
from lingtai.tools import vision as vision_tool
from lingtai.tools.vision import VisionManager, get_schema, setup


class _StubAgent:
    """Minimal agent surface: a working dir plus one recorded ``add_tool``."""

    def __init__(self, working_dir: Path):
        self._working_dir = working_dir
        self.tools: dict[str, dict] = {}

    def add_tool(self, name: str, **kwargs) -> None:
        self.tools[name] = kwargs


def _install_manual(workdir: Path) -> tuple[str, Path]:
    path = workdir / ".library" / "intrinsic" / "capabilities" / "vision" / "SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "---\nname: vision-manual\n---\n\n# vision sentinel\n"
    path.write_text(body, encoding="utf-8")
    return body, path


def _never_called_service() -> MagicMock:
    """A vision service that fails the test if any provider I/O is attempted."""
    svc = MagicMock(spec=VisionService)
    svc.analyze_image.side_effect = AssertionError(
        "provider I/O must not run for this call"
    )
    return svc


def _manager(tmp_path: Path, service=None) -> VisionManager:
    return VisionManager(_StubAgent(tmp_path), vision_service=service)


# ---------------------------------------------------------------------------
# Public registration: one model root, unchanged public name
# ---------------------------------------------------------------------------


def test_setup_registers_exactly_one_public_vision_root(tmp_path):
    agent = _StubAgent(tmp_path)
    setup(agent, vision_service=MagicMock(spec=VisionService))

    assert list(agent.tools) == ["vision"]
    assert agent.tools["vision"]["schema"] == get_schema()
    assert agent.tools["vision"]["glossary_package"] == "lingtai.tools.vision"


def test_public_actions_are_exactly_analyze_and_manual():
    schema = get_schema()
    assert schema["properties"]["action"]["enum"] == ["analyze", "manual"]


# ---------------------------------------------------------------------------
# Root schema: strict envelope with action <-> input correlation
# ---------------------------------------------------------------------------


def test_root_schema_is_the_strict_ltp_v2_envelope():
    schema = get_schema()
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert schema["required"] == ["action", "input", "reasoning"]
    assert set(schema["properties"]) == {"action", "input", "reasoning", "summarize"}
    assert schema["properties"]["reasoning"]["type"] == "string"
    assert schema["properties"]["summarize"]["type"] == "boolean"


def test_root_schema_correlates_each_action_const_with_its_own_input():
    schema = get_schema()
    conditions = {
        cond["if"]["properties"]["action"]["const"]: cond["then"]["properties"]["input"]
        for cond in schema["allOf"]
    }
    assert set(conditions) == {"analyze", "manual"}
    assert set(conditions["analyze"]["properties"]) == {"image_path", "question"}
    assert conditions["manual"]["properties"] == {}
    for cond in schema["allOf"]:
        # A strict ``if`` with a missing property matches vacuously; the guard
        # keeps each branch scoped to its own action.
        assert cond["if"]["required"] == ["action"]


def test_both_child_input_schemas_are_exposed_before_invocation():
    branches = get_schema()["properties"]["input"]["oneOf"]
    assert [b["title"] for b in branches] == ["analyze input", "manual input"]

    analyze_branch, manual_branch = branches
    assert analyze_branch["required"] == ["image_path", "question"]
    assert analyze_branch["additionalProperties"] is False
    assert analyze_branch["properties"]["image_path"]["type"] == "string"
    # Optional ``question`` is a required nullable property, matching the
    # strict-object convention the other migrated families use.
    assert analyze_branch["properties"]["question"]["type"] == ["string", "null"]

    assert manual_branch["properties"] == {}
    assert manual_branch["additionalProperties"] is False


def test_reasoning_and_summarize_never_leak_into_child_input():
    schema = get_schema()
    for branch in schema["properties"]["input"]["oneOf"]:
        assert not {"reasoning", "_reasoning", "summarize", "action"} & set(
            branch["properties"]
        )
    for cond in schema["allOf"]:
        assert not {"reasoning", "_reasoning", "summarize", "action"} & set(
            cond["then"]["properties"]["input"]["properties"]
        )


# ---------------------------------------------------------------------------
# Dispatch: envelope/cross-action failures land before any provider I/O
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "args",
    [
        pytest.param({"reasoning": "r"}, id="missing-action"),
        pytest.param({"action": "look", "input": {}, "reasoning": "r"}, id="unknown-action"),
        pytest.param(
            {"action": "analyze", "input": "not-an-object", "reasoning": "r"},
            id="input-not-object",
        ),
        pytest.param(
            {"action": "analyze", "input": {"image_path": "x.png", "question": None}, "reasoning": "r", "engine": "x"},
            id="unknown-root-field",
        ),
        pytest.param(
            {"action": "analyze", "input": {"image_path": "x.png", "question": None}, "reasoning": "r", "summarize": "yes"},
            id="non-boolean-summarize",
        ),
    ],
)
def test_invalid_envelope_fails_before_provider_io(tmp_path, args):
    mgr = _manager(tmp_path, _never_called_service())
    result = mgr.handle(args)
    assert result["status"] == "error"
    assert isinstance(result["message"], str) and result["message"]


def test_cross_action_input_is_rejected_before_provider_io(tmp_path):
    """``manual``'s strict-empty input cannot smuggle in analyze's fields."""
    mgr = _manager(tmp_path, _never_called_service())
    result = mgr.handle(
        {"action": "manual", "input": {"image_path": "x.png"}, "reasoning": "r"}
    )
    assert result["status"] == "error"
    assert "manual" not in result  # never reached the manual child either


def test_unknown_analyze_input_field_is_rejected_before_provider_io(tmp_path):
    mgr = _manager(tmp_path, _never_called_service())
    result = mgr.handle(
        {
            "action": "analyze",
            "input": {"image_path": "x.png", "question": None, "action": "manual"},
            "reasoning": "r",
        }
    )
    assert result["status"] == "error"


def test_root_summarize_is_stripped_and_never_reaches_the_child(tmp_path):
    svc = MagicMock(spec=VisionService)
    svc.analyze_image.return_value = "a chart"
    img = tmp_path / "chart.png"
    img.write_bytes(b"\x89PNG fake")

    mgr = _manager(tmp_path, svc)
    result = mgr.handle(
        {
            "action": "analyze",
            "input": {"image_path": str(img), "question": "What is this?"},
            "reasoning": "read the chart",
            "summarize": True,
        }
    )
    assert result == {"status": "ok", "analysis": "a chart"}
    svc.analyze_image.assert_called_once_with(str(img), prompt="What is this?")


# ---------------------------------------------------------------------------
# analyze: exact preserved success/failure shapes and routing
# ---------------------------------------------------------------------------


def test_analyze_success_shape_is_exact(tmp_path):
    svc = MagicMock(spec=VisionService)
    svc.analyze_image.return_value = "A dog in the park"
    img = tmp_path / "dog.jpg"
    img.write_bytes(b"\xff\xd8\xff fake jpeg")

    result = _manager(tmp_path, svc).handle(
        {
            "action": "analyze",
            "input": {"image_path": str(img), "question": "What animal?"},
            "reasoning": "identify the animal",
        }
    )
    assert result == {"status": "ok", "analysis": "A dog in the park"}


def test_analyze_null_question_uses_the_unchanged_default_prompt(tmp_path):
    svc = MagicMock(spec=VisionService)
    svc.analyze_image.return_value = "An image"
    img = tmp_path / "photo.png"
    img.write_bytes(b"\x89PNG fake")

    _manager(tmp_path, svc).handle(
        {
            "action": "analyze",
            "input": {"image_path": "photo.png", "question": None},
            "reasoning": "describe it",
        }
    )
    svc.analyze_image.assert_called_once_with(
        str(img), prompt="Describe what you see in this image."
    )


@pytest.mark.parametrize(
    ("image_path", "expected_fragment"),
    [
        pytest.param("", "Provide image_path", id="empty-path"),
        pytest.param("/nonexistent/img.png", "Image file not found", id="missing-file"),
    ],
)
def test_analyze_input_failures_keep_their_exact_messages(
    tmp_path, image_path, expected_fragment
):
    svc = _never_called_service()
    result = _manager(tmp_path, svc).handle(
        {
            "action": "analyze",
            "input": {"image_path": image_path, "question": None},
            "reasoning": "r",
        }
    )
    assert result["status"] == "error"
    assert expected_fragment in result["message"]


def test_analyze_request_failure_is_sanitized_and_points_to_manual(tmp_path):
    svc = MagicMock(spec=VisionService)
    svc.analyze_image.side_effect = RuntimeError(
        "token=secret https://user:pw@example.test/v1"
    )
    img = tmp_path / "x.png"
    img.write_bytes(b"fake")

    result = _manager(tmp_path, svc).handle(
        {"action": "analyze", "input": {"image_path": str(img), "question": None}, "reasoning": "r"}
    )
    assert result["status"] == "error"
    assert "RuntimeError" in result["message"]
    # The taught pointer must be the full accepted envelope, not the
    # pre-migration bare shorthand the dispatcher now rejects.
    assert "vision(action='manual', input={}" in result["message"]
    assert "reasoning=" in result["message"]
    assert "secret" not in result["message"]
    assert "example.test" not in result["message"]


def test_analyze_empty_response_is_an_error(tmp_path):
    svc = MagicMock(spec=VisionService)
    svc.analyze_image.return_value = ""
    img = tmp_path / "x.png"
    img.write_bytes(b"fake")

    result = _manager(tmp_path, svc).handle(
        {"action": "analyze", "input": {"image_path": str(img), "question": None}, "reasoning": "r"}
    )
    assert result == {
        "status": "error",
        "message": "Vision analysis returned no response.",
    }


def test_analyze_without_a_direct_route_returns_the_setup_manual_reason(tmp_path):
    reason = (
        "No direct vision provider was configured; use vision(action='manual', "
        "input={}, reasoning='no direct vision provider is configured')."
    )
    mgr = VisionManager(_StubAgent(tmp_path), vision_service=None, manual_reason=reason)
    result = mgr.handle(
        {"action": "analyze", "input": {"image_path": "x.png", "question": None}, "reasoning": "r"}
    )
    assert result == {"status": "error", "message": reason}


# ---------------------------------------------------------------------------
# manual: family-owned, no provider construction or call, exact body/path
# ---------------------------------------------------------------------------


def test_manual_returns_the_exact_installed_body_and_path(tmp_path):
    body, path = _install_manual(tmp_path)
    mgr = _manager(tmp_path, _never_called_service())

    result = mgr.handle({"action": "manual", "input": {}, "reasoning": "load guidance"})
    assert result == {
        "status": "ok",
        "action": "manual",
        "manual": body,
        "manual_path": str(path),
    }


def test_manual_result_is_not_double_wrapped(tmp_path):
    _install_manual(tmp_path)
    result = _manager(tmp_path, _never_called_service()).handle(
        {"action": "manual", "input": {}, "reasoning": "r"}
    )
    # The canonical MCP child result is adapted, never nested inside another
    # action result.
    assert "content" not in result
    assert "structuredContent" not in result
    assert not any(isinstance(value, dict) for value in result.values())


def test_missing_installed_manual_degrades_without_side_effects(tmp_path):
    expected = tmp_path / ".library" / "intrinsic" / "capabilities" / "vision" / "SKILL.md"
    result = _manager(tmp_path, _never_called_service()).handle(
        {"action": "manual", "input": {}, "reasoning": "r"}
    )
    assert result == {
        "status": "degraded",
        "action": "manual",
        "manual": "",
        "manual_path": str(expected),
        "error": (
            "vision manual missing — initializer may have failed or "
            "capability not installed correctly"
        ),
    }
    assert not (tmp_path / ".library").exists()


def test_manual_constructs_no_provider_and_calls_no_service(tmp_path):
    _install_manual(tmp_path)
    agent = _StubAgent(tmp_path)
    with patch("lingtai.services.vision.create_vision_service") as mock_factory:
        mgr = setup(agent, provider="not-a-real-provider")
        result = agent.tools["vision"]["handler"](
            {"action": "manual", "input": {}, "reasoning": "r"}
        )
    mock_factory.assert_not_called()
    assert mgr._vision_service is None
    assert result["status"] == "ok"
    assert result["action"] == "manual"


def test_manual_works_even_when_a_configured_service_would_fail(tmp_path):
    """Manual performs no analyze operation, so a broken provider is irrelevant."""
    body, path = _install_manual(tmp_path)
    svc = _never_called_service()
    result = _manager(tmp_path, svc).handle(
        {"action": "manual", "input": {}, "reasoning": "r"}
    )
    assert result["manual"] == body
    assert result["manual_path"] == str(path)
    svc.analyze_image.assert_not_called()


def test_manual_method_matches_the_dispatched_manual_action(tmp_path):
    _install_manual(tmp_path)
    mgr = _manager(tmp_path, _never_called_service())
    assert mgr.manual() == mgr.handle(
        {"action": "manual", "input": {}, "reasoning": "r"}
    )


def test_every_taught_manual_pointer_round_trips_through_the_dispatcher(tmp_path):
    """The guidance strings must teach a call the dispatcher actually accepts.

    Before the envelope migration, `vision(action='manual')` was a complete
    valid call. It no longer is — `input` is required — so any in-result string
    still teaching the bare shorthand would send an agent into a rejection loop.
    This walks every guidance string vision can emit, extracts the taught call,
    and proves the literal shape it teaches dispatches successfully.
    """
    import re

    _install_manual(tmp_path)
    mgr = _manager(tmp_path, _never_called_service())

    # Collect the guidance strings from every source that emits one: the
    # setup-failure builder, both analyze failure paths, and every
    # `manual_reason` literal assigned in setup().
    source = Path("src/lingtai/tools/vision/__init__.py").read_text(encoding="utf-8")
    taught = re.findall(r"vision\(action='manual'([^)]*)\)", source)
    assert len(taught) >= 18, f"expected every guidance string, found {len(taught)}"

    for suffix in taught:
        assert "input={}" in suffix.replace("{{}}", "{}"), (
            f"taught pointer omits input: vision(action='manual'{suffix})"
        )
        assert "reasoning=" in suffix, (
            f"taught pointer omits reasoning: vision(action='manual'{suffix})"
        )

    # The taught shape, executed literally, must succeed through dispatch.
    assert mgr.handle(
        {"action": "manual", "input": {}, "reasoning": "load vision guidance"}
    )["status"] == "ok"
    # ...and the pre-migration bare shorthand must NOT, which is exactly why
    # the strings had to change.
    assert mgr.handle({"action": "manual"})["status"] == "error"


def test_no_bare_manual_pointer_survives_in_any_vision_owned_surface():
    """No `vision(action='manual')` without `input=` anywhere vision owns."""
    import re

    owned = [
        Path("src/lingtai/tools/vision/__init__.py"),
        Path("src/lingtai/tools/vision/CONTRACT.md"),
        Path("src/lingtai/tools/vision/manual/SKILL.md"),
        Path("src/lingtai/services/vision/openai.py"),
    ]
    bare = re.compile(r"vision\(action=[\"']manual[\"']\s*\)")
    for path in owned:
        text = path.read_text(encoding="utf-8")
        assert not bare.search(text), f"stale bare manual pointer in {path}"


def test_family_registers_the_reserved_manual_child_once(tmp_path):
    mgr = _manager(tmp_path)
    assert mgr._family.child_names == ("analyze", "manual")
    assert mgr._family.has_manual()


def test_wire_and_dispatch_families_come_from_one_child_declaration(tmp_path):
    """The schema-only family and the manager's family cannot drift apart.

    Both are built by `_build_family`, so child names, order, and per-action
    input schemas are identical objects/values on the wire surface and at the
    dispatch boundary — the duplication that a second hand-written registry
    would allow is structurally impossible.
    """
    from lingtai.tools.vision import _FAMILY

    mgr = _manager(tmp_path, _never_called_service())
    assert mgr._family.child_names == _FAMILY.child_names
    assert mgr._family.build_schema() == _FAMILY.build_schema() == get_schema()


def test_manual_child_input_schema_is_the_generic_owners_object(tmp_path):
    """Vision registers the generic manual schema, never a local near-copy.

    A restated copy previously carried `"required": []` while the generic
    owner's omitted the key, so the wire schema and the dispatch-side schema
    for the same child were two different objects. The generic owner now
    states `"required": []` explicitly too (byte-for-byte comparability
    across every consumer), so the wire branch is checked against it.
    """
    from lingtai.tools.tool_family.manual import MANUAL_INPUT_SCHEMA

    manual_branch = get_schema()["properties"]["input"]["oneOf"][1]
    assert manual_branch["properties"] == MANUAL_INPUT_SCHEMA["properties"]
    assert manual_branch["additionalProperties"] is False
    assert manual_branch.get("required") == MANUAL_INPUT_SCHEMA["required"] == []


# ---------------------------------------------------------------------------
# Wire parity: Chat Completions and Responses
# ---------------------------------------------------------------------------


def test_vision_schema_survives_both_provider_wires():
    from lingtai.kernel.llm.base import FunctionSchema
    from lingtai.llm.openai.adapter import _build_responses_tools, _build_tools

    schema = FunctionSchema(
        name="vision",
        description=vision_tool.get_description(),
        parameters=get_schema(),
    )
    chat = _build_tools([schema])[0]["function"]["parameters"]
    responses = _build_responses_tools([schema])[0]["parameters"]

    for wire, combinator in ((chat, "oneOf"), (responses, "anyOf")):
        assert wire["type"] == "object"
        assert wire["required"] == ["action", "input", "reasoning"]
        assert wire["additionalProperties"] is False
        assert set(wire["properties"]) == {"action", "input", "reasoning", "summarize"}
        assert wire["properties"]["action"]["enum"] == ["analyze", "manual"]
        branches = wire["properties"]["input"][combinator]
        assert [b["title"] for b in branches] == ["analyze input", "manual input"]
        for branch in branches:
            assert branch["additionalProperties"] is False
            assert not {"reasoning", "_reasoning", "summarize"} & set(
                branch["properties"]
            )
        # Root action<->input correlation must survive the wire, not just the
        # composed schema: each action const keeps its own `then.input`.
        correlated = {
            cond["if"]["properties"]["action"]["const"]: cond["then"]["properties"]["input"]
            for cond in wire["allOf"]
        }
        assert set(correlated) == {"analyze", "manual"}
        assert set(correlated["analyze"]["properties"]) == {"image_path", "question"}
        assert correlated["manual"]["properties"] == {}


def test_root_summarize_reaches_the_single_centralized_summarizer(tmp_path):
    """``vision`` is a migrated LTP v2 family, so its canonical root
    ``summarize`` boolean is recognized by the one existing centralized
    a-priori summarizer — no second summarizer, and the raw result is still
    durably logged before the visible replacement."""
    from lingtai.kernel.llm.base import ToolCall
    from lingtai.kernel.loop_guard import LoopGuard
    from lingtai.kernel.tool_executor import ToolExecutor
    from lingtai.kernel.tool_result_summary import (
        APRIORI_SUMMARY_MARKER,
        summary_requested,
    )

    assert summary_requested({"summarize": True}, "vision") is True
    # An unmigrated tool's own ``summarize``-named field is still never
    # reinterpreted as this cross-cutting control.
    assert summary_requested({"summarize": True}, "some_unmigrated_tool") is False

    events: list[tuple] = []
    raw = {"status": "ok", "analysis": "VISIONRAW-marker long description"}
    executor = ToolExecutor(
        dispatch_fn=lambda tc: raw,
        make_tool_result_fn=lambda name, result, **kw: {"content": result, **kw},
        guard=LoopGuard(),
        known_tools={"vision"},
        parallel_safe_tools=set(),
        logger_fn=lambda event_type, **fields: events.append((event_type, fields)),
        working_dir=tmp_path,
        summarizer_fn=lambda sp, up, tn, cid: "SUMMARY: a chart",
    )
    results, _, _ = executor.execute(
        [
            ToolCall(
                name="vision",
                args={
                    "action": "analyze",
                    "input": {"image_path": "x.png", "question": None},
                    "reasoning": "read the chart",
                    "summarize": True,
                },
                id="v1",
            )
        ]
    )
    content = results[0]["content"]
    assert content["artifact"] == APRIORI_SUMMARY_MARKER
    assert content["generated_summary"] == "SUMMARY: a chart"
    assert "VISIONRAW-marker" not in str(content)
    assert any(
        event_type == "tool_result" and "VISIONRAW-marker" in str(fields.get("result"))
        for event_type, fields in events
    )


def test_dispatch_is_identical_regardless_of_originating_wire(tmp_path):
    """Dispatch depends only on the normalized args dict both wires converge to."""
    svc = MagicMock(spec=VisionService)
    svc.analyze_image.return_value = "same answer"
    img = tmp_path / "x.png"
    img.write_bytes(b"fake")
    mgr = _manager(tmp_path, svc)

    chat_call = mgr.handle(
        {"action": "analyze", "input": {"image_path": str(img), "question": "Q"}, "reasoning": "chat-wire"}
    )
    responses_call = mgr.handle(
        {"action": "analyze", "input": {"image_path": str(img), "question": "Q"}, "reasoning": "responses-wire"}
    )
    assert chat_call == responses_call == {"status": "ok", "analysis": "same answer"}
