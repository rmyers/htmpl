"""
Tests for htmpl core functionality.
"""

import pytest
from htmpl import html, SafeHTML, raw, attr, cached, cached_lru, cached_ttl


class TestSafeHTML:
    def test_content(self):
        s = SafeHTML("<p>hello</p>")
        assert s.content == "<p>hello</p>"
        assert s.__html__() == "<p>hello</p>"
        assert str(s) == "<p>hello</p>"

    def test_bool(self):
        assert bool(SafeHTML("content")) is True
        assert bool(SafeHTML("")) is False

    def test_add_safe(self):
        a = SafeHTML("<p>")
        b = SafeHTML("</p>")
        assert (a + b).content == "<p></p>"

    def test_add_unsafe_escapes(self):
        a = SafeHTML("<p>")
        result = a + "<script>"
        assert result.content == "<p>&lt;script&gt;"

    def test_radd(self):
        b = SafeHTML("</p>")
        result = "<p>" + b
        assert result.content == "&lt;p&gt;</p>"

    def test_hashable(self):
        s = SafeHTML("test")
        d = {s: "value"}
        assert d[SafeHTML("test")] == "value"


class TestRaw:
    def test_raw_passes_through(self):
        result = raw("<script>alert('hi')</script>")
        assert result.content == "<script>alert('hi')</script>"


class TestAttr:
    def test_attr_with_string(self):
        result = attr("class", "my-class")
        assert result.content == 'class="my-class"'

    def test_attr_escapes_value(self):
        result = attr("title", 'Say "hello"')
        assert result.content == 'title="Say &quot;hello&quot;"'

    def test_attr_with_none(self):
        result = attr("disabled", None)
        assert result.content == ""

    def test_attr_with_false(self):
        result = attr("hidden", False)
        assert result.content == ""

    def test_attr_with_true(self):
        result = attr("disabled", True)
        assert result.content == "disabled"

    def test_attr_xss_prevention(self):
        result = attr("onclick", '"><script>alert(1)</script><a x="')
        assert "<script>" not in result.content
        assert "&quot;" in result.content

    @pytest.mark.asyncio
    async def test_attr_in_template(self):
        active = True
        result = await html(t"<a {attr('aria-current', 'page' if active else None)}>Link</a>")
        assert 'aria-current="page"' in result.content

    @pytest.mark.asyncio
    async def test_attr_none_in_template(self):
        active = False
        result = await html(
            t'<a href="/" {attr("aria-current", "page" if active else None)}>Link</a>'
        )
        assert "aria-current" not in result.content


class TestHtmlBasic:
    @pytest.mark.asyncio
    async def test_static_template(self):
        result = await html(t"<p>hello</p>")
        assert result.content == "<p>hello</p>"

    @pytest.mark.asyncio
    async def test_escapes_strings(self):
        user_input = "<script>alert('xss')</script>"
        result = await html(t"<p>{user_input}</p>")
        assert "<script>" not in result.content
        assert "&lt;script&gt;" in result.content

    @pytest.mark.asyncio
    async def test_safe_html_not_escaped(self):
        trusted = SafeHTML("<strong>bold</strong>")
        result = await html(t"<p>{trusted}</p>")
        assert result.content == "<p><strong>bold</strong></p>"

    @pytest.mark.asyncio
    async def test_none_renders_empty(self):
        value = None
        result = await html(t"<p>{value}</p>")
        assert result.content == "<p></p>"

    @pytest.mark.asyncio
    async def test_nested_templates(self):
        inner = t"<span>inner</span>"
        result = await html(t"<div>{inner}</div>")
        assert result.content == "<div><span>inner</span></div>"


class TestHtmlLists:
    @pytest.mark.asyncio
    async def test_list_flattens(self):
        items = ["one", "two", "three"]
        result = await html(t"<ul>{[t'<li>{i}</li>' for i in items]}</ul>")
        assert result.content == "<ul><li>one</li><li>two</li><li>three</li></ul>"

    @pytest.mark.asyncio
    async def test_list_escapes_items(self):
        items = ["<script>", "normal"]
        result = await html(t"{items}")
        assert "&lt;script&gt;" in result.content
        assert "normal" in result.content

    @pytest.mark.asyncio
    async def test_empty_list(self):
        items = []
        result = await html(t"<ul>{items}</ul>")
        assert result.content == "<ul></ul>"

    @pytest.mark.asyncio
    async def test_list_with_none_items(self):
        items = ["a", None, "b"]
        result = await html(t"{items}")
        assert result.content == "ab"


class TestHtmlAsync:
    @pytest.mark.asyncio
    async def test_awaits_coroutines(self):
        async def get_name():
            return "Alice"

        result = await html(t"<p>Hello, {get_name()}!</p>")
        assert result.content == "<p>Hello, Alice!</p>"

    @pytest.mark.asyncio
    async def test_awaits_coroutines_in_list(self):
        async def make_item(n: int):
            return await html(t"<li>{n}</li>")

        result = await html(t"<ul>{[make_item(i) for i in range(3)]}</ul>")
        assert result.content == "<ul><li>0</li><li>1</li><li>2</li></ul>"

    @pytest.mark.asyncio
    async def test_async_generator(self):
        async def gen_items():
            for i in range(3):
                yield await html(t"<li>{i}</li>")

        result = await html(t"<ul>{gen_items()}</ul>")
        assert result.content == "<ul><li>0</li><li>1</li><li>2</li></ul>"

    @pytest.mark.asyncio
    async def test_coroutine_returning_none(self):
        async def maybe_content(show: bool):
            if not show:
                return None
            return await html(t"<p>shown</p>")

        result = await html(t"<div>{maybe_content(False)}</div>")
        assert result.content == "<div></div>"

        result = await html(t"<div>{maybe_content(True)}</div>")
        assert result.content == "<div><p>shown</p></div>"


class TestHtmlFormatting:
    @pytest.mark.asyncio
    async def test_format_spec(self):
        value = 1234.5678
        result = await html(t"<p>{value:.2f}</p>")
        assert result.content == "<p>1234.57</p>"

    @pytest.mark.asyncio
    async def test_format_spec_thousands(self):
        value = 1000000
        result = await html(t"<p>{value:,}</p>")
        assert result.content == "<p>1,000,000</p>"

    @pytest.mark.asyncio
    async def test_conversion_repr(self):
        value = "test"
        result = await html(t"<p>{value!r}</p>")
        assert result.content == "<p>&#x27;test&#x27;</p>"

    @pytest.mark.asyncio
    async def test_conversion_str(self):
        value = 42
        result = await html(t"<p>{value!s}</p>")
        assert result.content == "<p>42</p>"


class TestRenderable:
    @pytest.mark.asyncio
    async def test_custom_renderable(self):
        class Icon:
            def __init__(self, name: str):
                self.name = name

            def __html__(self) -> str:
                return f'<i class="icon-{self.name}"></i>'

        icon = Icon("star")
        result = await html(t"<button>{icon} Save</button>")
        assert result.content == '<button><i class="icon-star"></i> Save</button>'

    @pytest.mark.asyncio
    async def test_async_renderable(self):
        class AsyncWidget:
            async def __html__(self) -> str:
                return "<div>async widget</div>"

        widget = AsyncWidget()
        result = await html(t"<main>{widget}</main>")
        assert result.content == "<main><div>async widget</div></main>"


class TestCaching:
    @pytest.mark.asyncio
    async def test_cached_decorator(self):
        call_count = 0

        @cached
        async def expensive_component(name: str) -> SafeHTML:
            nonlocal call_count
            call_count += 1
            return await html(t"<p>{name}</p>")

        await expensive_component("test")
        await expensive_component("test")
        await expensive_component("test")

        assert call_count == 1

        await expensive_component("other")
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_cached_lru_eviction(self):
        call_count = 0

        @cached_lru(maxsize=2)
        async def component(n: int) -> SafeHTML:
            nonlocal call_count
            call_count += 1
            return await html(t"<p>{n}</p>")

        await component(1)
        await component(2)
        await component(3)  # evicts 1
        await component(1)  # cache miss

        assert call_count == 4

    @pytest.mark.asyncio
    async def test_cached_ttl_expiration(self):
        import time

        call_count = 0

        @cached_ttl(seconds=0)  # expires immediately
        async def component() -> SafeHTML:
            nonlocal call_count
            call_count += 1
            return await html(t"<p>content</p>")

        await component()
        time.sleep(0.01)
        await component()

        assert call_count == 2

    @pytest.mark.asyncio
    async def test_cache_clear(self):
        call_count = 0

        @cached
        async def component() -> SafeHTML:
            nonlocal call_count
            call_count += 1
            return await html(t"<p>test</p>")

        await component()
        await component()
        assert call_count == 1

        component.cache_clear()
        await component()
        assert call_count == 2
