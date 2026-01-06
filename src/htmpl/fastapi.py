"""
FastAPI integration for htmpl.
"""

from __future__ import annotations

from typing import Callable, Awaitable
from functools import wraps
from inspect import isawaitable
from string.templatelib import Template
from typing import Callable, Awaitable

from fastapi import Request, Response
from fastapi.responses import HTMLResponse

from .core import SafeHTML, html
from .elements import Element, Fragment


class THtmlResponse(HTMLResponse):
    """FastAPI response for SafeHTML content."""

    def __init__(
        self,
        content: SafeHTML,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(
            content=content.content,
            status_code=status_code,
            headers=headers,
        )


Renderable = SafeHTML | Element | Fragment | Template


def html_response(
    func: Callable[..., Renderable | Awaitable[Renderable]],
) -> Callable[..., Awaitable[THtmlResponse]]:
    """
    Decorator that renders SafeHTML/Element/Template to THtmlResponse.

    Usage:
        @app.get("/")
        @html_response
        async def home() -> Element:
            return section(h1("Hello"))

        @app.get("/page")
        @html_response
        async def page(name: str) -> Template:
            return t"<h1>Hello {name}</h1>"
    """

    @wraps(func)
    async def wrapper(*args, **kwargs) -> THtmlResponse:
        result = func(*args, **kwargs)
        if isawaitable(result):
            result = await result

        # Element/Fragment -> render async __html__
        if isinstance(result, (Element, Fragment)):
            content = await result.__html__()
            return THtmlResponse(SafeHTML(content))

        # Template -> process with html()
        if isinstance(result, Template):
            return THtmlResponse(await html(result))

        # SafeHTML -> use directly
        return THtmlResponse(result)

    return wrapper


# Request context helpers


def is_htmx(request: Request) -> bool:
    """Check if request is from HTMX."""
    return request.headers.get("HX-Request") == "true"


def htmx_target(request: Request) -> str | None:
    """Get HTMX target element ID."""
    return request.headers.get("HX-Target")


def htmx_trigger(request: Request) -> str | None:
    """Get HTMX trigger element ID."""
    return request.headers.get("HX-Trigger")


# HTMX response helpers


def htmx_redirect(url: str) -> Response:
    """Redirect via HTMX HX-Redirect header."""
    return Response(
        status_code=200,
        headers={"HX-Redirect": url},
    )


def htmx_refresh() -> Response:
    """Trigger full page refresh via HTMX."""
    return Response(
        status_code=200,
        headers={"HX-Refresh": "true"},
    )


def htmx_retarget(content: SafeHTML, target: str) -> THtmlResponse:
    """Return content with retargeted swap."""
    return THtmlResponse(
        content=content,
        headers={"HX-Retarget": target},
    )


def htmx_trigger_event(
    content: SafeHTML,
    event: str,
    *,
    after: str = "settle",
) -> THtmlResponse:
    """Return content and trigger a client-side event."""
    header = (
        f"HX-Trigger-After-{after.capitalize()}" if after != "receive" else "HX-Trigger"
    )
    return THtmlResponse(
        content=content,
        headers={header: event},
    )
