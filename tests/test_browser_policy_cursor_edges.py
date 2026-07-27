"""Deterministic browser Core policy, redirect, cap and state edge cases."""
from __future__ import annotations

import gzip

from lingtai.tools.browser.core import BrowserEngine, _content_metadata
from lingtai.tools.browser.cursor import paginate_blocks
from lingtai.tools.browser.extractor import Block, extract_html, extract_plain_text
from lingtai.tools.browser.port import ResolvedTarget, TransportError, TransportResponse
from lingtai.tools.browser.refstore import RefStore
from lingtai.tools.browser.snapshots import InMemorySnapshotStore


class StaticTextPort:
    def __init__(self, body: bytes = b"first paragraph\n\nsecond paragraph"):
        self.body = body
        self.calls: list[str] = []

    def resolve(self, hostname: str, *, timeout_s: float):
        return ("93.184.216.34",)

    def request(self, url: str, *, resolved: ResolvedTarget, max_bytes: int, timeout_s: float):
        self.calls.append(url)
        return TransportResponse(200, {"Content-Type": "text/plain"}, self.body, False, url)


class RedirectPort:
    def __init__(self, redirect_to: str):
        self.redirect_to = redirect_to
        self.calls: list[str] = []

    def resolve(self, hostname: str, *, timeout_s: float):
        return ("93.184.216.34",)

    def request(self, url: str, *, resolved: ResolvedTarget, max_bytes: int, timeout_s: float):
        self.calls.append(url)
        if len(self.calls) == 1:
            return TransportResponse(302, {"Location": self.redirect_to}, b"", False, url)
        return TransportResponse(200, {"Content-Type": "text/plain"}, b"redirected", False, url)


def test_redirect_is_rechecked_before_second_port_call():
    port = RedirectPort("http://127.0.0.1/private")
    result = BrowserEngine(port).handle({"url": "https://public.example/start"})
    assert result["status"] == "failed"
    assert result["error_code"] == "LOOPBACK_BLOCKED"
    assert port.calls == ["https://public.example/start"]


def test_safe_redirect_preserves_requested_and_final_provenance():
    port = RedirectPort("https://public.example/final")
    result = BrowserEngine(port).handle({"url": "https://public.example/start"})
    assert result["status"] == "ok"
    assert result["requested_url"] == "https://public.example/start"
    assert result["final_url"] == "https://public.example/final"
    assert result["redirect_chain"] == ["https://public.example/start"]


def test_remaining_budget_fragments_large_block_after_small_prefix_losslessly():
    blocks = [Block("prefix", "paragraph", "abc"), Block("large", "paragraph", "0123456789")]
    pages = []
    page = paginate_blocks(blocks, start_index=0, max_chars=5)
    pages.append(page)
    assert [block.id for block in page.blocks] == ["prefix", "large#0"]
    assert [block.text for block in page.blocks] == ["abc", "01"]
    assert page.next_index == 1
    assert page.next_char_offset == 2
    assert sum(len(block.text) for block in page.blocks) == 5

    while page.has_more:
        page = paginate_blocks(
            blocks,
            start_index=page.next_index,
            start_char_offset=page.next_char_offset,
            max_chars=5,
        )
        pages.append(page)

    assert all(page.blocks for page in pages)
    assert [block.id for page in pages for block in page.blocks] == [
        "prefix",
        "large#0",
        "large#2",
        "large#7",
    ]
    assert "".join(block.text for page in pages for block in page.blocks) == "abc0123456789"
    assert all(sum(len(block.text) for block in page.blocks) <= 5 for page in pages)


def test_exact_fit_page_does_not_emit_empty_or_duplicate_fragment():
    blocks = [Block("prefix", "paragraph", "abcde"), Block("large", "paragraph", "0123456789")]
    first = paginate_blocks(blocks, start_index=0, max_chars=5)
    assert [block.id for block in first.blocks] == ["prefix"]
    assert first.next_index == 1
    assert first.next_char_offset == 0
    assert first.has_more is True

    second = paginate_blocks(
        blocks,
        start_index=first.next_index,
        start_char_offset=first.next_char_offset,
        max_chars=5,
    )
    third = paginate_blocks(
        blocks,
        start_index=second.next_index,
        start_char_offset=second.next_char_offset,
        max_chars=5,
    )
    fragments = [block for page in (first, second, third) for block in page.blocks]
    assert [block.id for block in fragments] == ["prefix", "large#0", "large#5"]
    assert all(block.text for block in fragments)
    assert "".join(block.text for block in fragments) == "abcde0123456789"
    assert all(sum(len(block.text) for block in page.blocks) <= 5 for page in (first, second, third))
    assert third.has_more is False


def test_output_cap_splits_blocks_without_overflow():
    class LongPort:
        def resolve(self, hostname: str, *, timeout_s: float):
            return ("93.184.216.34",)

        def request(self, url: str, *, resolved: ResolvedTarget, max_bytes: int, timeout_s: float):
            return TransportResponse(200, {"Content-Type": "text/plain"}, b"abcdefghijk", False, url)

    engine = BrowserEngine(LongPort())
    page = engine.handle({"url": "https://public.example/text", "max_chars": 3})
    assert page["status"] == "ok"
    assert page["returned_chars"] <= 3
    assert all(len(block["text"]) <= 3 for block in page["blocks"])
    assert page["next_cursor"]


def test_http_failures_are_typed_and_retryable_only_when_transient():
    class ErrorPort:
        def resolve(self, hostname: str, *, timeout_s: float):
            return ("93.184.216.34",)

        def request(self, url: str, *, resolved: ResolvedTarget, max_bytes: int, timeout_s: float):
            return TransportResponse(503, {}, b"", False, url)

    result = BrowserEngine(ErrorPort()).handle({"url": "https://public.example/down"})
    assert result["status"] == "failed"
    assert result["error_code"] == "HTTP_STATUS"
    assert result["retryable"] is True
    assert result["http_status"] == 503


def test_unsupported_content_preserves_known_http_status():
    class PdfPort:
        def resolve(self, hostname: str, *, timeout_s: float):
            return ("93.184.216.34",)

        def request(self, url: str, *, resolved: ResolvedTarget, max_bytes: int, timeout_s: float):
            return TransportResponse(200, {"Content-Type": "application/pdf"}, b"%PDF", False, url)

    result = BrowserEngine(PdfPort()).handle({"url": "https://public.example/report.pdf"})
    assert result["status"] == "failed"
    assert result["error_code"] == "CONTENT_TYPE_UNSUPPORTED"
    assert result["http_status"] == 200


def test_link_ref_eviction_is_loud_and_never_refetches():
    refs = RefStore(max_refs=1)
    first = refs.add_link_ref("https://public.example/one")
    refs.add_link_ref("https://public.example/two")
    assert refs.resolve_link_ref(first) is None


def test_dns_transport_error_preserves_stage_and_retryability():
    class DnsErrorPort:
        def resolve(self, hostname: str, *, timeout_s: float):
            raise TransportError("dns", "DNS_RESOLUTION_FAILED", retryable=True)

    result = BrowserEngine(DnsErrorPort()).handle({"url": "https://public.example/dns"})
    assert result["status"] == "failed"
    assert result["stage"] == "dns"
    assert result["error_code"] == "DNS_RESOLUTION_FAILED"
    assert result["retryable"] is True
    assert result["recommended_action"] != "Use a public, direct HTTP(S) URL; do not retry an unsafe destination."
    assert "unsafe destination" not in result["recommended_action"]


def test_bool_max_chars_is_rejected_before_fetch():
    port = StaticTextPort()
    result = BrowserEngine(port).handle({"url": "https://public.example/page", "max_chars": True})
    assert result["status"] == "failed"
    assert result["error_code"] == "INVALID_MAX_CHARS"
    assert port.calls == []


def test_cursor_hmac_tamper_is_rejected():
    port = StaticTextPort()
    engine = BrowserEngine(port)
    first = engine.handle({"url": "https://public.example/page", "max_chars": 3})
    assert first["next_cursor"]
    body, tag = first["next_cursor"].split(".", 1)
    tampered = body + "." + ("A" if tag[0] != "A" else "B") + tag[1:]
    result = engine.handle({"url": "https://public.example/page", "cursor": tampered, "max_chars": 3})
    assert result["status"] == "failed"
    assert result["error_code"] == "CURSOR_INVALID"
    assert len(port.calls) == 1


def test_cursor_target_mismatch_does_not_refetch_same_snapshot():
    port = StaticTextPort()
    engine = BrowserEngine(port)
    first = engine.handle({"url": "https://public.example/page", "max_chars": 3})
    result = engine.handle(
        {
            "url": "https://public.example/other",
            "cursor": first["next_cursor"],
            "max_chars": 3,
        }
    )
    assert result["status"] == "failed"
    assert result["error_code"] == "CURSOR_SNAPSHOT_MISMATCH"
    assert len(port.calls) == 1


def test_snapshot_eviction_returns_not_found_without_refetch():
    port = StaticTextPort()
    engine = BrowserEngine(port, snapshots=InMemorySnapshotStore(max_snapshots=1))
    first = engine.handle({"url": "https://public.example/one", "max_chars": 3})
    second = engine.handle({"url": "https://public.example/two", "max_chars": 3})
    assert second["status"] == "ok"
    calls_before_stale = len(port.calls)
    result = engine.handle(
        {
            "url": "https://public.example/one",
            "cursor": first["next_cursor"],
            "max_chars": 3,
        }
    )
    assert result["status"] == "failed"
    assert result["error_code"] == "CURSOR_SNAPSHOT_NOT_FOUND"
    assert len(port.calls) == calls_before_stale


def test_returned_links_have_fixed_aggregate_budget_and_full_ref_urls():
    links = "".join(
        f'<a href="/{"x" * 4000}{index}">{"t" * 600}</a>'
        for index in range(32)
    )

    class LongLinksPort:
        def __init__(self):
            self.calls: list[str] = []

        def resolve(self, hostname: str, *, timeout_s: float):
            return ("93.184.216.34",)

        def request(self, url: str, *, resolved: ResolvedTarget, max_bytes: int, timeout_s: float):
            self.calls.append(url)
            body = f"<html><body><p>content</p>{links}</body></html>".encode()
            return TransportResponse(200, {"Content-Type": "text/html"}, body, False, url)

    port = LongLinksPort()
    engine = BrowserEngine(port)
    result = engine.handle({"url": "https://public.example/page", "max_chars": 1})
    assert result["status"] == "ok"
    assert "LINKS_TRUNCATED" in result["warnings"]
    assert len(result["links"]) < 32
    assert sum(len(link["text"]) + len(link["url"]) for link in result["links"]) <= 24_000

    first = result["links"][0]
    followed = engine.handle({"link_ref": first["ref"]})
    assert followed["status"] == "ok"
    assert len(followed["requested_url"]) > len(first["url"])


def test_container_text_is_visible_once_in_dom_order_and_skips_noncontent():
    document = extract_html(
        b"""<html><body><main>before <div>container-before <section>nested <span>phrase</span></section> container-after</div>
        <h2>Heading <span>two</span></h2><p>Paragraph <span>visible</span></p>
        <ul><li>Item <span>one</span></li></ul><pre>code line</pre>
        <script>secret-script</script><nav>secret-nav</nav><footer>secret-footer</footer>
        </main></body></html>""",
        base_url="https://public.example/page",
    )
    texts = [block.text for block in document.blocks]
    joined = " | ".join(texts)
    for phrase in ("before", "container-before", "nested phrase", "container-after", "Heading two", "Paragraph visible", "Item one", "code line"):
        assert texts.count(phrase) == 1
    assert joined.index("container-before") < joined.index("nested phrase") < joined.index("container-after")
    assert "secret-script" not in joined
    assert "secret-nav" not in joined
    assert "secret-footer" not in joined
    assert {block.kind for block in document.blocks} >= {"heading", "paragraph", "list_item", "code"}

    title_document = extract_html(
        b"<head><title>visible title</title><script><title>secret title</title></script></head>"
        b"<body><p>body</p></body>",
        base_url="https://public.example/page",
    )
    assert title_document.title == "visible title"
    assert "secret title" not in title_document.title


def test_nested_block_frames_preserve_semantic_parent_dom_order():
    blockquote = extract_html(
        b"<blockquote>before<p>child</p>after</blockquote>",
        base_url="https://public.example/page",
    )
    assert [block.text for block in blockquote.blocks] == ["before", "child", "after"]
    assert [block.text for block in blockquote.blocks].count("child") == 1

    semantic_parent = extract_html(
        b"<h2>before<div>child</div>after</h2>",
        base_url="https://public.example/page",
    )
    assert [block.text for block in semantic_parent.blocks] == ["before", "child", "after"]
    assert [block.kind for block in semantic_parent.blocks] == ["heading", "paragraph", "heading"]


def test_declared_multibyte_charset_replaces_with_declared_codec():
    document = extract_plain_text(b"\x82\xa0\x82", charset="shift_jis")
    assert document.blocks[0].text == "\u3042\ufffd"
    assert document.warnings == ["CHARSET_DECODE_ERROR_REPLACED"]


def test_non_text_codec_alias_uses_utf8_replacement_fallback():
    document = extract_plain_text(b"caf\xff", charset="base64_codec")
    assert document.blocks[0].text == "caf\ufffd"
    assert document.warnings == ["UNSUPPORTED_CHARSET_FALLBACK"]


def test_declared_charset_and_safe_fallback_warnings_are_deterministic():
    html = extract_html("<main><p>caf\u00e9</p></main>".encode("iso-8859-1"), base_url="https://public.example", charset="iso-8859-1")
    assert html.blocks[0].text == "café"
    assert "UNSUPPORTED_CHARSET_FALLBACK" not in html.warnings
    unsupported = extract_plain_text(b"caf\xff", charset="not-a-real-codec")
    assert "UNSUPPORTED_CHARSET_FALLBACK" in unsupported.warnings
    assert "\ufffd" in unsupported.blocks[0].text
    media, charset, warnings = _content_metadata({"Content-Type": "text/plain; charset=\"bad name\""})
    assert (media, charset) == ("text/plain", None)
    assert warnings == ["MALFORMED_CHARSET_FALLBACK"]


def test_continuation_refreshes_all_snapshot_link_refs_after_eviction():
    class CursorLinksPort:
        def __init__(self):
            self.calls: list[str] = []

        def resolve(self, hostname: str, *, timeout_s: float):
            return ("93.184.216.34",)

        def request(self, url: str, *, resolved: ResolvedTarget, max_bytes: int, timeout_s: float):
            self.calls.append(url)
            body = (
                b"<html><body><p>abcdefghijk</p>"
                b"<a href='/one'>one</a><a href='/two'>two</a></body></html>"
            )
            return TransportResponse(200, {"Content-Type": "text/html"}, body, False, url)

    refs = RefStore(max_refs=2)
    port = CursorLinksPort()
    engine = BrowserEngine(port, refs=refs)
    first = engine.handle({"url": "https://public.example/page", "max_chars": 3})
    assert first["status"] == "ok"
    assert first["next_cursor"]
    assert len(first["links"]) == 2
    refs.add_link_ref("https://public.example/unrelated-1")
    refs.add_link_ref("https://public.example/unrelated-2")
    assert all(refs.resolve_link_ref(link["ref"]) is None for link in first["links"])

    continued = engine.handle(
        {
            "url": "https://public.example/page",
            "cursor": first["next_cursor"],
            "max_chars": 3,
        }
    )
    assert continued["status"] == "ok"
    assert len(port.calls) == 1
    assert all(refs.resolve_link_ref(link["ref"]) for link in continued["links"])
    for link in continued["links"]:
        followed = engine.handle({"link_ref": link["ref"]})
        assert followed["status"] == "ok"
        assert followed["requested_url"].endswith(("/one", "/two"))


class UndecodableBodyPort:
    """Serves a text/html 200 whose body is not decodable text.

    Reproduces the real ``python.org/downloads`` case: the origin answers an
    unnegotiated ``Content-Encoding: gzip`` while still labelling the payload
    ``text/html; charset=utf-8``, so Core receives compressed bytes.
    """

    def __init__(self, body: bytes, content_type: str = "text/html; charset=utf-8"):
        self.body = body
        self.content_type = content_type

    def resolve(self, hostname: str, *, timeout_s: float):
        return ("93.184.216.34",)

    def request(self, url: str, *, resolved: ResolvedTarget, max_bytes: int, timeout_s: float):
        return TransportResponse(200, {"Content-Type": self.content_type}, self.body, False, url)


def _gzipped_page() -> bytes:
    # Paragraphs vary so the compressed payload stays high-entropy and
    # realistically sized, like the real origin response.
    paragraphs = "".join(
        f"<p>Python 3.{n}.{n % 7} was released on day {n}; download artifact {n * 7919}.</p>"
        for n in range(400)
    )
    html = (
        "<html><head><title>Download Python</title></head><body>"
        f"<main>{paragraphs}</main></body></html>"
    ).encode("utf-8")
    return gzip.compress(html)


def test_compressed_binary_body_is_a_typed_extract_failure_not_nominal_success():
    """HTTP 200 whose extracted body is replacement garbage must not read as usable content."""
    engine = BrowserEngine(UndecodableBodyPort(_gzipped_page()))
    result = engine.handle({"url": "https://public.example/downloads/", "max_chars": 12_000})

    assert result["status"] == "failed"
    assert result["error_code"] == "NO_TEXT_BLOCKS"
    assert result["stage"] == "extract"
    # HTTP provenance survives the reclassification.
    assert result["http_status"] == 200
    assert result["retryable"] is False
    # The diagnosis names the real cause instead of blaming the URL, and the
    # recovery route is actionable.
    assert "not decodable text" in result["message"]
    assert "legacy extraction fallback" in result["recommended_action"]
    # No garbage may reach the model as ordinary page content.
    assert "blocks" not in result
    assert result["partial"] is False


def test_genuinely_empty_page_keeps_the_generic_no_text_diagnosis():
    """Only undecodable bodies get the decode-specific message and recovery."""
    engine = BrowserEngine(UndecodableBodyPort(b"<html><body><nav>menu</nav></body></html>"))
    result = engine.handle({"url": "https://public.example/empty"})
    assert result["status"] == "failed"
    assert result["error_code"] == "NO_TEXT_BLOCKS"
    assert result["message"] == "The page contained no static text blocks."
    assert "legacy extraction fallback" not in result["recommended_action"]


def test_undecodable_detection_requires_an_actual_decode_failure():
    """Cleanly decoded text is never reclassified, however unusual its characters."""
    dense_unicode = ("<main><p>" + "中文内容\U0001f600" * 400 + "</p></main>").encode("utf-8")
    engine = BrowserEngine(UndecodableBodyPort(dense_unicode))
    result = engine.handle({"url": "https://public.example/cjk", "max_chars": 12_000})
    assert result["status"] == "ok"
    assert result["blocks"]


def test_legitimate_partially_replaced_documents_stay_successful():
    """A mostly-readable document with a few bad bytes keeps its usable content."""
    body = ("café " * 200).encode("utf-8") + b"\xff\xfe"
    engine = BrowserEngine(UndecodableBodyPort(body, content_type="text/plain; charset=utf-8"))
    result = engine.handle({"url": "https://public.example/text", "max_chars": 12_000})
    assert result["status"] == "ok"
    assert "CHARSET_DECODE_ERROR_REPLACED" in result["warnings"]
    assert "café" in result["blocks"][0]["text"]

    # A short legitimately-truncated multibyte document is far too small to judge
    # by replacement density alone; it must survive.
    short = extract_plain_text(b"\x82\xa0\x82", charset="shift_jis")
    assert short.blocks[0].text == "あ�"
    assert "UNDECODABLE_CONTENT" not in short.warnings
