"""
HTML element factories for pure-Python composition.

Usage:
    from htmpl.elements import div, section, h1, p, a, button

    section(
        h1("Welcome"),
        t"<p>Hello {name}</p>",  # t-strings work as children
        div(
            button("Click me", type="button"),
            class_="actions"
        ),
        class_="hero",
        id="main"
    )
"""

from __future__ import annotations

from html import escape
from inspect import isawaitable
from string.templatelib import Template, Interpolation
from typing import Any

from .core import SafeHTML, attr


class Element:
    """
    Lazy HTML element that renders when __html__ is called.

    Supports async rendering - coroutines in children are awaited.
    """

    __slots__ = ("tag", "children", "attrs", "void")

    def __init__(
        self,
        tag: str,
        children: tuple[Any, ...],
        attrs: dict[str, Any],
        void: bool = False,
    ):
        self.tag = tag
        self.children = children
        self.attrs = attrs
        self.void = void

    async def __html__(self) -> str:
        attr_str = _render_attrs(self.attrs)
        space = " " if attr_str else ""

        if self.void:
            return f"<{self.tag}{space}{attr_str}>"

        inner = await _render_children(self.children)
        return f"<{self.tag}{space}{attr_str}>{inner}</{self.tag}>"

    def __repr__(self) -> str:
        return (
            f"Element({self.tag!r}, children={len(self.children)}, attrs={list(self.attrs.keys())})"
        )


async def _render_children(children: tuple[Any, ...]) -> str:
    """Render a tuple of children to string."""
    parts = []
    for child in children:
        if child is None:
            continue

        # Await coroutines
        if isawaitable(child):
            child = await child
        if child is None:
            continue

        # SafeHTML passes through
        if isinstance(child, SafeHTML):
            parts.append(child.content)
        # Elements render recursively
        elif isinstance(child, Element):
            parts.append(await child.__html__())
        # t-strings process inline
        elif isinstance(child, Template):
            parts.append(await _render_template(child))
        # Strings get escaped
        elif isinstance(child, str):
            parts.append(escape(child))
        # Objects with __html__ (sync or async)
        elif hasattr(child, "__html__"):
            result = child.__html__()
            if isawaitable(result):
                result = await result
            parts.append(result)
        # Iterables flatten (but not strings)
        elif hasattr(child, "__iter__") and not isinstance(child, (str, bytes)):
            for item in child:
                parts.append(await _render_children((item,)))
        # Everything else: str + escape
        else:
            parts.append(escape(str(child)))

    return "".join(parts)


async def _render_template(template: Template) -> str:
    """Render a t-string template with escaping."""
    parts = []
    for item in template:
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, Interpolation):
            parts.append(await _render_children((item.value,)))
    return "".join(parts)


def _render_attrs(attrs: dict[str, Any]) -> str:
    """Render attributes dict to string."""
    parts = []
    for key, value in attrs.items():
        # class_ -> class, for_ -> for
        if key.endswith("_"):
            key = key[:-1]
        # snake_case -> kebab-case
        key = key.replace("_", "-")

        result = attr(key, value)
        if result.content:
            parts.append(result.content)

    return " ".join(parts)


def _make_element(tag: str, void: bool = False):
    """Factory for creating element functions."""

    def element(*children, **attrs) -> Element:
        return Element(tag, children, attrs, void)

    element.__name__ = tag
    element.__doc__ = f"Create a <{tag}> element."
    return element


# Document structure
html_el = _make_element("html")  # Avoid shadowing htmpl.html
head = _make_element("head")
body = _make_element("body")
title = _make_element("title")

# Sections
section = _make_element("section")
article = _make_element("article")
aside = _make_element("aside")
header = _make_element("header")
footer = _make_element("footer")
nav = _make_element("nav")
main = _make_element("main")
div = _make_element("div")

# Headings
h1 = _make_element("h1")
h2 = _make_element("h2")
h3 = _make_element("h3")
h4 = _make_element("h4")
h5 = _make_element("h5")
h6 = _make_element("h6")
hgroup = _make_element("hgroup")

# Text content
p = _make_element("p")
pre = _make_element("pre")
blockquote = _make_element("blockquote")
ol = _make_element("ol")
ul = _make_element("ul")
li = _make_element("li")
dl = _make_element("dl")
dt = _make_element("dt")
dd = _make_element("dd")
figure = _make_element("figure")
figcaption = _make_element("figcaption")

# Inline text
a = _make_element("a")
span = _make_element("span")
strong = _make_element("strong")
em = _make_element("em")
b = _make_element("b")
i = _make_element("i")
u = _make_element("u")
s = _make_element("s")
small = _make_element("small")
mark = _make_element("mark")
code = _make_element("code")
kbd = _make_element("kbd")
abbr = _make_element("abbr")
time_ = _make_element("time")
del_ = _make_element("del")
ins = _make_element("ins")
sub = _make_element("sub")
sup = _make_element("sup")

# Forms
form = _make_element("form")
label = _make_element("label")
input_ = _make_element("input", void=True)
button = _make_element("button")
select = _make_element("select")
option = _make_element("option")
optgroup = _make_element("optgroup")
textarea = _make_element("textarea")
fieldset = _make_element("fieldset")
legend = _make_element("legend")
datalist = _make_element("datalist")
output = _make_element("output")

# Tables
table = _make_element("table")
thead = _make_element("thead")
tbody = _make_element("tbody")
tfoot = _make_element("tfoot")
tr = _make_element("tr")
th = _make_element("th")
td = _make_element("td")
caption = _make_element("caption")
colgroup = _make_element("colgroup")
col = _make_element("col", void=True)

# Media
img = _make_element("img", void=True)
audio = _make_element("audio")
video = _make_element("video")
source = _make_element("source", void=True)
track = _make_element("track", void=True)
picture = _make_element("picture")
iframe = _make_element("iframe")
embed = _make_element("embed", void=True)
object_ = _make_element("object")
canvas = _make_element("canvas")
svg = _make_element("svg")

# Interactive
details = _make_element("details")
summary = _make_element("summary")
dialog = _make_element("dialog")
menu = _make_element("menu")

# Other
br = _make_element("br", void=True)
hr = _make_element("hr", void=True)
wbr = _make_element("wbr", void=True)
link = _make_element("link", void=True)
meta_ = _make_element("meta", void=True)
script = _make_element("script")
style = _make_element("style")
template = _make_element("template")
slot = _make_element("slot")


class Fragment:
    """Multiple children without a wrapper element."""

    __slots__ = ("children",)

    def __init__(self, *children):
        self.children = children

    async def __html__(self) -> str:
        return await _render_children(self.children)


def fragment(*children) -> Fragment:
    """Render multiple children without a wrapper element."""
    return Fragment(*children)
