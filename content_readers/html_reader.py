"""HTML reader: stdlib html.parser.HTMLParser only. HTMLParser tokenizes
tags/text -- it has no execution capability at all, so <script>/<style>
content is received here as plain text data (via handle_data) and is
explicitly excluded from the extracted text, never passed to exec/eval,
never rendered, never fetched.
"""
from __future__ import annotations

import sys
from html.parser import HTMLParser
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
from content_readers import interface  # noqa: E402


class _ExtractingParser(HTMLParser):
    def __init__(self, max_links: int):
        super().__init__(convert_charrefs=True)
        self._max_links = max_links
        self.title_parts = []
        self.text_parts = []
        self.links = []
        self._in_title = False
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip_depth += 1
        if tag == "title":
            self._in_title = True
        if tag == "a" and len(self.links) < self._max_links:
            href = dict(attrs).get("href")
            if href:
                self.links.append(href)

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip_depth > 0:
            self._skip_depth -= 1
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._skip_depth:
            return  # script/style body: received as inert text, never executed, never kept
        if self._in_title:
            self.title_parts.append(data)
        else:
            self.text_parts.append(data)


class HTMLReader:
    reader_id = "html_reader"
    reader_version = "1.0.0"

    def read(self, request: interface.ContentReadRequest) -> interface.ContentReadResult:
        try:
            text = request.data.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            return self._malformed(request, f"content is not valid UTF-8 text: {exc}")

        parser = _ExtractingParser(max_links=request.limits.max_links)
        try:
            parser.feed(text)
            parser.close()
        except Exception as exc:  # noqa: BLE001 -- HTMLParser is lenient; this is a last-resort guard
            return self._malformed(request, f"HTML could not be parsed: {exc}")

        title = "".join(parser.title_parts).strip()
        body_text = "".join(parser.text_parts).strip()
        bounded_text, truncated = _bounded(body_text, request.limits.max_output_chars)

        return interface.ContentReadResult(
            artifact_id=request.artifact_id, reader_id=self.reader_id, reader_version=self.reader_version,
            content_type="text/html", status=interface.READ_OK,
            structured_content={"title": title, "link_count": len(parser.links), "links": parser.links},
            text_content=bounded_text,
            metadata={
                "char_count": len(body_text),
                "note": "script/style content excluded from text_content; never executed, never rendered",
            },
            provenance_reference=request.artifact_id, warnings=(), errors=(),
            truncated=truncated,
            truncation_detail=(f"text_content bounded to max_output_chars={request.limits.max_output_chars}" if truncated else None),
            source_sha256=request.source_sha256,
        )

    def _malformed(self, request, detail):
        return interface.ContentReadResult(
            artifact_id=request.artifact_id, reader_id=self.reader_id, reader_version=self.reader_version,
            content_type="text/html", status=interface.READ_MALFORMED,
            structured_content=None, text_content=None, metadata={},
            provenance_reference=request.artifact_id, warnings=(), errors=(detail,),
            truncated=False, source_sha256=request.source_sha256,
        )


def _bounded(text: str, max_chars: int):
    if len(text) > max_chars:
        return text[:max_chars], True
    return text, False


interface.register_reader("text/html", HTMLReader())
