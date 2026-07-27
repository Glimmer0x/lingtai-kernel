"""ToolExecutor evidence for the migrated ``web`` family's canonical root
``summarize`` control (LTP v2).

Reuses the ``test_apriori_summary_executor.py`` harness shape. Proves, for a
tool call named ``web``:

* the raw result is durably logged BEFORE any visible summary replacement, on
  both the sequential and the controlled-parallel ToolExecutor paths;
* ``summarize=true`` on a ``status: failed`` web result stays byte/content
  exact and is never summarized.

The parallel-path test declares ``web`` parallel-safe only as a local test
fixture choice to exercise ``ToolExecutor``'s existing parallel code path; it
is not a claim about web's real registry parallel-safety, which this PR does
not change.
"""
from __future__ import annotations

from lingtai.kernel.llm.base import ToolCall
from lingtai.kernel.loop_guard import LoopGuard
from lingtai.kernel.tool_executor import ToolExecutor
from lingtai.kernel.tool_result_summary import APRIORI_SUMMARY_MARKER


def _make_executor(*, dispatch_fn, summarizer_fn, events, tmp_path, parallel_safe_tools=None):
    def logger_fn(event_type, **fields):
        events.append((event_type, fields))

    def make_tool_result_fn(name, result, **kw):
        return {"role": "tool", "name": name, "content": result, **kw}

    return ToolExecutor(
        dispatch_fn=dispatch_fn,
        make_tool_result_fn=make_tool_result_fn,
        guard=LoopGuard(),
        known_tools={"web"},
        parallel_safe_tools=parallel_safe_tools or set(),
        logger_fn=logger_fn,
        working_dir=tmp_path,
        summarizer_fn=summarizer_fn,
    )


def _wire_content(result_msg):
    return result_msg["content"]


def _raw_logged(events, *, needle):
    for event_type, fields in events:
        if event_type == "tool_result" and needle in str(fields.get("result")):
            return True
    return False


def test_web_summarize_true_sequential_raw_logged_before_summary(tmp_path):
    raw = {"status": "ok", "action": "search", "results": [], "query": "WEBRAW-marker"}
    events = []
    ex = _make_executor(
        dispatch_fn=lambda tc: raw,
        summarizer_fn=lambda sp, up, tn, cid: "SUMMARY: no results",
        events=events,
        tmp_path=tmp_path,
    )
    results, _, _ = ex.execute(
        [ToolCall(name="web", args={"action": "search", "input": {"query": "q"}, "summarize": True}, id="w1")]
    )
    content = _wire_content(results[0])
    assert content["artifact"] == APRIORI_SUMMARY_MARKER
    assert content["generated_summary"] == "SUMMARY: no results"
    assert "WEBRAW-marker" not in str(content)
    # The raw result was durably logged before the visible replacement.
    assert _raw_logged(events, needle="WEBRAW-marker")


def test_web_summarize_true_parallel_raw_logged_before_summary(tmp_path):
    raw_a = {"status": "ok", "action": "search", "results": [], "query": "WEBPARALLEL-a"}
    raw_b = {"status": "ok", "action": "browse", "blocks": [], "final_url": "WEBPARALLEL-b"}

    def dispatch(tc):
        return raw_a if tc.id == "wa" else raw_b

    events = []
    ex = _make_executor(
        dispatch_fn=dispatch,
        summarizer_fn=lambda sp, up, tn, cid: f"SUMMARY-for-{cid}",
        events=events,
        tmp_path=tmp_path,
        parallel_safe_tools={"web"},
    )
    results, _, _ = ex.execute([
        ToolCall(name="web", args={"action": "search", "input": {"query": "q"}, "summarize": True}, id="wa"),
        ToolCall(name="web", args={"action": "browse", "input": {
            "url": "https://example.test", "link_ref": None, "cursor": None,
            "extract": None, "max_chars": None,
        }, "summarize": True}, id="wb"),
    ])
    for content in [_wire_content(r) for r in results]:
        assert content["artifact"] == APRIORI_SUMMARY_MARKER
        assert "WEBPARALLEL" not in str(content)
    assert _raw_logged(events, needle="WEBPARALLEL-a")
    assert _raw_logged(events, needle="WEBPARALLEL-b")


def test_web_search_failed_status_with_summarize_true_stays_exact_and_unsummarized(tmp_path):
    raw = {
        "status": "failed", "action": "search", "error_code": "SEARCH_ENGINE_UNAVAILABLE",
        "message": "the selected search engine is unavailable", "current_setting": {"engine": None},
    }
    events = []
    ex = _make_executor(
        dispatch_fn=lambda tc: dict(raw),
        summarizer_fn=lambda sp, up, tn, cid: (_ for _ in ()).throw(AssertionError("must not summarize a failed result")),
        events=events,
        tmp_path=tmp_path,
    )
    results, _, _ = ex.execute(
        [ToolCall(name="web", args={"action": "search", "input": {"query": "q"}, "summarize": True}, id="wf")]
    )
    content = _wire_content(results[0])
    assert content["status"] == "failed"
    assert content["error_code"] == "SEARCH_ENGINE_UNAVAILABLE"
    assert content["message"] == raw["message"]
    assert content.get("artifact") != APRIORI_SUMMARY_MARKER


def test_web_browse_failed_status_with_summarize_true_stays_exact_and_unsummarized(tmp_path):
    raw = {
        "status": "failed", "action": "browse", "error_code": "BROWSE_FAILED",
        "message": "browse failed safely", "current_setting": {"engine": None},
    }
    events = []
    ex = _make_executor(
        dispatch_fn=lambda tc: dict(raw),
        summarizer_fn=lambda sp, up, tn, cid: (_ for _ in ()).throw(AssertionError("must not summarize a failed result")),
        events=events,
        tmp_path=tmp_path,
    )
    results, _, _ = ex.execute(
        [ToolCall(name="web", args={"action": "browse", "input": {
            "url": "https://example.test", "link_ref": None, "cursor": None,
            "extract": None, "max_chars": None,
        }, "summarize": True}, id="wf2")]
    )
    content = _wire_content(results[0])
    assert content["status"] == "failed"
    assert content["error_code"] == "BROWSE_FAILED"
    assert content["message"] == raw["message"]
    assert content.get("artifact") != APRIORI_SUMMARY_MARKER
