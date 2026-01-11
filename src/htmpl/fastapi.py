"""FastAPI integration with component DI and automatic asset registration."""

from __future__ import annotations

import inspect
from inspect import isawaitable
from string.templatelib import Template
from typing import (
    Any,
    Awaitable,
    Callable,
    Generic,
    TypeVar,
)

from fastapi import Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import ValidationError

from .assets import (
    registry,
    Bundles,
    ComponentFunc,
    LayoutFunc,
    Page,
    get_bundles,
)
from .core import SafeHTML, html
from .forms import BaseForm, parse_form_errors

# --- Page Renderer ---


class PageRenderer:
    """
    Renders page content through a layout with pre-resolved assets.

    Usage:
        @router.get("/")
        async def home(page: Annotated[PageRenderer, page("home", layout=AppLayout)]):
            content = section(h1("Welcome"))
            return await page.render(content)
    """

    def __init__(
        self,
        name: str,
        title: str,
        layout: LayoutFunc | None,
    ):
        self.name = name
        self.title = title
        self.layout = layout
        self._bundles: Bundles | None = None

    @property
    def bundles(self) -> Bundles:
        """Lazily generate bundles on first access."""
        if self._bundles is None:
            self._bundles = get_bundles(self.name)
        return self._bundles

    async def render(self, content: Any) -> HTMLResponse:
        """Render content through layout and return HTMLResponse."""
        rendered = await render_html(content)
        if rendered is None:
            rendered = SafeHTML(str(content))

        if self.layout:
            final = await self.layout(rendered, self.title, self.bundles)
            return HTMLResponse(final.content)

        return HTMLResponse(rendered.content)


# --- Page Dependency ---


def page(
    name: str,
    *,
    title: str = "Page",
    layout: Callable | None = None,
    uses: set[ComponentFunc] | None = None,
):
    """
    Page dependency that returns a PageRenderer.

    Assets are resolved statically via the layout's `uses={}` dependencies.

    Usage:
        @router.get("/")
        async def home(page: Annotated[PageRenderer, page("home", layout=AppLayout)]):
            return await page.render(section(h1("Welcome")))
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
            return PageRenderer(
                name=name,
                title=title,
                layout=resolved_layout,
            )

        setup.__signature__ = inspect.Signature(parameters=params)  # type: ignore
        return Depends(setup)

    else:

        def setup_simple(request: Request) -> PageRenderer:
            return PageRenderer(
                name=name,
                title=title,
                layout=layout,
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

        @layout()
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


# --- Helpers ---


async def render_html(result: Any) -> SafeHTML | None:
    """Render an Element/SafeHTML/Template to SafeHTML."""
    if isinstance(result, SafeHTML):
        return result

    if isinstance(result, Template):
        return await html(result)

    if isawaitable(result):
        content = await result
        return await render_html(content)

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
        template: Callable[[type[T], dict, dict], Awaitable[SafeHTML]],
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
