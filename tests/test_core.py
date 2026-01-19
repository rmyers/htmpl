"""
Tests for htmpl core functionality.
"""

import pytest
from htmpl import SafeHTML


class TestSafeHTML:
    def test_content(self):
        s = SafeHTML("<p>hello</p>")
        assert s.content == "<p>hello</p>"
        assert s.__html__() == "<p>hello</p>"
        assert str(s) == "<p>hello</p>"

    def test_bool(self):
        assert bool(SafeHTML("content")) is True
        assert bool(SafeHTML("")) is False

    def test_hashable(self):
        s = SafeHTML("test")
        d = {s: "value"}
        assert d[SafeHTML("test")] == "value"
