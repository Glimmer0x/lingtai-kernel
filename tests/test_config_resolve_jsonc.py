"""Direct unit coverage for the string-aware JSONC reader.

``parse_jsonc`` / ``load_jsonc`` are the kernel's single entry point for
reading preset manifests, init config, and migration inputs. These tests lock
in the string-aware handling of both JSONC normalisations (``//`` comments and
trailing commas): string values must survive byte-for-byte, even when they
contain text that looks like a comment marker or a trailing-comma pattern.

Regression: lingtai-kernel#725 — the whole-text trailing-comma regex used to
corrupt string values containing `, ]` / `, }` (or `,]` / `,}`).
"""

import json

import pytest

from lingtai.kernel.config_resolve import (
    _strip_trailing_commas,
    load_jsonc,
    parse_jsonc,
)


def test_load_jsonc_preserves_comma_bracket_inside_strings(tmp_path):
    """String values containing `, ]` / `, }` are not rewritten (#725)."""
    p = tmp_path / "carriers.jsonc"
    p.write_text('{"pattern": "a, ]b", "cmd": "x, }y"}', encoding="utf-8")
    assert load_jsonc(p) == {"pattern": "a, ]b", "cmd": "x, }y"}


def test_load_jsonc_preserves_multi_space_bracket_inside_strings(tmp_path):
    """Multiple spaces between comma and bracket inside a string survive."""
    p = tmp_path / "ws.jsonc"
    p.write_text('{"pattern": "a,   ]b", "cmd": "x,    }y"}', encoding="utf-8")
    assert load_jsonc(p) == {"pattern": "a,   ]b", "cmd": "x,    }y"}


def test_parse_jsonc_string_aware_across_real_whitespace():
    """The comma pass never rewrites string content, even when the span
    would cover real control whitespace (newline or tab).

    Real control characters inside a string are invalid JSON, so those inputs
    now raise ``JSONDecodeError`` instead of being silently "fixed" by eating
    the comma+bracket like the old whole-text regex did.
    """
    assert _strip_trailing_commas('{"a": "x,\n ]y"}') == '{"a": "x,\n ]y"}'
    assert _strip_trailing_commas('{"a": "x,\t]y"}') == '{"a": "x,\t]y"}'
    for malformed in ('{"a": "x,\n]y"}', '{"a": "x,\t]y"}'):
        with pytest.raises(json.JSONDecodeError):
            parse_jsonc(malformed)


def test_parse_jsonc_still_strips_trailing_commas():
    """Genuine JSONC trailing commas still collapse to strict JSON."""
    assert parse_jsonc('{"a": [1, 2, ], "b": {"c": 1, }, }') == {
        "a": [1, 2],
        "b": {"c": 1},
    }


def test_parse_jsonc_trailing_comma_before_comment():
    """A trailing comma before a `//` comment still collapses (comment
    stripping runs before comma stripping within each pass)."""
    assert parse_jsonc('{"a": 1,  // note\n}') == {"a": 1}


def test_parse_jsonc_features_compose_with_strings():
    """URLs, `, ]`-bearing strings, comments (incl. quoted examples) and
    trailing commas all behave at once."""
    body = """{
      // copy as "init.json" -- a quote inside a comment must stay inert
      "url": "https://example.test/path?from=kernel",
      "desc": "options: a, } or b, ]",
      "arr": [1, 2, ],
    }"""
    assert parse_jsonc(body) == {
        "url": "https://example.test/path?from=kernel",
        "desc": "options: a, } or b, ]",
        "arr": [1, 2],
    }


def test_parse_jsonc_preserves_escaped_quote_before_pattern():
    """An escaped quote immediately before `, ]` inside a string survives."""
    assert parse_jsonc('{"re": "end \\", ]"}') == {"re": 'end ", ]'}


def test_parse_jsonc_preserves_double_slash_inside_strings():
    """`//` inside a string value is never treated as a comment."""
    assert parse_jsonc('{"docs": "https://example.test/docs//nested"}') == {
        "docs": "https://example.test/docs//nested"
    }
