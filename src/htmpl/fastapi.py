"""
FastAPI integration for htmpl.
"""

from __future__ import annotations

from functools import wraps
from inspect import isawaitable
import inspect
from string.templatelib import Template
from typing import Any, Awaitable, Callable, Generic, TypeAlias, TypeVar

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ValidationError

from .core import SafeHTML, html
from .elements import Element, Fragment
from .forms import BaseForm, parse_form_errors


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


T = TypeVar("T", bound=BaseForm)


class FormValidationError(HTTPException):
    """Raised when form validation fails - contains the rendered HTML response."""

    def __init__(self, content: str):
        # Use 422 for validation errors, or 200 if you want it to look successful
        super().__init__(status_code=200, detail="Form validation failed")
        self.response = HTMLResponse(content=content, status_code=200)


async def form_validation_error_handler(request: Request, exc: FormValidationError):
    return exc.response


class HTMLForm(Generic[T]):
    """
    Dependency that validates form data and re-renders template on errors.

    Usage:
        async def login_page(renderer, values, errors):
            return section(
                h1("Login"),
                renderer.render(action="/login", values=values, errors=errors)
            )

        @router.get("/login")
        async def show_login():
            return await login_page(login_form, {}, {})

        @router.post("/login")
        async def handle_login(
            data: LoginSchema = Depends(HTMLForm(LoginSchema, login_page)),
            user: User = Depends(get_current_user)
        ):
            # Only reached if validation succeeds
            return htmx_redirect("/dashboard")
    """

    def __init__(
        self,
        model: type[T],
        template: Callable[[type[T], dict, dict], Awaitable[HTML]],
    ):
        self.model = model
        self.template = template

    async def __call__(self, request: Request) -> T:
        """Validate form data or raise FormValidationError with rendered template."""
        form_data = await request.form()
        values = dict(form_data)

        # Handle checkboxes
        for name, cfg in self.model.get_field_configs().items():
            if cfg.widget == "checkbox" and name in form_data:
                values[name] = True  # type: ignore

        try:
            return self.model(**values)
        except ValidationError as e:
            errors = parse_form_errors(e)

            # Render the template with errors
            html = await self.template(self.model, values, errors)
            content = await render_html(html)

            # Raise exception to short-circuit and return the rendered form
            raise FormValidationError(content or "<div>Invalid Form</div")


class HTMLRouter(APIRouter):
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
