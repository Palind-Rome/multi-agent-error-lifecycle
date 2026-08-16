"""Web tools for the BrowseComp multi-agent pilot (stdlib only).

BrowseComp questions require web search + page reading. This module provides
the two tools the MAS agents need, with no third-party runtime dependencies:

* ``tavily_search`` — one query against the Tavily search API (the search
  backend the pilot uses; key supplied at runtime, never persisted).
* ``fetch_url`` — GET a URL and turn the HTML into readable text via stdlib
  ``html.parser``.

The API key is a plain argument and is never logged or persisted by this module.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from html.parser import HTMLParser
from typing import Any

TAVILY_ENDPOINT = "https://api.tavily.com/search"
DEFAULT_TIMEOUT_SECONDS = 20.0
USER_AGENT = "mas-error-lifecycle/0.3 browsecomp-pilot"


class _TextExtractor(HTMLParser):
    """Collect visible text, skipping script/style/noscript and link URLs."""

    _SKIP = {"script", "style", "noscript", "head", "title", "svg"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []
        self._depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._SKIP:
            self._depth += 1
        elif tag in {"p", "br", "li", "div", "h1", "h2", "h3", "tr"}:
            self._chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP:
            self._depth = max(0, self._depth - 1)

    def handle_data(self, data: str) -> None:
        if self._depth == 0 and data.strip():
            self._chunks.append(data)

    def text(self) -> str:
        return "\n".join(chunk.strip() for chunk in self._chunks if chunk.strip())


class WebToolError(RuntimeError):
    """Safe public error for a failed search or fetch (no secrets in args)."""


def tavily_search(api_key: str, query: str, max_results: int = 5) -> list[dict[str, Any]]:
    """Return ``[{title, url, content}, ...]`` for one Tavily search query."""
    if not api_key or not query.strip():
        raise WebToolError("tavily_search needs a non-empty api_key and query")
    payload = json.dumps(
        {
            "api_key": api_key,
            "query": query,
            "search_depth": "advanced",
            "max_results": max(1, min(int(max_results), 10)),
            "include_answer": False,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        TAVILY_ENDPOINT,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=DEFAULT_TIMEOUT_SECONDS) as response:
            body = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, json.JSONDecodeError, OSError) as exc:
        raise WebToolError(f"tavily_search failed: {type(exc).__name__}") from exc
    return [
        {
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "content": item.get("content", ""),
        }
        for item in body.get("results", [])
    ]


def fetch_url(url: str, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> str:
    """GET a URL and return its visible text (HTML stripped, truncated)."""
    if not url.startswith(("http://", "https://")):
        raise WebToolError("fetch_url only accepts http(s) URLs")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(2_000_000)
            content_type = response.headers.get("Content-Type", "")
    except (urllib.error.URLError, OSError) as exc:
        raise WebToolError(f"fetch_url failed: {type(exc).__name__}") from exc
    if "html" not in content_type.lower() and "text" not in content_type.lower():
        # Non-HTML (PDF, binary): return a short placeholder, not raw bytes.
        return f"[non-text content, {len(raw)} bytes, type={content_type or 'unknown'}]"
    extractor = _TextExtractor()
    try:
        extractor.feed(raw.decode("utf-8", errors="replace"))
    except Exception as exc:  # noqa: BLE001
        raise WebToolError(f"fetch_url parse failed: {type(exc).__name__}") from exc
    text = extractor.text()
    return text[:50_000]
