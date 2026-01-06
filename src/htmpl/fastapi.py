"""
FastAPI integration for htmpl.
"""

from __future__ import annotations

from functools import wraps
from inspect import isawaitable
import inspect
from string.templatelib import Template
from typing import Callable, Awaitable, Any, TypeAlias, TypeVar

from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ValidationError

from .core import SafeHTML, html
from .elements import Element, Fragment
from .forms import FormRenderer, parse_form_errors


HTML: TypeAlias = Element | Fragment | SafeHTML | Template


async def render_html(result: Any) -> str | None:
    """Render an Element/SafeHTML/Template to string."""
    if isinstance(result, SafeHTML):
        return result.content

    if isinstance(result, Template):
        rendered = await html(result)
        return rendered.content

    if hasattr(result, "__html__"):
        content = result.__html__()
        if isawaitable(content):
            content = await content
        return content

    return None


class HTMLRoute(APIRoute):
    """Route class that auto-converts Element/SafeHTML returns to HTMLResponse."""

    def __init__(self, path: str, endpoint: Callable[..., Any], **kwargs):
        # We need to wrap the endpoint callable and process the results
        # doing this here so that we do not have to decorate each endpoint

        @wraps(endpoint)
        async def html_endpoint(*args, **kwargs):
            result = endpoint(*args, **kwargs)
            if isawaitable(result):
                result = await result

            content = await render_html(result)
            if content is not None:
                return HTMLResponse(content)

            return result

        # Preserve signature for FastAPI's dependency injection
        html_endpoint.__signature__ = inspect.signature(endpoint)  # type: ignore

        super().__init__(path, html_endpoint, **kwargs)


T = TypeVar("T", bound=BaseModel)


class Router(APIRouter):
    """
    APIRouter that renders Element/SafeHTML and handles forms.

    Usage:
        from htmpl.fastapi import Router
        from htmpl.elements import section, h1

        router = Router()

        @router.get("/")
        async def home():
            return section(h1("Hello"))

        @router.form("/login", LoginSchema)
        async def login(data: LoginSchema):
            return section(h1(f"Welcome, {data.email}!"))
    """

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("route_class", HTMLRoute)
        super().__init__(*args, **kwargs)

    def form(
        self,
        path: str,
        model: type[T],
        *,
        action: str | None = None,
        method: str = "post",
        submit_text: str = "Submit",
        template: Callable[[FormRenderer, dict, dict], Any] | None = None,
        **form_attrs,
    ):
        """
        Decorator that registers GET (render form) and POST (handle submit) routes.

        Args:
            path: URL path for the form
            model: Pydantic model for validation
            action: Form action URL (defaults to path)
            method: Form method
            submit_text: Submit button text
            template: Custom template function(renderer, values, errors) -> Element
            **form_attrs: Extra attributes for the form element
        """
        renderer = FormRenderer(model)
        form_action = action or path

        def decorator(handler: Callable[[T], Awaitable[Any]]):

            @self.get(path)
            async def get_form(request: Request) -> Any:
                values = dict(request.query_params)
                if template:
                    return template(renderer, values, {})
                return renderer.render(
                    action=form_action,
                    method=method,
                    values=values,
                    submit_text=submit_text,
                    **form_attrs,
                )

            @self.post(path)
            async def post_form(request: Request) -> Any:
                form_data = await request.form()
                values = dict(form_data)

                for name, cfg in renderer.field_configs.items():
                    if cfg.widget == "checkbox" and name in form_data:
                        values[name] = True  # type: ignore

                try:
                    validated = model(**values)
                except ValidationError as e:
                    errors = parse_form_errors(e)
                    if template:
                        return template(renderer, values, errors)
                    return renderer.render(
                        action=form_action,
                        method=method,
                        values=values,
                        errors=errors,
                        submit_text=submit_text,
                        **form_attrs,
                    )

                return await handler(validated)

            return handler

        return decorator


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


def htmx_retarget(content: SafeHTML, target: str) -> Response:
    """Return content with retargeted swap."""
    return Response(
        content=content.content,
        headers={"HX-Retarget": target},
    )


def htmx_trigger_event(
    content: SafeHTML,
    event: str,
    *,
    after: str = "settle",
) -> Response:
    """Return content and trigger a client-side event."""
    header = (
        f"HX-Trigger-After-{after.capitalize()}" if after != "receive" else "HX-Trigger"
    )
    return Response(
        content=content.content,
        headers={header: event},
    )
