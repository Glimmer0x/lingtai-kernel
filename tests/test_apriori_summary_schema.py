"""The legacy a-priori ``summary`` boolean on unmigrated tool schemas.

``glob`` used to be covered here too. It is now an action of the migrated
``file`` family, whose canonical control is the root ``summarize`` boolean —
covered by ``tests/test_file_tool_family.py``, not by this legacy-flag test.
``daemon`` remains unmigrated and still carries the literal ``summary`` field.
"""
from __future__ import annotations

from lingtai.tools.daemon import get_schema as daemon_schema


def _assert_summary_option(schema: dict) -> None:
    prop = schema["properties"]["summary"]
    assert prop["type"] == "boolean"
    assert prop["default"] is False
    assert "raw result is preserved" in prop["description"]


def test_daemon_exposes_apriori_summary_option() -> None:
    _assert_summary_option(daemon_schema())
