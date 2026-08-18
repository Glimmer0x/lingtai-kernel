"""Site-specific schema quirk regressions for issues #694 and #913."""

from __future__ import annotations

import copy

from lingtai.llm.openai.adapter import (
    _SITE_SCHEMA_QUIRKS,
    _apply_site_quirks,
    _build_tools,
    _move_type_into_union_branches,
)


def test_moves_parent_type_into_anyof_branches() -> None:
    schema = {"type": "object", "anyOf": [{"required": ["x"]}, {"type": "string"}]}
    result = _move_type_into_union_branches(schema)
    assert "type" not in result
    assert result["anyOf"] == [
        {"type": "object", "required": ["x"]},
        {"type": "string"},
    ]


def test_moves_parent_type_into_oneof_branches() -> None:
    schema = {"type": "object", "oneOf": [{"properties": {"x": {"type": "string"}}}]}
    result = _move_type_into_union_branches(schema)
    assert "type" not in result
    assert result["oneOf"][0]["type"] == "object"


def test_moves_nested_union_types_recursively() -> None:
    schema = {
        "type": "object",
        "properties": {
            "input": {
                "type": "object",
                "anyOf": [{"required": ["x"]}, {"required": ["y"]}],
            },
        },
    }
    result = _move_type_into_union_branches(schema)
    nested = result["properties"]["input"]
    assert "type" not in nested
    assert [branch["type"] for branch in nested["anyOf"]] == ["object", "object"]


def test_inherited_type_moves_through_nested_union_branch() -> None:
    schema = {
        "type": "object",
        "anyOf": [{"anyOf": [{"required": ["x"]}]}],
    }
    result = _move_type_into_union_branches(schema)
    nested = result["anyOf"][0]
    assert "type" not in nested
    assert nested["anyOf"] == [{"type": "object", "required": ["x"]}]


def test_parent_type_moves_into_both_union_keywords() -> None:
    schema = {
        "type": "object",
        "anyOf": [{"required": ["x"]}],
        "oneOf": [{"required": ["y"]}],
    }
    result = _move_type_into_union_branches(schema)
    assert "type" not in result
    assert result["anyOf"] == [{"type": "object", "required": ["x"]}]
    assert result["oneOf"] == [{"type": "object", "required": ["y"]}]


def test_union_without_parent_type_is_preserved() -> None:
    schema = {"anyOf": [{"type": "string"}, {"type": "integer"}]}
    assert _move_type_into_union_branches(schema) == schema


def test_non_union_schema_is_preserved() -> None:
    schema = {"type": "object", "properties": {"x": {"type": "string"}}}
    assert _move_type_into_union_branches(schema) == schema


def test_transform_does_not_mutate_original() -> None:
    schema = {"type": "object", "anyOf": [{"required": ["x"]}]}
    original = copy.deepcopy(schema)
    _move_type_into_union_branches(schema)
    assert schema == original


_CHAT_TOOL = {
    "type": "function",
    "function": {
        "name": "test_tool",
        "description": "test",
        "parameters": {
            "type": "object",
            "anyOf": [{"required": ["action"]}, {"required": ["input"]}],
        },
    },
}

_RESPONSES_TOOL = {
    "type": "function",
    "name": "test_tool",
    "description": "test",
    "parameters": {
        "type": "object",
        "oneOf": [{"required": ["action"]}, {"required": ["input"]}],
    },
}

def _daemon_compact_tool() -> dict:
    from lingtai.tools.daemon import DaemonManager

    manager = DaemonManager.__new__(DaemonManager)
    schemas, _handlers = manager._daemon_intrinsic_surface()
    return _build_tools([schemas["compact"]])[0]


def test_exact_kimi_host_applies_chat_quirk() -> None:
    original = copy.deepcopy(_CHAT_TOOL)
    result = _apply_site_quirks("https://api.kimi.com/coding/v1", [_CHAT_TOOL])
    parameters = result[0]["function"]["parameters"]
    assert parameters == {"type": "object"}
    assert _CHAT_TOOL == original


def test_exact_kimi_host_applies_responses_quirk() -> None:
    result = _apply_site_quirks("https://api.kimi.com/coding/v1", [_RESPONSES_TOOL])
    parameters = result[0]["parameters"]
    assert parameters == {"type": "object"}


def test_exact_moonshot_host_applies_real_daemon_compact_quirk() -> None:
    compact_tool = _daemon_compact_tool()
    original = copy.deepcopy(compact_tool)
    result = _apply_site_quirks(
        "https://api.moonshot.cn/v1",
        [compact_tool],
    )
    parameters = result[0]["function"]["parameters"]
    assert parameters["type"] == "object"
    assert "anyOf" not in parameters
    assert "oneOf" not in parameters
    assert parameters["properties"] == original["function"]["parameters"]["properties"]
    assert parameters["required"] == original["function"]["parameters"]["required"]
    assert parameters["additionalProperties"] is False
    assert compact_tool == original


def test_moonshot_lookalike_host_does_not_apply_quirk() -> None:
    compact_tool = _daemon_compact_tool()
    assert _apply_site_quirks(
        "https://api.moonshot.cn.example.test/v1",
        [compact_tool],
    ) == [compact_tool]


def test_openrouter_does_not_apply_kimi_quirk() -> None:
    assert _apply_site_quirks("https://openrouter.ai/api/v1", [_CHAT_TOOL]) == [
        _CHAT_TOOL
    ]


def test_lookalike_host_does_not_apply_kimi_quirk() -> None:
    assert _apply_site_quirks("https://api.kimi.com.example.test/v1", [_CHAT_TOOL]) == [
        _CHAT_TOOL
    ]


def test_none_and_empty_inputs_are_passthrough() -> None:
    assert _apply_site_quirks(None, [_CHAT_TOOL]) == [_CHAT_TOOL]
    assert _apply_site_quirks("https://api.kimi.com/coding/v1", None) is None
    assert _apply_site_quirks("https://api.kimi.com/coding/v1", []) == []


def test_site_registry_is_exact_and_named() -> None:
    assert _SITE_SCHEMA_QUIRKS == {
        "api.kimi.com": frozenset({"move_type_into_union_branches"}),
        "api.moonshot.cn": frozenset({"move_type_into_union_branches"}),
    }


def _chat(parameters: dict) -> dict:
    return {
        "type": "function",
        "function": {
            "name": "x",
            "description": "x",
            "parameters": parameters,
        },
    }


def test_root_anyof_and_oneof_are_stripped_before_recursive_move() -> None:
    tool = _chat(
        {
            "type": "object",
            "properties": {"x": {"type": "string"}},
            "required": ["x"],
            "additionalProperties": False,
            "anyOf": [{"required": ["x"]}],
            "oneOf": [{"required": ["x"]}],
        }
    )
    original = copy.deepcopy(tool)
    result = _apply_site_quirks("https://api.moonshot.cn/v1", [tool])[0][
        "function"
    ]["parameters"]
    assert result == {
        "type": "object",
        "properties": {"x": {"type": "string"}},
        "required": ["x"],
        "additionalProperties": False,
    }
    assert tool == original


def test_nested_union_still_uses_pr_1408_branch_move() -> None:
    tool = _chat(
        {
            "type": "object",
            "properties": {
                "payload": {
                    "type": "object",
                    "anyOf": [{"required": ["x"]}, {"required": ["y"]}],
                }
            },
        }
    )
    result = _apply_site_quirks("https://api.moonshot.cn/v1", [tool])[0][
        "function"
    ]["parameters"]
    assert result["type"] == "object"
    nested = result["properties"]["payload"]
    assert "type" not in nested
    assert [branch["type"] for branch in nested["anyOf"]] == ["object", "object"]


def test_allof_root_is_untouched() -> None:
    parameters = {
        "type": "object",
        "properties": {"x": {"type": "string"}},
        "allOf": [{"required": ["x"]}],
    }
    result = _apply_site_quirks(
        "https://api.moonshot.cn/v1",
        [_chat(parameters)],
    )[0]["function"]["parameters"]
    assert result == parameters
