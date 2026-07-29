"""Anthropic web search — uses Claude's native web_search tool."""
from __future__ import annotations

from lingtai.kernel.logging import get_logger

from . import SearchProviderError, SearchResult, SearchService

logger = get_logger()


class AnthropicSearchError(SearchProviderError):
    """The canonical Anthropic web search request failed.

    Raised both for an SDK/HTTP-level failure (connection error, rate limit,
    auth error, ...) and for an official HTTP-200 in-body
    ``web_search_tool_result_error`` (Anthropic's web search tool can
    legally fail while the overall API response still succeeds — evidence
    doc: "the Claude API still returns a 200 (success) response"). Carries
    only the bounded failure class/error code, never raw exception text,
    request bodies, or encrypted result content.
    """

    def __init__(self, failure_class: str) -> None:
        super().__init__("anthropic", failure_class)


class AnthropicSearchService(SearchService):
    """Web search via Anthropic's native web_search_20250305 tool.

    Sends a one-shot request with the web search tool enabled and extracts
    official per-source citation URLs from the response.

    Args:
        api_key: Anthropic API key.
        model: Model to use (default ``claude-sonnet-4-20250514``).
    """

    def __init__(self, api_key: str, *, model: str = "claude-sonnet-4-20250514") -> None:
        self._api_key = api_key
        self._model = model

    def search(self, query: str, max_results: int | None = 5) -> list[SearchResult]:
        import anthropic

        client = anthropic.Anthropic(api_key=self._api_key)
        web_search_tool: dict = {
            "type": "web_search_20250305",
            "name": "web_search",
        }
        if max_results is not None:
            web_search_tool["max_uses"] = max_results
        try:
            raw = client.messages.create(
                model=self._model,
                max_tokens=4096,
                messages=[{"role": "user", "content": query}],
                tools=[web_search_tool],
            )
        except Exception as e:
            logger.warning("Anthropic web search failed: %s", type(e).__name__)
            raise AnthropicSearchError(type(e).__name__) from e

        return _extract_results(raw, max_results)


def _extract_results(raw: object, max_results: int) -> list[SearchResult]:
    # Official response shape (evidence doc: content blocks of type
    # "web_search_tool_result" carry nested "web_search_result" items with
    # real url/title on success, or a *single* "web_search_tool_result_error"
    # object (not a list) with an "error_code" on failure — "On an error,
    # content is a single error object rather than a list of result blocks."
    # "text" blocks carry a "citations" list of "web_search_result_location"
    # entries with url/title/cited_text. Prefer text citations first since
    # they're tied to the actual generated narrative.
    results: list[SearchResult] = []
    seen_urls: set[str] = set()
    text_parts: list[str] = []
    content = getattr(raw, "content", None) or []

    for block in content:
        block_type = getattr(block, "type", None)
        if block_type == "text":
            text = getattr(block, "text", None) or ""
            text_parts.append(text)
            for citation in getattr(block, "citations", None) or []:
                if getattr(citation, "type", None) != "web_search_result_location":
                    continue
                url = getattr(citation, "url", None)
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                title = getattr(citation, "title", None) or "Anthropic Web Search"
                snippet = getattr(citation, "cited_text", None) or ""
                results.append(SearchResult(title=title, url=url, snippet=snippet))
                if len(results) >= max_results:
                    return results
        elif block_type == "web_search_tool_result":
            tool_content = getattr(block, "content", None)
            if getattr(tool_content, "type", None) == "web_search_tool_result_error":
                # The web search tool itself failed inside an HTTP-200
                # response; a bounded, secret-free error code only, never
                # the raw block or any other response content.
                error_code = getattr(tool_content, "error_code", None) or "unknown"
                raise AnthropicSearchError(f"web_search_tool_result_error:{error_code}")
            for item in tool_content or []:
                if getattr(item, "type", None) != "web_search_result":
                    continue
                url = getattr(item, "url", None)
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                title = getattr(item, "title", None) or "Anthropic Web Search"
                results.append(SearchResult(title=title, url=url, snippet=""))
                if len(results) >= max_results:
                    return results

    if results:
        return results

    # No structured citation/result blocks were present, but the official
    # API can still legally return a nonempty search-grounded narrative with
    # no URL. Preserve exactly one bounded narrative result rather than
    # silently discarding real output — never fabricate a link_ref for it.
    text = "\n".join(part for part in text_parts if part)
    if not text:
        return []
    return [SearchResult(title="Anthropic Web Search", url="", snippet=text)]
