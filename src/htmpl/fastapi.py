"""FastAPI integration with component DI and automatic asset registration."""

from __future__ import annotations

import inspect
from functools import wraps
from inspect import isawaitable
from string.templatelib import Template
from typing import (
    Annotated,
    Any,
    Awaitable,
    Callable,
    Generic,
    TypeVar,
)

from fastapi import Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from fastapi.routing import APIRoute
from pydantic import ValidationError

from .assets import (
    _pages,
    AssetCollector,
    ComponentFunc,
    Page,
    PageContext,
)
from .core import SafeHTML, html
from .forms import BaseForm, parse_form_errors


# --- Request State Helpers ---


def get_asset_collector(request: Request) -> AssetCollector:
    """Get or create the asset collector for this request."""
    if not hasattr(request.state, "htmpl_assets"):
        request.state.htmpl_assets = AssetCollector()
    return request.state.htmpl_assets


def get_page_context(request: Request) -> PageContext | None:
    """Get page context if set."""
    return getattr(request.state, "htmpl_page", None)


Assets = Annotated[AssetCollector, Depends(get_asset_collector)]
CurrentPage = Annotated[PageContext | None, Depends(get_page_context)]


# --- Page Dependency ---


def page(
    name: str,
    *,
    title: str = "Page",
    layout: Callable | None = None,
):
    """
    Page dependency - sets up context with optional layout.

    Usage:
        # No layout - just asset collection
        @router.get("/fragment", dependencies=[page("frag")])
        async def fragment():
            return div("Hello")

        # With layout component
        @router.get("/", dependencies=[page("home", title="Home", layout=AppLayout)])
        async def home():
            return section(h1("Welcome"))
    """
    # Register page at import time for pre-building
    layout_name = getattr(layout, "_htmpl_layout", None) if layout else None
    _pages[name] = Page(
        name=name,
        title=title,
        layout=layout_name,
    )

    if layout is not None and hasattr(layout, "_htmpl_layout"):
        # Layout is a component - merge its signature into setup
        layout_name = layout._htmpl_layout
        layout_sig = inspect.signature(layout, eval_str=True)

        # Build params: Request first, then layout's params
        params = [
            inspect.Parameter(
                "request",
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                annotation=Request,
            )
        ]

        for pname, p in layout_sig.parameters.items():
            params.append(
                inspect.Parameter(
                    pname,
                    inspect.Parameter.POSITIONAL_OR_KEYWORD,
                    default=p.default,
                    annotation=p.annotation,
                )
            )

        async def setup(request: Request, **kwargs) -> PageContext:
            collector = get_asset_collector(request)
            collector.add(layout_name)

            # Call layout to get renderer
            resolved_layout = await layout(**kwargs)

            ctx = PageContext(
                name=name,
                title=title,
                layout=resolved_layout,
                assets=collector,
            )
            request.state.htmpl_page = ctx
            return ctx

        setup.__signature__ = inspect.Signature(parameters=params)  # type: ignore
        return Depends(setup)

    else:
        # No layout or plain function layout
        def setup_simple(request: Request) -> PageContext:
            collector = get_asset_collector(request)
            ctx = PageContext(
                name=name,
                title=title,
                layout=layout,
                assets=collector,
            )
            request.state.htmpl_page = ctx
            return ctx

        return Depends(setup_simple)


# --- Component Injection ---


def use_component(
    component: ComponentFunc,
    **fixed_kwargs: Any,
) -> Any:
    """
    FastAPI dependency that renders a component and registers its assets.

    Usage:
        @component(css={"/static/navbar.css"})
        async def NavBar(user: Annotated[User, Depends(get_user)]):
            return await html(t'<nav>Welcome {user.name}</nav>')

        @router.get("/", dependencies=[page("home", layout=AppLayout)])
        async def home(navbar: Annotated[SafeHTML, use_component(NavBar)]):
            return section(navbar, h1("Welcome"))
    """
    if not hasattr(component, "_htmpl_component"):
        raise TypeError(
            f"'{getattr(component, '__name__', component)}' is not a registered component. "
            f"Add the @component decorator to register it."
        )

    comp_name = component._htmpl_component
    sig = inspect.signature(component, eval_str=True)

    params = []
    has_request = False

    for pname, p in sig.parameters.items():
        if pname in fixed_kwargs:
            continue
        if p.annotation is Request:
            has_request = True
        params.append(
            inspect.Parameter(
                pname,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                default=p.default,
                annotation=p.annotation,
            )
        )

    if not has_request:
        params.insert(
            0,
            inspect.Parameter(
                "_htmpl_request",
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                annotation=Request,
            ),
        )

    async def render(**kwargs) -> SafeHTML | None:
        request = kwargs.pop("_htmpl_request", None)
        if request is None:
            for v in kwargs.values():
                if isinstance(v, Request):
                    request = v
                    break

        if request is not None:
            collector = get_asset_collector(request)
            collector.add(comp_name)

        return await component(**fixed_kwargs, **kwargs)

    render.__signature__ = inspect.Signature(parameters=params)  # type: ignore
    render.__name__ = f"use_{comp_name}"

    return Depends(render)


# --- HTML Route ---


class HTMLRoute(APIRoute):
    """
    Route that auto-converts Element/SafeHTML to HTMLResponse.

    Usage:
        router = APIRouter(route_class=HTMLRoute)
    """

    def __init__(self, path: str, endpoint: Callable[..., Any], **kwargs):
        sig = inspect.signature(endpoint)
        needs_request = "request" not in sig.parameters

        @wraps(endpoint)
        async def html_endpoint(request: Request, **kw):
            if needs_request:
                result = endpoint(**kw)
            else:
                result = endpoint(request=request, **kw)

            if isawaitable(result):
                result = await result

            if hasattr(result, "status_code"):
                return result

            content = await render_html(result)
            if content is None:
                return result

            ctx = get_page_context(request)
            if ctx:
                final = await ctx.render(content)
                return HTMLResponse(final.content)

            return HTMLResponse(
                content.content if isinstance(content, SafeHTML) else content
            )

        params = list(sig.parameters.values())

        if needs_request:
            params.insert(
                0,
                inspect.Parameter(
                    "request",
                    inspect.Parameter.POSITIONAL_OR_KEYWORD,
                    annotation=Request,
                ),
            )

        html_endpoint.__signature__ = sig.replace(parameters=params)  # type: ignore

        super().__init__(path, html_endpoint, **kwargs)


# --- Helpers ---


async def render_html(result: Any) -> SafeHTML | None:
    """Render an Element/SafeHTML/Template to SafeHTML."""
    if isinstance(result, SafeHTML):
        return result

    if isinstance(result, Template):
        return await html(result)

    if hasattr(result, "__html__"):
        content = result.__html__()
        if isawaitable(content):
            content = await content
        return SafeHTML(content)

    return None


# --- Form Handling ---


class FormValidationError(HTTPException):
    """Raised when form validation fails - contains the rendered HTML response."""

    def __init__(self, content: SafeHTML | None):
        super().__init__(status_code=200, detail="Form validation failed")
        self.response = HTMLResponse(
            content=content.content if content else "", status_code=200
        )


async def form_validation_error_handler(request: Request, exc: FormValidationError):
    return exc.response


T = TypeVar("T", bound=BaseForm)


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
        template: Callable[[type[T], dict, dict], Awaitable[Any]],
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
            html_result = await self.template(self.model, values, errors)
            content = await render_html(html_result)
            raise FormValidationError(content)


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
    return Response(status_code=200, headers={"HX-Redirect": url})


def htmx_refresh() -> Response:
    """Trigger full page refresh via HTMX."""
    return Response(status_code=200, headers={"HX-Refresh": "true"})


def htmx_retarget(content: SafeHTML, target: str) -> Response:
    """Return content with retargeted swap."""
    return Response(content=content.content, headers={"HX-Retarget": target})


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
    return Response(content=content.content, headers={header: event})
