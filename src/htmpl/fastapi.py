from __future__ import annotations

import inspect
from dataclasses import dataclass
from functools import wraps
from inspect import isawaitable
from string.templatelib import Template
from typing import Annotated, Any, Awaitable, Callable, Generic, TypeAlias, TypeVar

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.routing import APIRoute
from pydantic import ValidationError

from .assets import (
    BUNDLE_DIR,
    Bundles,
    Page as PageDef,
    ComponentFunc,
    get_bundles,
    get_pages,
    _pages,
)
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


# --- Page Context ---


@dataclass
class PageContext:
    """Runtime page context with resolved bundles."""

    name: str
    title: str
    bundles: Bundles


def get_page(request: Request) -> PageContext | None:
    """Get current page context from request state."""
    return getattr(request.state, "htmpl_page", None)


CurrentPage = Annotated[PageContext, Depends(get_page)]


def page(
    name: str,
    *,
    title: str = "Page",
    css: set[str] | None = None,
    js: set[str] | None = None,
    py: set[str] | None = None,
    uses: set[ComponentFunc] | None = None,
):
    """
    Page dependency - registers assets at import time, sets up context at request time.

    Usage:
        @router.get("/", dependencies=[page("home", title="Home", uses={AppPage, NavBar})])
        async def home():
            return section(h1("Welcome"))

        # Access context if needed
        @router.get("/dashboard", dependencies=[page("dashboard", title="Dashboard")])
        async def dashboard(ctx: CurrentPage):
            return section(h1(ctx.title))
    """
    # Resolve component names from functions
    imports: set[str] = set()
    for comp in uses or set():
        if not callable(comp):
            raise TypeError(f"Expected a component function, got {type(comp).__name__}")
        comp_name = getattr(comp, "_htmpl_component", None)
        if comp_name is None:
            raise TypeError(
                f"'{type(comp).__name__}' is not a registered component. "
                f"Add the @component decorator to register it."
            )
        imports.add(comp_name)

    # Static registration at import time
    _pages[name] = PageDef(
        name=name,
        title=title,
        css=css or set(),
        js=js or set(),
        py=py or set(),
        imports=imports,
    )

    # Runtime dependency
    def setup_page_context(request: Request) -> PageContext:
        ctx = PageContext(
            name=name,
            title=title,
            bundles=get_bundles(name),
        )
        request.state.htmpl_page = ctx
        return ctx

    return Depends(setup_page_context)


# --- Layout ---

LayoutFunc: TypeAlias = Callable[[str, str, Bundles], str | Awaitable[str]]


def default_layout(content: str, title: str, bundles: Bundles) -> str:
    """Default page layout."""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    {bundles.head()}
</head>
<body>
    {content}
</body>
</html>"""


# --- Routes ---


class HTMLRoute(APIRoute):
    """
    Route that auto-converts Element/SafeHTML to HTMLResponse.
    If page context is set, wraps with layout.
    """

    def __init__(
        self,
        path: str,
        endpoint: Callable[..., Any],
        *,
        layout: LayoutFunc | None = None,
        **kwargs,
    ):
        layout_fn = layout or default_layout
        orig_sig = inspect.signature(endpoint)
        orig_params = list(orig_sig.parameters.values())

        # Check if endpoint already has request param
        has_request = "request" in orig_sig.parameters

        @wraps(endpoint)
        async def html_endpoint(request: Request, *args, **kw):
            # Call original endpoint
            if has_request:
                result = endpoint(request=request, *args, **kw)
            else:
                result = endpoint(*args, **kw)

            if isawaitable(result):
                result = await result

            content = await render_html(result)
            if content is None:
                return result

            # Check for page context from request.state
            ctx = getattr(request.state, "htmpl_page", None)
            if ctx:
                final = layout_fn(content, ctx.title, ctx.bundles)
                if isawaitable(final):
                    final = await final
                return HTMLResponse(final)

            return HTMLResponse(content)

        # Build new signature with request first, then original params (minus request if present)
        new_params = [
            inspect.Parameter(
                "request", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=Request
            )
        ]
        for p in orig_params:
            if p.name != "request":
                new_params.append(p)

        html_endpoint.__signature__ = inspect.Signature(parameters=new_params)  # type: ignore

        super().__init__(path, html_endpoint, **kwargs)


# --- Form Handling ---

T = TypeVar("T", bound=BaseForm)


class FormValidationError(HTTPException):
    """Raised when form validation fails - contains the rendered HTML response."""

    def __init__(self, content: str):
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
            html_result = await self.template(self.model, values, errors)
            content = await render_html(html_result)

            raise FormValidationError(content or "<div>Invalid Form</div>")


class HTMLRouter(APIRouter):
    """
    Router with HTML rendering support.

    Usage:
        router = HTMLRouter()

        # Simple fragment (no layout)
        @router.get("/fragment")
        async def fragment():
            return div(h1("Hello"))

        # Full page with layout and bundling
        @router.get("/", dependencies=[page("home", title="Home", imports={"nav"})])
        async def home():
            return section(h1("Dashboard"))
    """

    def __init__(self, *args, layout: LayoutFunc | None = None, **kwargs):
        self._layout = layout
        kwargs.setdefault("route_class", HTMLRoute)
        super().__init__(*args, **kwargs)

    def add_api_route(
        self,
        path: str,
        endpoint: Callable[..., Any],
        *,
        layout: LayoutFunc | None = None,
        **kwargs,
    ) -> None:
        """Override to pass layout to HTMLRoute."""
        route = HTMLRoute(
            path,
            endpoint,
            layout=layout or self._layout,
            **kwargs,
        )
        self.routes.append(route)


# --- Bundle Serving ---


def mount_bundles(router: APIRouter, path: str = "/static/bundles") -> None:
    """Add route to serve bundles with immutable caching."""

    @router.get(f"{path}/{{filename:path}}")
    async def serve_bundle(filename: str):
        file_path = BUNDLE_DIR / filename
        if not file_path.exists():
            return Response(status_code=404)

        media_types = {
            ".css": "text/css",
            ".js": "application/javascript",
            ".py": "text/x-python",
        }
        media = media_types.get(file_path.suffix, "application/octet-stream")

        return FileResponse(
            file_path,
            media_type=media,
            headers={"Cache-Control": "public, max-age=31536000, immutable"},
        )


# --- HTMX Helpers ---


def is_htmx(request: Request) -> bool:
    """Check if request is from HTMX."""
    return request.headers.get("HX-Request") == "true"


def htmx_target(request: Request) -> str | None:
    """Get HTMX target element ID."""
    return request.headers.get("HX-Target")


def htmx_trigger(request: Request) -> str | None:
    """Get HTMX trigger element ID."""
    return request.headers.get("HX-Trigger")


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
    header = f"HX-Trigger-After-{after.capitalize()}" if after != "receive" else "HX-Trigger"
    return Response(
        content=content.content,
        headers={header: event},
    )
