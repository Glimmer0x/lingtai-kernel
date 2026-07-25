"""Deterministic HTML/plain-text extraction for the static browse contract."""
from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from . import netpolicy


@dataclass(frozen=True, slots=True)
class Block:
    id: str
    kind: str
    text: str


@dataclass(frozen=True, slots=True)
class ExtractedLink:
    text: str
    url: str


@dataclass(frozen=True, slots=True)
class ExtractedDocument:
    title: str
    blocks: list[Block]
    links: list[ExtractedLink]
    warnings: list[str]


_SKIP = {"script", "style", "noscript", "nav", "footer", "aside", "svg", "template", "iframe", "head"}
_HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
_PARAGRAPHS = {"p", "blockquote", "dd", "dt", "figcaption", "th", "td"}


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


class _Parser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.title_parts: list[str] = []
        self.in_title = False
        self.skip_depth = 0
        self.blocks: list[tuple[str, str]] = []
        self._active: list[dict[str, object]] = []
        self._link: dict[str, object] | None = None
        self.links: list[ExtractedLink] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_map = dict(attrs)
        if tag == "title":
            self.in_title = True
            return
        if tag in _SKIP:
            self.skip_depth += 1
            return
        if self.skip_depth:
            return
        if tag == "a":
            self._link = {"href": attrs_map.get("href"), "parts": []}
        if tag in _HEADINGS:
            self._active.append({"kind": "heading", "tag": tag, "parts": []})
        elif tag == "pre":
            self._active.append({"kind": "code", "tag": tag, "parts": []})
        elif tag in _PARAGRAPHS:
            self._active.append({"kind": "paragraph", "tag": tag, "parts": []})
        elif tag == "li":
            self._active.append({"kind": "list_item", "tag": tag, "parts": []})
        elif tag == "br" and self._active:
            self._active[-1]["parts"].append("\n")  # type: ignore[union-attr]

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self.in_title = False
            return
        if tag in _SKIP:
            self.skip_depth = max(0, self.skip_depth - 1)
            return
        if self.skip_depth:
            return
        if tag == "a" and self._link is not None:
            href = self._link.get("href")
            text = _clean("".join(self._link["parts"]))  # type: ignore[arg-type]
            self._link = None
            if isinstance(href, str) and text:
                try:
                    candidate = netpolicy.resolved_url(self.base_url, href)
                    self.links.append(ExtractedLink(text, candidate))
                except (TypeError, ValueError, netpolicy.PolicyViolation):
                    pass
        if not self._active:
            return
        current = self._active[-1]
        if current["tag"] == tag:
            self._active.pop()
            parts = "".join(current["parts"])  # type: ignore[arg-type]
            text = parts.strip("\n") if current["kind"] == "code" else _clean(parts)
            if text:
                self.blocks.append((str(current["kind"]), text))

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title_parts.append(data)
            return
        if self.skip_depth:
            return
        if self._link is not None:
            self._link["parts"].append(data)  # type: ignore[union-attr]
        if self._active:
            self._active[-1]["parts"].append(data)  # type: ignore[union-attr]


def _number_blocks(raw: list[tuple[str, str]]) -> list[Block]:
    return [Block(id=f"b{i:04d}", kind=kind, text=text) for i, (kind, text) in enumerate(raw, 1)]


def extract_html(body: bytes, *, base_url: str) -> ExtractedDocument:
    warnings: list[str] = []
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        text = body.decode("utf-8", errors="replace")
        warnings.append("INVALID_UTF8_REPLACED")
    parser = _Parser(base_url)
    try:
        parser.feed(text)
        parser.close()
    except Exception:
        warnings.append("HTML_PARSE_RECOVERED")
    seen: set[tuple[str, str]] = set()
    links: list[ExtractedLink] = []
    for link in parser.links:
        key = (link.text, link.url)
        if key not in seen:
            seen.add(key)
            links.append(link)
    blocks = _number_blocks(parser.blocks)
    if not blocks:
        warnings.append("NO_TEXT_BLOCKS")
    return ExtractedDocument(_clean("".join(parser.title_parts)), blocks, links, warnings)


def extract_plain_text(body: bytes) -> ExtractedDocument:
    warnings: list[str] = []
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        text = body.decode("utf-8", errors="replace")
        warnings.append("INVALID_UTF8_REPLACED")
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    if len(paragraphs) == 1 and "\n" in paragraphs[0]:
        paragraphs = [line.strip() for line in paragraphs[0].splitlines() if line.strip()]
    blocks = _number_blocks([("paragraph", _clean(part)) for part in paragraphs if _clean(part)])
    if not blocks:
        warnings.append("NO_TEXT_BLOCKS")
    return ExtractedDocument("", blocks, [], warnings)
