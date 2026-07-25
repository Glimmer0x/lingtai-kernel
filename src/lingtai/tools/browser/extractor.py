"""Deterministic HTML/plain-text extraction for the static browse contract."""
from __future__ import annotations

import codecs
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
_CONTAINERS = {"div", "article", "section", "main", "body"}
_HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
_PARAGRAPHS = {"p", "blockquote", "dd", "dt", "figcaption", "th", "td"}
_SEMANTIC_KINDS = {
    **{tag: "heading" for tag in _HEADINGS},
    "pre": "code",
    **{tag: "paragraph" for tag in _PARAGRAPHS},
    "li": "list_item",
}


@dataclass
class _Frame:
    tag: str
    kind: str
    parts: list[str]


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


class _Parser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.title_parts: list[str] = []
        self.in_title = False
        self.skip_depth = 0
        self._skip_tags: list[str] = []
        self.blocks: list[tuple[str, str]] = []
        # Every block-ish element shares one ordered stack.  This prevents a
        # semantic frame and a nested container from collecting each other's
        # text out of DOM order.
        self._frames: list[_Frame] = [_Frame("__root__", "paragraph", [])]
        self._link: dict[str, object] | None = None
        self.links: list[ExtractedLink] = []

    def _append_visible(self, data: str) -> None:
        self._frames[-1].parts.append(data)

    def _flush_frame(self, frame: _Frame) -> None:
        parts = "".join(frame.parts)
        frame.parts.clear()
        text = parts.strip("\n") if frame.tag == "pre" else _clean(parts)
        if text:
            self.blocks.append((frame.kind, text))

    def _push_frame(self, tag: str, kind: str) -> None:
        # A frame owns direct text only.  Flush it before descending so text
        # before and after a child is emitted as separate ordered blocks.
        self._flush_frame(self._frames[-1])
        self._frames.append(_Frame(tag, kind, []))

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_map = dict(attrs)
        # Preserve the useful document title even though other <head> text is
        # skipped; title is metadata, not a visible page block. A title inside
        # a truly skipped element must remain skipped (for example, a script
        # containing a literal <title> tag).
        if tag in _SKIP:
            self._skip_tags.append(tag)
            self.skip_depth += 1
            return
        if self.skip_depth:
            if tag == "title" and self._skip_tags[-1] == "head":
                self.in_title = True
            return
        if tag == "title":
            self.in_title = True
            return
        if tag == "a":
            self._link = {"href": attrs_map.get("href"), "parts": []}
        if tag in _CONTAINERS:
            self._push_frame(tag, "paragraph")
            return
        kind = _SEMANTIC_KINDS.get(tag)
        if kind is not None:
            self._push_frame(tag, kind)
        elif tag == "br":
            self._append_visible("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self.in_title = False
            return
        if tag in _SKIP:
            self.skip_depth = max(0, self.skip_depth - 1)
            if self._skip_tags:
                self._skip_tags.pop()
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
        if len(self._frames) > 1 and self._frames[-1].tag == tag:
            frame = self._frames.pop()
            self._flush_frame(frame)

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title_parts.append(data)
            return
        if self.skip_depth:
            return
        if self._link is not None:
            self._link["parts"].append(data)  # type: ignore[union-attr]
        self._append_visible(data)

    def finish(self) -> None:
        while len(self._frames) > 1:
            frame = self._frames.pop()
            self._flush_frame(frame)
        self._flush_frame(self._frames[0])


def _decode(body: bytes, charset: str | None) -> tuple[str, list[str]]:
    warnings: list[str] = []
    encoding = charset or "utf-8"
    if charset:
        try:
            codecs.lookup(charset)
        except (LookupError, TypeError):
            warnings.append("UNSUPPORTED_CHARSET_FALLBACK")
            return body.decode("utf-8", errors="replace"), warnings
        try:
            return body.decode(encoding), warnings
        except UnicodeDecodeError:
            warnings.append("CHARSET_DECODE_ERROR_REPLACED")
            # Preserve the declared codec when replacing malformed sequences;
            # do not reinterpret a supported non-UTF-8 document as UTF-8.
            return body.decode(encoding, errors="replace"), warnings
        except (LookupError, TypeError):
            # ``codecs.lookup`` also exposes non-text codecs (for example
            # ``base64_codec``), which bytes.decode cannot use.
            warnings.append("UNSUPPORTED_CHARSET_FALLBACK")
            return body.decode("utf-8", errors="replace"), warnings
    try:
        return body.decode(encoding), warnings
    except UnicodeDecodeError:
        warnings.append("INVALID_UTF8_REPLACED")
        return body.decode("utf-8", errors="replace"), warnings


def _number_blocks(raw: list[tuple[str, str]]) -> list[Block]:
    return [Block(id=f"b{i:04d}", kind=kind, text=text) for i, (kind, text) in enumerate(raw, 1)]


def extract_html(body: bytes, *, base_url: str, charset: str | None = None) -> ExtractedDocument:
    text, warnings = _decode(body, charset)
    parser = _Parser(base_url)
    try:
        parser.feed(text)
        parser.close()
        parser.finish()
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


def extract_plain_text(body: bytes, charset: str | None = None) -> ExtractedDocument:
    text, warnings = _decode(body, charset)
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    if len(paragraphs) == 1 and "\n" in paragraphs[0]:
        paragraphs = [line.strip() for line in paragraphs[0].splitlines() if line.strip()]
    blocks = _number_blocks([("paragraph", _clean(part)) for part in paragraphs if _clean(part)])
    if not blocks:
        warnings.append("NO_TEXT_BLOCKS")
    return ExtractedDocument("", blocks, [], warnings)
