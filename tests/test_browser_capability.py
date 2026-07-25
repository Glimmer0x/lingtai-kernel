"""Hermetic browser capability and real-Agent integration tests."""
from __future__ import annotations

from dataclasses import dataclass

from lingtai.agent import Agent
from lingtai.tools.browser import get_schema
from lingtai.tools.browser.core import BrowserEngine
from lingtai.tools.browser.port import ResolvedTarget, TransportResponse
from tests._service_helpers import make_gemini_mock_service


@dataclass
class FakeBrowserPort:
    body_by_url: dict[str, bytes]

    def __post_init__(self):
        self.calls: list[tuple[str, ResolvedTarget]] = []

    def resolve(self, hostname: str, *, timeout_s: float):
        return ("93.184.216.34",)

    def request(self, url: str, *, resolved: ResolvedTarget, max_bytes: int, timeout_s: float):
        self.calls.append((url, resolved))
        body = self.body_by_url.get(
            url,
            b"<html><body><p>linked page</p></body></html>",
        )
        return TransportResponse(
            status=200,
            headers={"Content-Type": "text/html; charset=utf-8"},
            body=body,
            truncated=False,
            url=url,
        )


def test_browser_browse_vertical_slice(tmp_path):
    port = FakeBrowserPort(
        {
            "https://public.example/page": (
                b"<html><head><title>Example</title></head><body>"
                b"<h1>Heading</h1><p>First paragraph with enough text.</p>"
                b"<p><a href='/next'>Next page</a></p></body></html>"
            ),
            "https://public.example/next": b"<html><body><p>Next page text</p></body></html>",
        }
    )
    agent = Agent(
        service=make_gemini_mock_service(),
        agent_name="browser-vertical-slice",
        working_dir=tmp_path,
        capabilities={"browser": {"browser_port": port}},
        disable=[
            "knowledge", "skills", "shell", "avatar", "daemon", "mcp",
            "read", "write", "edit", "glob", "grep", "vision", "web_search",
        ],
    )
    try:
        assert "browser" in agent._tool_handlers
        schemas = agent._build_tool_schemas()
        browser_schema = next(schema for schema in schemas if schema.name == "browser")
        assert set(browser_schema.parameters["properties"]) == set(get_schema()["properties"]) | {"reasoning"}
        first = agent._tool_handlers["browser"](
            {"url": "https://public.example/page", "max_chars": 18}
        )
        assert first["status"] == "ok"
        assert first["source_sha256"]
        assert first["snapshot_id"]
        assert first["requested_url"] == "https://public.example/page"
        assert first["final_url"] == "https://public.example/page"
        assert first["untrusted_content"] is True
        assert first["next_cursor"]
        calls_after_first = len(port.calls)

        second = agent._tool_handlers["browser"](
            {
                "url": "https://public.example/page",
                "cursor": first["next_cursor"],
                "max_chars": 18,
            }
        )
        assert second["status"] == "ok"
        assert second["timings_ms"] == {}
        assert len(port.calls) == calls_after_first
        first_ids = {block["id"] for block in first["blocks"]}
        second_ids = {block["id"] for block in second["blocks"]}
        assert first_ids.isdisjoint(second_ids)

        link_ref = first["links"][0]["ref"]
        followed = agent._tool_handlers["browser"]({"link_ref": link_ref})
        assert followed["status"] == "ok"
        assert followed["requested_url"] == "https://public.example/next"

        manual = agent._tool_handlers["browser"]({"action": "manual", "url": "not-used"})
        assert manual["status"] == "ok"
        assert manual["action"] == "manual"
        assert len(port.calls) == calls_after_first + 1
    finally:
        agent.stop(timeout=1.0)


def test_browser_real_agent_startup_and_complete_prompt_build(tmp_path):
    agent = Agent(
        service=make_gemini_mock_service(),
        agent_name="browser-startup-gate",
        working_dir=tmp_path,
        capabilities={"browser": {}},
        disable=[
            "knowledge", "skills", "shell", "avatar", "daemon", "mcp",
            "read", "write", "edit", "glob", "grep", "vision", "web_search",
        ],
    )
    try:
        agent.start()
        prompt = agent._build_system_prompt()
        batches = agent._build_system_prompt_batches()
        schemas = agent._build_tool_schemas()
        assert "### browser" in prompt
        assert "browser" in {schema.name for schema in schemas}
        assert "browser" in "\\n\\n".join(batches)
    finally:
        agent.stop(timeout=1.0)


def test_browser_policy_and_cursor_failures_are_typed_and_sanitized():
    port = FakeBrowserPort({"https://public.example/page": b"<p>content</p>"})
    engine = BrowserEngine(port)
    unsafe = engine.handle({"url": "http://127.0.0.1/admin"})
    assert unsafe["status"] == "failed"
    assert unsafe["error_code"] == "LOOPBACK_BLOCKED"
    assert "127.0.0.1" not in unsafe["message"]
    assert not port.calls
    malformed = engine.handle({"url": "https://user:password@public.example/page"})
    assert malformed["error_code"] == "URL_USERINFO_FORBIDDEN"
    stale = engine.handle({"url": "https://public.example/page", "cursor": "broken"})
    assert stale["error_code"] == "CURSOR_MALFORMED"


def test_browser_schema_is_browse_manual_only():
    schema = get_schema()
    assert schema["properties"]["action"]["enum"] == ["browse", "manual"]
    assert "search" not in schema["properties"]
    assert schema["properties"]["extract"]["enum"] == ["article"]
    assert schema["required"] == []
