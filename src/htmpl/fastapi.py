"""FastAPI integration with component DI and automatic asset registration."""

from __future__ import annotations

import inspect
from typing import (
    Any,
    Callable,
    Generic,
    TypeVar,
)

from fastapi import Depends, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, ValidationError

from .assets import (
    registry,
    Bundles,
    ComponentFunc,
    LayoutFunc,
    Page,
    get_bundles,
)
from .core import SafeHTML, html, render_html
from .forms import BaseForm, parse_form_errors


T = TypeVar("T", bound=BaseForm)


# --- Page Renderer ---


class PageRenderer(Generic[T]):
    """
    Renders page content through a layout with pre-resolved assets.

    Usage:
        # Simple page (no form)
        @router.get("/")
        async def home(page: Annotated[PageRenderer, page("home", layout=AppLayout)]):
            return await page(section(h1("Welcome")))

        # Page with form
        @router.post("/settings")
        async def settings_post(
            page: Annotated[PageRenderer[SettingsForm], page("settings", layout=AppLayout, form=SettingsForm)],
        ):
            if page.errors:
                return await page.form_error(settings_template)

            save_settings(page.data)
            return page.redirect("/settings?saved=1")
    """

    def __init__(
        self,
        name: str,
        title: str,
        layout: LayoutFunc | None,
        request: Request,
        *,
        form_class: type[T] | None = None,
        data: T | None = None,
        values: dict | None = None,
        errors: dict[str, str] | None = None,
    ):
        self.name = name
        self.title = title
        self.layout = layout
        self.request = request
        self.form_class = form_class
        self.data = data
        self.values = values or {}
        self.errors = errors or {}
        self._bundles: Bundles | None = None

    @property
    def bundles(self) -> Bundles:
        """Lazily generate bundles on first access."""
        if self._bundles is None:
            self._bundles = get_bundles(self.name)
        return self._bundles

    @property
    def is_htmx(self) -> bool:
        """Check if request is from HTMX."""
        return self.request.headers.get("HX-Request") == "true"

    async def __call__(self, content: Any) -> HTMLResponse:
        """Render content through layout and return HTMLResponse."""
        if self.layout:
            laid_out = await self.layout(content, self.title, self.bundles)
            return await render_html(laid_out)
        return await render_html(content)

    async def form_error(
        self,
        template: Callable[[type[T], dict, dict[str, str]], Any],
    ) -> HTMLResponse:
        """Render the form template with current values and errors."""
        if self.form_class is None:
            raise ValueError("No form class configured for this page")
        content = await template(self.form_class, self.values, self.errors)
        return await self(content)

    def redirect(
        self,
        url: str,
        *,
        status_code: int = 303,  # See Other - correct for POST->GET
    ) -> Response:
        """Redirect after form submission. Auto-detects HTMX."""
        if self.is_htmx:
            return Response(
                status_code=200,
                headers={"HX-Redirect": url},
            )
        return RedirectResponse(url=url, status_code=status_code)

    def refresh(self) -> Response:
        """Refresh the current page. For HTMX or standard redirect."""
        if self.is_htmx:
            return Response(
                status_code=200,
                headers={"HX-Refresh": "true"},
            )
        return RedirectResponse(url=str(self.request.url), status_code=303)


# --- Page Dependency ---
class ParsedForm(BaseModel, Generic[T]):
    data: T | None = None
    values: dict
    errors: dict


async def parse_form(request: Request, form: type[T] | None) -> ParsedForm[T]:
    if form is not None and request.method in ("POST", "PUT", "PATCH"):
        form_data = await request.form()
        values = dict(form_data)

        # Handle checkboxes
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


def page(
    name: str,
    *,
    title: str = "Page",
    layout: Callable | None = None,
    form: type[BaseForm] | None = None,
    uses: set[ComponentFunc] | None = None,
):
    """
    Page dependency that returns a PageRenderer.

    Usage:
        # GET - no form
        @router.get("/settings")
        async def settings_get(
            page: Annotated[PageRenderer, page("settings", layout=AppLayout)],
        ):
            return await page(settings_template(SettingsForm, {}, {}))

        # POST - with form
        @router.post("/settings")
        async def settings_post(
            page: Annotated[PageRenderer[SettingsForm], page("settings", layout=AppLayout, form=SettingsForm)],
        ):
            if page.errors:
                return await page.form_error(settings_template)
            save_settings(page.data)
            return page.redirect("/settings")
    """
    # Register dependencies
    imports: set[str] = set()
    for comp in uses or set():
        if not callable(comp):
            raise TypeError(f"Expected a component function, got {type(comp).__name__}")
        dep_name = getattr(comp, "_htmpl_component", None)
        if dep_name is None:
            raise TypeError(
                f"'{type(comp).__name__}' is not a registered component. "
                f"Add the @component decorator to register it."
            )
        imports.add(dep_name)
    # Register page at import time for pre-building
    layout_name = getattr(layout, "_htmpl_layout", None) if layout else None
    registry.add_page(Page(name=name, title=title, layout=layout_name, imports=imports))

    if layout is not None and hasattr(layout, "_htmpl_layout"):
        layout_sig = inspect.signature(layout, eval_str=True)

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

        async def setup(request: Request, **kwargs) -> PageRenderer:
            resolved_layout = await layout(**kwargs)

            # Parse form if configured
            parsed = await parse_form(request, form)

            return PageRenderer(
                name=name,
                title=title,
                layout=resolved_layout,
                request=request,
                form_class=form,
                data=parsed.data,
                values=parsed.values,
                errors=parsed.errors,
            )

        setup.__signature__ = inspect.Signature(parameters=params)  # type: ignore
        return Depends(setup)

    else:

        async def setup_simple(request: Request) -> PageRenderer:
            # Parse form if configured
            parsed = await parse_form(request, form)

            return PageRenderer(
                name=name,
                title=title,
                layout=layout,
                request=request,
                form_class=form,
                data=parsed.data,
                values=parsed.values,
                errors=parsed.errors,
            )

        return Depends(setup_simple)


# --- Component Injection ---


def use_component(
    component: ComponentFunc,
    **fixed_kwargs: Any,
) -> Any:
    """
    FastAPI dependency that renders a component.

    Components register their assets at decoration time.
    The page's bundle is resolved statically from the dependency tree.

    Usage:
        @component(css={"/static/navbar.css"})
        async def NavBar(user: Annotated[User, Depends(get_user)]):
            return await html(t'<nav>Welcome {user.name}</nav>')

        @layout(uses={NavBar})
        async def AppLayout(nav: Annotated[SafeHTML, use_component(NavBar)]):
            ...
    """
    if not hasattr(component, "_htmpl_component"):
        raise TypeError(
            f"'{getattr(component, '__name__', component)}' is not a registered component. "
            f"Add the @component decorator to register it."
        )

    comp_name = component._htmpl_component
    sig = inspect.signature(component, eval_str=True)

    params = []
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

    async def render(**kwargs) -> SafeHTML | None:
        return await component(**fixed_kwargs, **kwargs)

    render.__signature__ = inspect.Signature(parameters=params)  # type: ignore
    render.__name__ = f"use_{comp_name}"

    return Depends(render)
