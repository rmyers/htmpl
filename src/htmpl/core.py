"""
Core async template processing engine.
"""

import asyncio
from dataclasses import dataclass
from inspect import isawaitable, iscoroutinefunction
from string.templatelib import Template
from typing import Any, TYPE_CHECKING

from tdom import Element, Fragment, Node, html

from fastapi.responses import HTMLResponse

if TYPE_CHECKING:
    from .assets import Component


@dataclass(frozen=True, slots=True)
class SafeHTML:
    """
    Marks content as already escaped/safe.
    Immutable and hashable for use as cache keys.
    """

    content: str

    def __html__(self) -> str:
        return self.content

    def __str__(self) -> str:
        return self.content

    def __bool__(self) -> bool:
        return bool(self.content)

    def encode(self, encoding: str = "utf-8", errors: str = "strict") -> bytes:
        return self.content.encode(encoding, errors)


async def render_html(result: Any) -> HTMLResponse:
    """Render an Element/SafeHTML/Template to SafeHTML."""
    if isinstance(result, SafeHTML):
        return HTMLResponse(result)

    if isinstance(result, Template):
        content = html(result)
        return HTMLResponse(str(content))

    if hasattr(result, "__html__"):
        content = result.__html__()
        if isawaitable(content):
            content = await content
        return HTMLResponse(SafeHTML(content))

    return HTMLResponse("")


async def process_components(node: Node, registry: dict[str, "Component"]) -> Node:
    """Walk tree, replace custom elements with registered component calls."""
    if isinstance(node, Fragment):
        children = await asyncio.gather(
            *[process_components(c, registry) for c in node.children]
        )
        return Fragment(list(children))

    if not isinstance(node, Element):
        return node

    # Process children first (bottom-up)
    children = await asyncio.gather(
        *[process_components(c, registry) for c in node.children]
    )

    # Custom element? Call the component
    if "-" in node.tag and node.tag in registry:
        comp = registry[node.tag]
        result = comp.fn(children=list(children), **node.attrs)
        if isawaitable(result):
            result = await result

        # If component returned a Template, convert to Node
        if isinstance(result, Template):
            result = html(result)

        # Recursively process in case component contains other custom elements
        return await process_components(result, registry)

    # Regular element with processed children
    return Element(node.tag, node.attrs, list(children))


async def render(template: Template, registry: dict) -> HTMLResponse:
    content = html(template)
    node = await process_components(content, registry)
    print(f"{node!r}")
    return HTMLResponse(str(node))
