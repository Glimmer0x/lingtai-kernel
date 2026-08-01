"""Live end-to-end test for the claude-code provider against the real `claude` CLI.

Not collected by default (filename doesn't match ``test_*.py``). Run explicitly:

    PYTHONPATH=src python -m pytest tests/integration_test_claude_code.py -v

Requires the `claude` CLI installed and logged in with a Claude subscription.
"""

import shutil

import pytest

from lingtai.llm.claude_code.adapter import ClaudeCodeAdapter
from lingtai.llm.service import LLMService
from lingtai.kernel.llm.base import FunctionSchema

pytestmark = pytest.mark.skipif(
    shutil.which("claude") is None, reason="claude CLI not installed / not on PATH"
)


def _weather_tool():
    return FunctionSchema(
        name="get_weather",
        description="Get the current weather for a city.",
        parameters={
            "type": "object",
            "properties": {"city": {"type": "string"}},
            "required": ["city"],
        },
    )


def test_live_tool_call_then_final():
    ad = ClaudeCodeAdapter(model="sonnet")
    sess = ad.create_chat("sonnet", "You are Aria, a concise weather agent.", [_weather_tool()])

    r1 = sess.send("What's the weather in Paris right now?")
    assert r1.tool_calls, "expected a tool call"
    assert r1.tool_calls[0].name == "get_weather"
    assert r1.tool_calls[0].args.get("city", "").lower() == "paris"

    tc = r1.tool_calls[0]
    tr = ad.make_tool_result_message(tc.name, {"temp_c": 18, "conditions": "light rain"}, tool_call_id=tc.id)
    r2 = sess.send([tr])
    assert not r2.tool_calls
    assert "18" in r2.text or "rain" in r2.text.lower()


def test_live_service_path_keyless():
    svc = LLMService(provider="claude-code", model="sonnet", api_key=None)
    sess = svc.create_session(system_prompt="You are a concise assistant.", tools=[_weather_tool()])
    sess.update_system_prompt_batches(["You are a concise assistant.", "Be brief."])
    sess.update_tools([_weather_tool()])
    r = sess.send("Reply with exactly: READY")
    assert "READY" in r.text


def test_live_system_block_is_cache_read_across_growing_turns():
    """The prompt-cache contract: the stable system block must be cache-read
    on later turns even as the conversation grows.

    Before the ``--append-system-prompt-file`` split, the whole stable context
    was embedded in the per-turn user message, so a growing conversation forced
    a full cache write every turn (``cached_tokens`` stayed flat at Claude
    Code's own system-prompt size). With the split, the stable block lives in
    the cached system block, so ``cached_tokens`` must grow on turn 2 and stay
    stable on turn 3.
    """
    big_context = "\n".join(
        "Context line %d: the quick brown fox jumps over the lazy dog. "
        "This line makes the system prompt large enough to exceed Anthropic "
        "cache minimums. Lorem ipsum dolor sit amet consectetur adipiscing elit "
        "sed do eiusmod tempor incididunt ut labore et dolore magna aliqua." % i
        for i in range(120)
    )
    system_prompt = "You are a reasoning core under test.\n# SYSTEM CONTEXT\n" + big_context

    ad = ClaudeCodeAdapter(model="sonnet", timeout_s=120)
    sess = ad.create_chat("sonnet", system_prompt, None)

    r1 = sess.send("First question: say hello.")
    u1 = r1.usage
    r2 = sess.send("Second question: now say goodbye.")
    u2 = r2.usage
    r3 = sess.send("Third question: and now a number.")
    u3 = r3.usage

    assert u2.cached_tokens > u1.cached_tokens, (
        f"system block not cache-read on turn 2: t1={u1.cached_tokens} t2={u2.cached_tokens}"
    )
    assert u3.cached_tokens >= u2.cached_tokens, (
        f"cache regressed on turn 3: t2={u2.cached_tokens} t3={u3.cached_tokens}"
    )
