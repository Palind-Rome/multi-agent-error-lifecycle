"""Offline tests for the BrowseComp web tools (no network, no API key)."""

from __future__ import annotations

import unittest

from mas_error_lifecycle.adapters.browsecomp_tools import (
    WebToolError,
    _TextExtractor,
    fetch_url,
    tavily_search,
)


class TextExtractorTests(unittest.TestCase):
    def test_strips_script_style_title(self):
        extractor = _TextExtractor()
        extractor.feed(
            "<html><head><title>ignored</title><style>a{}</style></head>"
            "<body><p>Hello <b>world</b></p>"
            "<script>var x = 1;</script></body></html>"
        )
        self.assertIn("Hello", extractor.text())
        self.assertIn("world", extractor.text())
        self.assertNotIn("var x", extractor.text())
        self.assertNotIn("ignored", extractor.text())

    def test_nested_skip_tags(self):
        extractor = _TextExtractor()
        extractor.feed("<div>keep <span>this</span> <script>drop</script> tail</div>")
        text = extractor.text()
        self.assertIn("keep", text)
        self.assertIn("tail", text)
        self.assertNotIn("drop", text)


class WebToolGuardTests(unittest.TestCase):
    def test_tavily_rejects_empty_key(self):
        with self.assertRaises(WebToolError):
            tavily_search("", "query")

    def test_tavily_rejects_empty_query(self):
        with self.assertRaises(WebToolError):
            tavily_search("key", "   ")

    def test_fetch_rejects_non_http(self):
        with self.assertRaises(WebToolError):
            fetch_url("file:///etc/passwd")


if __name__ == "__main__":
    unittest.main()
