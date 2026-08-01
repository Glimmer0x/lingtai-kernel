"""Opt-in live Kimi Code provider/session/cache-identity test.

Run explicitly only when a configured Kimi route and paid-call authorization are
available:

    LINGTAI_RUN_LIVE_KIMI_CODE=1 PYTHONPATH=src python -m pytest \
        tests/integration_test_kimi_code.py -v

The test never treats stable output or a repeated session id as cached tokens;
it asserts the adapter's honest zero-usage contract.
"""

import os

import pytest

from lingtai.llm.kimi_code.adapter import KimiCodeAdapter


_KEY_ENV_NAMES = (
    "KIMI_MODEL_API_KEY",
    "KIMI_CODE_API_KEY",
    "KIMICODE_API_KEY",
    "KIMI_API_KEY",
    "MOONSHOT_API_KEY",
)


_LIVE_ENABLED = os.environ.get("LINGTAI_RUN_LIVE_KIMI_CODE") == "1"
_HAS_KEY = any(os.environ.get(name) for name in _KEY_ENV_NAMES)


@pytest.mark.skipif(
    not _LIVE_ENABLED or not _HAS_KEY,
    reason="set LINGTAI_RUN_LIVE_KIMI_CODE=1 with a configured Kimi key to run",
)
def test_live_kimi_session_identity_and_zero_unknown_usage(tmp_path):
    adapter = KimiCodeAdapter(
        model=os.environ.get("KIMI_MODEL_NAME") or "kimi-for-coding",
        cwd=tmp_path / "kimi-cwd",
    )
    session = adapter.create_chat(
        adapter._model,
        "Return one exact final answer. Never use native Kimi tools.",
        tools=None,
    )

    first = session.send("Return exactly KIMI_INTEGRATION_1.")
    first_id = session.kimi_session_id
    second = session.send("Return exactly KIMI_INTEGRATION_2.")
    second_id = session.kimi_session_id

    assert first.text == "KIMI_INTEGRATION_1"
    assert second.text == "KIMI_INTEGRATION_2"
    assert first_id and second_id == first_id
    assert first.raw["usage_source"] == "private_session_wire"
    assert second.raw["usage_source"] == "private_session_wire"
    assert first.raw["usage_records"] == 1
    assert second.raw["usage_records"] == 1
    assert first.usage.cached_tokens > 0
    assert second.usage.cached_tokens > 0
    assert first.usage.input_tokens >= first.usage.cached_tokens
    assert second.usage.input_tokens >= second.usage.cached_tokens
