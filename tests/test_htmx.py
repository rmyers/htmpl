"""
Tests for htmpl HTMX helpers.
"""

import pytest
from htmpl import html
from htmpl.htmx import (
    HX,
    HtmxScripts,
    HtmxExtension,
    LoadingButton,
    InfiniteScroll,
    LazyLoad,
    PollingContent,
    SearchInput,
    OobSwap,
)


class TestHXBuilder:
    def test_empty(self):
        hx = HX()
        assert str(hx) == ""

    def test_get(self):
        hx = HX(get="/api/data")
        assert str(hx) == 'hx-get="/api/data"'

    def test_post(self):
        hx = HX(post="/api/submit")
        assert str(hx) == 'hx-post="/api/submit"'

    def test_target_and_swap(self):
        hx = HX(get="/api", target="#results", swap="innerHTML")
        result = str(hx)
        assert 'hx-get="/api"' in result
        assert 'hx-target="#results"' in result
        assert 'hx-swap="innerHTML"' in result

    def test_trigger(self):
        hx = HX(get="/api", trigger="click, keyup")
        assert 'hx-trigger="click, keyup"' in str(hx)

    def test_push_url_bool(self):
        hx = HX(get="/page", push_url=True)
        assert 'hx-push-url="true"' in str(hx)

    def test_push_url_string(self):
        hx = HX(get="/page", push_url="/custom-url")
        assert 'hx-push-url="/custom-url"' in str(hx)

    def test_confirm(self):
        hx = HX(delete="/item/1", confirm="Are you sure?")
        assert 'hx-confirm="Are you sure?"' in str(hx)

    def test_boost(self):
        hx = HX(boost=True)
        assert 'hx-boost="true"' in str(hx)

    def test_indicator(self):
        hx = HX(post="/api", indicator="#spinner")
        assert 'hx-indicator="#spinner"' in str(hx)

    def test_disabled_elt(self):
        hx = HX(post="/api", disabled_elt="this")
        assert 'hx-disabled-elt="this"' in str(hx)

    def test_select(self):
        hx = HX(get="/page", select="#content")
        assert 'hx-select="#content"' in str(hx)

    def test_swap_oob(self):
        hx = HX(swap_oob="true")
        assert 'hx-swap-oob="true"' in str(hx)

    def test_vals(self):
        hx = HX(post="/api", vals='{"key": "value"}')
        assert 'hx-vals="{"key": "value"}"' in str(hx)

    def test_include(self):
        hx = HX(post="/api", include="[name='token']")
        assert "hx-include=\"[name='token']\"" in str(hx)

    def test_params(self):
        hx = HX(get="/api", params="*")
        assert 'hx-params="*"' in str(hx)

    def test_sync(self):
        hx = HX(get="/api", sync="closest form:abort")
        assert 'hx-sync="closest form:abort"' in str(hx)

    def test_preserve(self):
        hx = HX(preserve=True)
        assert 'hx-preserve="true"' in str(hx)

    def test_ext(self):
        hx = HX(ext="json-enc")
        assert 'hx-ext="json-enc"' in str(hx)

    def test_headers(self):
        hx = HX(headers='{"X-Custom": "value"}')
        assert 'hx-headers="{"X-Custom": "value"}"' in str(hx)

    def test_history(self):
        hx = HX(history=False)
        assert 'hx-history="false"' in str(hx)

    def test_history_elt(self):
        hx = HX(history_elt=True)
        assert "hx-history-elt" in str(hx)

    def test_on_events(self):
        hx = HX(on={"click": "alert('hi')", "htmx:beforeRequest": "console.log('req')"})
        result = str(hx)
        assert "hx-on:click=\"alert('hi')\"" in result
        assert "hx-on:htmx:beforeRequest=\"console.log('req')\"" in result

    def test_html_method(self):
        hx = HX(get="/api")
        assert hx.__html__() == str(hx)

    @pytest.mark.asyncio
    async def test_interpolation_in_template(self):
        hx = HX(get="/api/data", target="#results", swap="innerHTML")
        result = await html(t"<button {hx}>Load</button>")
        assert 'hx-get="/api/data"' in result.content
        assert 'hx-target="#results"' in result.content

    def test_all_http_methods(self):
        assert 'hx-get="/a"' in str(HX(get="/a"))
        assert 'hx-post="/a"' in str(HX(post="/a"))
        assert 'hx-put="/a"' in str(HX(put="/a"))
        assert 'hx-patch="/a"' in str(HX(patch="/a"))
        assert 'hx-delete="/a"' in str(HX(delete="/a"))


class TestHtmxComponents:
    @pytest.mark.asyncio
    async def test_htmx_scripts(self):
        result = await HtmxScripts()
        assert "htmx.org" in result.content
        assert "htmx.min" in result.content

    @pytest.mark.asyncio
    async def test_htmx_scripts_debug(self):
        result = await HtmxScripts(debug=True)
        assert "htmx.min.js" in result.content

    @pytest.mark.asyncio
    async def test_htmx_extension(self):
        result = await HtmxExtension("json-enc")
        assert "htmx-ext-json-enc" in result.content

    @pytest.mark.asyncio
    async def test_loading_button(self):
        result = await LoadingButton("Save", post="/api/save")
        assert 'hx-post="/api/save"' in result.content
        assert ">Save</button>" in result.content

    @pytest.mark.asyncio
    async def test_loading_button_with_confirm(self):
        result = await LoadingButton("Delete", post="/delete", confirm="Sure?")
        assert 'hx-confirm="Sure?"' in result.content

    @pytest.mark.asyncio
    async def test_infinite_scroll(self):
        result = await InfiniteScroll("/api/more")
        assert 'hx-get="/api/more"' in result.content
        assert 'hx-trigger="revealed"' in result.content
        assert 'hx-swap="afterend"' in result.content

    @pytest.mark.asyncio
    async def test_lazy_load(self):
        result = await LazyLoad("/api/content")
        assert 'hx-get="/api/content"' in result.content
        assert 'hx-trigger="load"' in result.content
        assert 'aria-busy="true"' in result.content

    @pytest.mark.asyncio
    async def test_lazy_load_custom_placeholder(self):
        placeholder = await html(t"<p>Custom loading...</p>")
        result = await LazyLoad("/api/content", placeholder=placeholder)
        assert "Custom loading..." in result.content

    @pytest.mark.asyncio
    async def test_polling_content(self):
        result = await PollingContent("/api/status", interval=10)
        assert 'hx-get="/api/status"' in result.content
        assert 'hx-trigger="every 10s"' in result.content

    @pytest.mark.asyncio
    async def test_search_input(self):
        result = await SearchInput("q", src="/search", target="#results")
        assert 'type="search"' in result.content
        assert 'name="q"' in result.content
        assert 'hx-get="/search"' in result.content
        assert 'hx-target="#results"' in result.content
        assert "delay:300ms" in result.content

    @pytest.mark.asyncio
    async def test_search_input_custom_debounce(self):
        result = await SearchInput("q", src="/s", target="#r", debounce=500)
        assert "delay:500ms" in result.content

    @pytest.mark.asyncio
    async def test_oob_swap(self):
        content = await html(t"<p>Updated!</p>")
        result = await OobSwap("notification", content)
        assert 'id="notification"' in result.content
        assert 'hx-swap-oob="innerHTML"' in result.content
        assert "<p>Updated!</p>" in result.content

    @pytest.mark.asyncio
    async def test_oob_swap_custom_method(self):
        content = await html(t"<p>New</p>")
        result = await OobSwap("target", content, swap="outerHTML")
        assert 'hx-swap-oob="outerHTML"' in result.content
