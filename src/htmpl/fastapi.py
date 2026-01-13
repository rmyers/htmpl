"""FastAPI integration with component DI and automatic asset registration."""

from __future__ import annotations

import inspect
from typing import Any, Awaitable, Callable, Generic, TypeVar

from fastapi import Depends, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, ValidationError

from .assets import (
    registry,
    AssetCollector,
    Bundles,
    ComponentFunc,
)
from .core import SafeHTML, render_html
from .forms import BaseForm, parse_form_errors


T = TypeVar("T", bound=BaseForm)


# --- Page Renderer ---


class PageRenderer(Generic[T]):
    """Renders page content through a layout with collected assets."""

    def __init__(
        self,
        layout: Callable[..., Awaitable[SafeHTML]],
        request: Request,
        *,
        form_class: type[T] | None = None,
        data: T | None = None,
        values: dict | None = None,
        errors: dict[str, str] | None = None,
    ):
        self.layout = layout
        self.request = request
        self.form_class = form_class
        self.data = data
        self.values = values or {}
        self.errors = errors or {}

    @property
    def collector(self) -> AssetCollector | None:
        """Get the request's asset collector (if any)."""
        return getattr(self.request.state, "htmpl_collector", None)

    @property
    def bundles(self) -> Bundles:
        """Resolve collected assets to bundles."""
        if self.collector:
            return self.collector.bundles()
        return Bundles()

    @property
    def is_htmx(self) -> bool:
        return self.request.headers.get("HX-Request") == "true"

    async def __call__(self, content: Any, **kwargs) -> HTMLResponse:
        """Render content through layout and return HTMLResponse."""
        laid_out = await self.layout(content, self.bundles, **kwargs)
        return await render_html(laid_out)

    async def form_error(
        self,
        template: Callable[[type[T], dict, dict[str, str]], Any],
        **kwargs,
    ) -> HTMLResponse:
        if self.form_class is None:
            raise ValueError("No form class configured for this page")
        content = await template(self.form_class, self.values, self.errors)
        return await self(content, **kwargs)

    def redirect(self, url: str, *, status_code: int = 303) -> Response:
        if self.is_htmx:
            return Response(status_code=200, headers={"HX-Redirect": url})
        return RedirectResponse(url=url, status_code=status_code)

    def refresh(self) -> Response:
        if self.is_htmx:
            return Response(status_code=200, headers={"HX-Refresh": "true"})
        return RedirectResponse(url=str(self.request.url), status_code=303)


# --- Form Parsing ---


class ParsedForm(BaseModel, Generic[T]):
    data: T | None = None
    values: dict
    errors: dict


async def parse_form(request: Request, form: type[T] | None) -> ParsedForm[T]:
    if form is not None and request.method in ("POST", "PUT", "PATCH"):
        form_data = await request.form()
        values = dict(form_data)

        for field_name, cfg in form.get_field_configs().items():
            if cfg.widget == "checkbox" and field_name in form_data:
                values[field_name] = True  # type: ignore

        try:
            data = form.model_validate(values)
            errors = {}
        except ValidationError as e:
            errors = parse_form_errors(e)
            data = None

        return ParsedForm(data=data, values=values, errors=errors)

    return ParsedForm(data=None, values={}, errors={})


# --- use_layout Dependency ---


def use_layout(
    layout_fn: Callable,
    *,
    form: type[BaseForm] | None = None,
):
    """
    Layout dependency - sets up asset collector and returns PageRenderer.

    The layout function can depend on other components via use_component.
    It returns a render function whose signature you define.

    Usage:
        @layout(css={"static/app.css"})
        async def AppLayout(nav: Annotated[SafeHTML, use_component(NavBar)]):
            async def render(content: SafeHTML, bundles: Bundles, *, title: str = "Page") -> SafeHTML:
                return await html(t'<html><head>{bundles.head()}</head>...')
            return render

        @router.get("/")
        async def home(page: Annotated[PageRenderer, use_layout(AppLayout)]):
            return await page(section(h1("Welcome")), title="Home")
    """
    layout_name = getattr(layout_fn, "_htmpl_layout", None)
    layout_sig = inspect.signature(layout_fn, eval_str=True)

    params = [
        inspect.Parameter(
            "request", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=Request
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

    async def setup(request: Request, **kwargs) -> PageRenderer:
        # Initialize collector
        collector = AssetCollector()
        request.state.htmpl_collector = collector

        # Register layout's assets
        if layout_name:
            collector.add_by_name(layout_name)

        # Call layout to get renderer
        resolved_layout = await layout_fn(**kwargs)

        # Parse form if configured
        parsed = await parse_form(request, form)

        return PageRenderer(
            layout=resolved_layout,
            request=request,
            form_class=form,
            data=parsed.data,
            values=parsed.values,
            errors=parsed.errors,
        )

    setup.__signature__ = inspect.Signature(parameters=params)
    return Depends(setup)


# --- Component Injection ---


def use_component(
    component: ComponentFunc,
    **fixed_kwargs: Any,
) -> Any:
    """
    FastAPI dependency that renders a component and registers its assets.

    Assets are only collected if a collector exists on request.state,
    so partials/fragments without use_layout() won't collect.

    Usage:
        @component(css={"static/navbar.css"})
        async def NavBar(user: Annotated[User, Depends(get_user)]):
            return await html(t'<nav>Welcome {user.name}</nav>')

        @layout(css={"static/app.css"})
        async def AppLayout(nav: Annotated[SafeHTML, use_component(NavBar)]):
            ...
    """
    comp_name = getattr(component, "_htmpl_component", None)
    if not comp_name:
        raise TypeError(
            f"'{getattr(component, '__name__', component)}' is not a registered component."
        )

    sig = inspect.signature(component, eval_str=True)

    # Build params: Request first, then component's params (minus fixed)
    params = [
        inspect.Parameter(
            "request", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=Request
        )
    ]
    for pname, p in sig.parameters.items():
        if pname in fixed_kwargs:
            continue
        params.append(
            inspect.Parameter(
                pname,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                default=p.default,
                annotation=p.annotation,
            )
        )

    async def render(request: Request, **kwargs) -> SafeHTML | None:
        # Register component's assets if collector exists
        if collector := getattr(request.state, "htmpl_collector", None):
            collector.add_by_name(comp_name)
        return await component(**fixed_kwargs, **kwargs)

    render.__signature__ = inspect.Signature(parameters=params)
    render.__name__ = comp_name

    return Depends(render)
