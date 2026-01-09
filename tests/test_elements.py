"""
Tests for htmpl element factories.
"""

import pytest
from htmpl.elements import (
    Element,
    Fragment,
    fragment,
    div,
    span,
    p,
    a,
    h1,
    h2,
    ul,
    li,
    table,
    tr,
    td,
    th,
    form,
    label,
    input_,
    button,
    select,
    option,
    textarea,
    article,
    section,
    header,
    footer,
    nav,
    main,
    img,
    br,
    hr,
)


class TestElementBasics:
    @pytest.mark.asyncio
    async def test_simple_element(self):
        el = div("Hello")
        html = await el.__html__()
        assert html == "<div>Hello</div>"

    @pytest.mark.asyncio
    async def test_nested_elements(self):
        el = div(span("inner"))
        html = await el.__html__()
        assert html == "<div><span>inner</span></div>"

    @pytest.mark.asyncio
    async def test_multiple_children(self):
        el = div(span("one"), span("two"), span("three"))
        html = await el.__html__()
        assert html == "<div><span>one</span><span>two</span><span>three</span></div>"

    @pytest.mark.asyncio
    async def test_empty_element(self):
        el = div()
        html = await el.__html__()
        assert html == "<div></div>"

    @pytest.mark.asyncio
    async def test_void_element(self):
        el = br()
        html = await el.__html__()
        assert html == "<br>"

    @pytest.mark.asyncio
    async def test_void_element_with_attrs(self):
        el = img(src="/image.png", alt="An image")
        html = await el.__html__()
        assert "<img" in html
        assert 'src="/image.png"' in html
        assert 'alt="An image"' in html
        assert "</img>" not in html


class TestAttributes:
    @pytest.mark.asyncio
    async def test_simple_attribute(self):
        el = div(id="main")
        html = await el.__html__()
        assert '<div id="main"></div>' == html

    @pytest.mark.asyncio
    async def test_class_underscore(self):
        el = div(class_="container")
        html = await el.__html__()
        assert 'class="container"' in html

    @pytest.mark.asyncio
    async def test_for_underscore(self):
        el = label(for_="email")
        html = await el.__html__()
        assert 'for="email"' in html

    @pytest.mark.asyncio
    async def test_data_attribute(self):
        el = div(data_user_id="123")
        html = await el.__html__()
        assert 'data-user-id="123"' in html

    @pytest.mark.asyncio
    async def test_aria_attribute(self):
        el = button(aria_label="Close")
        html = await el.__html__()
        assert 'aria-label="Close"' in html

    @pytest.mark.asyncio
    async def test_boolean_true_attribute(self):
        el = input_(disabled=True)
        html = await el.__html__()
        assert "disabled" in html
        assert 'disabled="' not in html

    @pytest.mark.asyncio
    async def test_boolean_false_attribute(self):
        el = input_(disabled=False)
        html = await el.__html__()
        assert "disabled" not in html

    @pytest.mark.asyncio
    async def test_none_attribute(self):
        el = div(title=None)
        html = await el.__html__()
        assert "title" not in html

    @pytest.mark.asyncio
    async def test_attribute_escaping(self):
        el = div(title='Say "hello"')
        html = await el.__html__()
        assert 'title="Say &quot;hello&quot;"' in html


class TestChildrenEscaping:
    @pytest.mark.asyncio
    async def test_string_escaped(self):
        el = div("<script>alert('xss')</script>")
        html = await el.__html__()
        assert "<script>" not in html
        assert "&lt;script&gt;" in html

    @pytest.mark.asyncio
    async def test_safehtml_not_escaped(self):
        from htmpl import SafeHTML

        el = div(SafeHTML("<strong>bold</strong>"))
        html = await el.__html__()
        assert "<strong>bold</strong>" in html

    @pytest.mark.asyncio
    async def test_none_child_ignored(self):
        el = div("before", None, "after")
        html = await el.__html__()
        assert html == "<div>beforeafter</div>"


class TestListChildren:
    @pytest.mark.asyncio
    async def test_list_of_elements(self):
        items = [li("one"), li("two"), li("three")]
        el = ul(items)
        html = await el.__html__()
        assert "<li>one</li>" in html
        assert "<li>two</li>" in html
        assert "<li>three</li>" in html

    @pytest.mark.asyncio
    async def test_list_comprehension(self):
        el = ul([li(str(i)) for i in range(3)])
        html = await el.__html__()
        assert "<li>0</li>" in html
        assert "<li>1</li>" in html
        assert "<li>2</li>" in html

    @pytest.mark.asyncio
    async def test_mixed_children_and_list(self):
        el = div(
            h1("Title"),
            [p(f"Para {i}") for i in range(2)],
            footer("End"),
        )
        html = await el.__html__()
        assert "<h1>Title</h1>" in html
        assert "<p>Para 0</p>" in html
        assert "<p>Para 1</p>" in html
        assert "<footer>End</footer>" in html


class TestAsyncChildren:
    @pytest.mark.asyncio
    async def test_coroutine_child(self):
        async def async_content():
            return span("async result")

        el = div(async_content())
        html = await el.__html__()
        assert "<span>async result</span>" in html

    @pytest.mark.asyncio
    async def test_coroutine_returning_none(self):
        async def maybe_content(show: bool):
            return span("visible") if show else None

        el = div(maybe_content(False), maybe_content(True))
        html = await el.__html__()
        assert "visible" in html
        assert html.count("<span>") == 1

    @pytest.mark.asyncio
    async def test_list_of_coroutines(self):
        async def make_item(n: int):
            return li(str(n))

        el = ul([make_item(i) for i in range(3)])
        html = await el.__html__()
        assert "<li>0</li>" in html
        assert "<li>1</li>" in html
        assert "<li>2</li>" in html

    @pytest.mark.asyncio
    async def test_nested_async(self):
        async def inner():
            return span("deep")

        async def outer():
            return div(inner())

        el = section(outer())
        html = await el.__html__()
        assert "<section><div><span>deep</span></div></section>" == html


class TestTStringChildren:
    @pytest.mark.asyncio
    async def test_tstring_child(self):
        name = "World"
        el = div(t"<p>Hello {name}!</p>")
        html = await el.__html__()
        assert "<p>Hello World!</p>" in html

    @pytest.mark.asyncio
    async def test_tstring_escapes_interpolation(self):
        user_input = "<script>bad</script>"
        el = div(t"<p>{user_input}</p>")
        html = await el.__html__()
        assert "<script>" not in html
        assert "&lt;script&gt;" in html

    @pytest.mark.asyncio
    async def test_tstring_with_element(self):
        el = div(t"<header>Title</header>{p('Body content')}")
        html = await el.__html__()
        assert "<header>Title</header>" in html
        assert "<p>Body content</p>" in html


class TestFragment:
    @pytest.mark.asyncio
    async def test_fragment_basic(self):
        frag = fragment(div("one"), div("two"))
        html = await frag.__html__()
        assert html == "<div>one</div><div>two</div>"

    @pytest.mark.asyncio
    async def test_fragment_as_child(self):
        frag = fragment(li("a"), li("b"))
        el = ul(frag)
        html = await el.__html__()
        assert "<ul><li>a</li><li>b</li></ul>" == html

    @pytest.mark.asyncio
    async def test_fragment_with_async(self):
        async def item():
            return li("async")

        frag = fragment(li("sync"), item())
        html = await frag.__html__()
        assert "<li>sync</li>" in html
        assert "<li>async</li>" in html

    @pytest.mark.asyncio
    async def test_empty_fragment(self):
        frag = fragment()
        html = await frag.__html__()
        assert html == ""


class TestCommonPatterns:
    @pytest.mark.asyncio
    async def test_table_structure(self):
        el = table(
            tr(th("Name"), th("Age")),
            tr(td("Alice"), td("30")),
            tr(td("Bob"), td("25")),
        )
        html = await el.__html__()
        assert "<table>" in html
        assert "<th>Name</th>" in html
        assert "<td>Alice</td>" in html
        assert "</table>" in html

    @pytest.mark.asyncio
    async def test_form_structure(self):
        el = form(
            label("Email", input_(type="email", name="email")),
            button("Submit", type="submit"),
            action="/login",
            method="post",
        )
        html = await el.__html__()
        assert 'action="/login"' in html
        assert 'method="post"' in html
        assert 'type="email"' in html
        assert 'name="email"' in html

    @pytest.mark.asyncio
    async def test_nav_structure(self):
        links = [("Home", "/"), ("About", "/about"), ("Contact", "/contact")]
        el = nav(
            ul([li(a(text, href=url)) for text, url in links]),
            class_="main-nav",
        )
        html = await el.__html__()
        assert 'class="main-nav"' in html
        assert 'href="/"' in html
        assert 'href="/about"' in html
        assert ">Home</a>" in html


class TestElementRepr:
    def test_repr(self):
        el = div(span("hello"), class_="container", id="main")
        r = repr(el)
        assert "Element" in r
        assert "div" in r
