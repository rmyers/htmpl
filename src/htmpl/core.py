"""
Core async template processing engine.
"""

from dataclasses import dataclass
from inspect import isawaitable
from string.templatelib import Template
from typing import Any

from tdom import html

from fastapi.responses import HTMLResponse


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
