"""
Tests for htmpl core functionality.
"""

import pytest
from htmpl.core import SafeHTML, render
from tdom import Node

from htmpl.assets import Component, component

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


@component('custom-layout')
async def layout(children: list[Node], *, title="layout"):
    return t"<div><header>{title}</header>{children}</div>"


class TestRender:
    @pytest.fixture()
    def registry(self):
        return {
            'custom-layout': Component(name='custom-layout', fn=layout)
        }

    async def test_renders_html_properly(self, registry):
        result = await render(t'<custom-layout><p>IT WORKS!</p></custom-layout>', registry)
        assert result.body == b"<div><header>layout</header><p>IT WORKS!</p></div>"
