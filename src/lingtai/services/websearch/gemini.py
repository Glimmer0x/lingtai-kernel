"""Gemini web search — uses Google Search grounding via google-genai."""
from __future__ import annotations

from lingtai.kernel.logging import get_logger

from . import SearchProviderError, SearchResult, SearchService

logger = get_logger()


class GeminiSearchError(SearchProviderError):
    """The canonical Gemini Google Search grounding request failed.

    Carries only the bounded ``google.genai.errors.APIError`` (or other SDK
    exception) class name, never raw exception text, request bodies, or
    credentials.
    """

    def __init__(self, failure_class: str) -> None:
        super().__init__("gemini", failure_class)


class GeminiSearchService(SearchService):
    """Web search via Gemini's Google Search grounding.

    Sends a one-shot generate_content call with the Google Search tool
    enabled and extracts official grounding source URLs from the response.

    Args:
        api_key: Google AI / Gemini API key.
        model: Model to use (default ``gemini-3-flash-preview``).
    """

    def __init__(self, api_key: str, *, model: str = "gemini-3-flash-preview") -> None:
        self._api_key = api_key
        self._model = model

    def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=self._api_key)
        try:
            gen_config = types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())],
            )
            raw = client.models.generate_content(
                model=self._model,
                contents=query,
                config=gen_config,
            )
        except Exception as e:
            logger.warning("Gemini web search failed: %s", type(e).__name__)
            raise GeminiSearchError(type(e).__name__) from e

        return _extract_results(raw, max_results)


def _extract_results(raw: object, max_results: int) -> list[SearchResult]:
    # Official grounding-metadata shape, verified 2026-07-28 read-only
    # against the already-installed google-genai 2.10.0 package source
    # (site-packages/google/genai/types.py): Candidate.grounding_metadata:
    # Optional[GroundingMetadata] (types.py:7745);
    # GroundingMetadata.grounding_chunks: Optional[list[GroundingChunk]]
    # (types.py:7416); GroundingChunk.web: Optional[GroundingChunkWeb]
    # (types.py:7178); GroundingChunkWeb.uri/.title: Optional[str]
    # (types.py:7123-7129). Defensive getattr at every level regardless:
    # grounding_metadata/grounding_chunks/chunk.web can each be None when the
    # model answered without actually invoking search this turn, even with
    # the tool enabled — that is documented, not merely defensive paranoia.
    text_parts: list[str] = []
    candidates = getattr(raw, "candidates", None) or []
    if candidates:
        content = getattr(candidates[0], "content", None)
        for part in getattr(content, "parts", None) or []:
            if getattr(part, "text", None) and not getattr(part, "thought", False):
                text_parts.append(part.text)

    results: list[SearchResult] = []
    seen_urls: set[str] = set()
    if candidates:
        grounding_metadata = getattr(candidates[0], "grounding_metadata", None)
        chunks = getattr(grounding_metadata, "grounding_chunks", None) or []
        for chunk in chunks:
            web = getattr(chunk, "web", None)
            if web is None:
                continue
            url = getattr(web, "uri", None)
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            title = getattr(web, "title", None) or "Gemini Web Search"
            results.append(SearchResult(title=title, url=url, snippet=""))
            if len(results) >= max_results:
                return results

    if results:
        return results

    # No structured grounding chunks were present, but the official API can
    # still legally return a nonempty search-grounded narrative with no URL.
    # Preserve exactly one bounded narrative result rather than silently
    # discarding real output — never fabricate a link_ref for it.
    text = "\n".join(text_parts)
    if not text:
        return []
    return [SearchResult(title="Gemini Web Search", url="", snippet=text)]
