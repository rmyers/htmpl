"""FastAPI integration with component DI and automatic asset registration."""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import (
    Annotated,
    Any,
    Awaitable,
    Callable,
    Generic,
    TypeVar,
    get_origin,
    get_args,
)

from fastapi import (
    APIRouter,
    FastAPI,
    Depends,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
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


async def use_bundles(request: Request) -> Bundles:
    """Dependency that provides bundles for asset collection.

    Note: This dependency should be added before components

    Usage:
        @layout(css={"static/app.css"}, title="Page")
        async def AppLayout(
            content: SafeHTML,
            bundles: Annotated[Bundles, Depends(use_bundles)],
            nav: Annotated[SafeHTML, use_component(NavBar)],
            title: str,
        ):
            return await html(t'<html><head>{bundles.head}</head>...')
    """
    if not hasattr(request.state, "htmpl_collector"):
        request.state.htmpl_collector = AssetCollector()
    return Bundles(_collector=request.state.htmpl_collector)


class PageRenderer(Generic[T]):
    """Renders page content through a layout with collected assets."""

    def __init__(
        self,
        layout: Callable[..., Awaitable[SafeHTML]],
        request: Request,
        *,
        defaults: dict[str, Any] | None = None,
        resolved_deps: dict[str, Any] | None = None,
        form_class: type[T] | None = None,
        data: T | None = None,
        values: dict | None = None,
        errors: dict[str, str] | None = None,
    ):
        self.layout = layout
        self.request = request
        self.defaults = defaults or {}
        self.resolved_deps = resolved_deps or {}
        self.form_class = form_class
        self.data = data
        self.values = values or {}
        self.errors = errors or {}

    @property
    def collector(self) -> AssetCollector | None:
        """Get the request's asset collector (if any)."""
        return getattr(self.request.state, "htmpl_collector", None)

    @property
    def is_htmx(self) -> bool:
        return self.request.headers.get("HX-Request") == "true"

    async def __call__(self, content: Any, **kwargs) -> HTMLResponse:
        """Render content through layout and return HTMLResponse."""
        # Merge: defaults < resolved_deps < call kwargs
        merged = {**self.defaults, **self.resolved_deps, **kwargs}
        laid_out = await self.layout(content, **merged)
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


def _is_depends(annotation) -> bool:
    """Get Depends from annotation if present."""
    if get_origin(annotation) is Annotated:
        for meta in get_args(annotation)[1:]:
            if type(meta).__name__ == "Depends":
                return True
    return False


def use_layout(
    layout_fn: Callable,
    *,
    form: type[BaseForm] | None = None,
):
    """
    Layout dependency - returns PageRenderer for rendering content through layout.

    The layout function receives content + dependencies + kwargs.
    Dependencies (use_bundles, use_component) are resolved by FastAPI.
    Default kwargs come from the @layout decorator.

    Usage:
        @layout(css={"static/app.css"}, title="Page")
        async def AppLayout(
            content: SafeHTML,
            bundles: Annotated[Bundles, Depends(use_bundles)],
            nav: Annotated[SafeHTML, use_component(NavBar)],
            title: str,
        ):
            return await html(t'<html><head>{await bundles.head()}</head>...')

        @router.get("/")
        async def home(page: Annotated[PageRenderer, use_layout(AppLayout)]):
            return await page(section(h1("Welcome")), title="Home")
    """
    layout_name = getattr(layout_fn, "_htmpl_layout", None)
    defaults = getattr(layout_fn, "_htmpl_defaults", {})
    sig = inspect.signature(layout_fn, eval_str=True)

    params_list = list(sig.parameters.items())

    # First param is content, skip it
    # Collect FastAPI dependencies
    fastapi_params = [
        inspect.Parameter(
            "request", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=Request
        )
    ]

    for pname, p in params_list[1:]:  # Skip content param
        if _is_depends(p.annotation):
            fastapi_params.append(
                inspect.Parameter(
                    pname,
                    inspect.Parameter.POSITIONAL_OR_KEYWORD,
                    default=p.default,
                    annotation=p.annotation,
                )
            )

    async def setup(request: Request, **kwargs) -> PageRenderer:
        # Register layout's assets if collector exists
        if layout_name:
            if collector := getattr(request.state, "htmpl_collector", None):
                collector.add_by_name(layout_name)

        # Parse form if configured
        parsed = await parse_form(request, form)

        return PageRenderer(
            layout=layout_fn,
            request=request,
            defaults=defaults,
            resolved_deps=kwargs,  # use_bundles, use_component results
            form_class=form,
            data=parsed.data,
            values=parsed.values,
            errors=parsed.errors,
        )

    setup.__signature__ = inspect.Signature(parameters=fastapi_params)
    return Depends(setup)


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
        async def AppLayout(
            content: SafeHTML,
            bundles: Annotated[Bundles, use_bundles()],
            nav: Annotated[SafeHTML, use_component(NavBar)],
        ):
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


def add_assets_routes(
    app: FastAPI, assets_path: str = "/assets", bundle_dir: str = "dist/bundles"
) -> FastAPI:
    router = APIRouter()

    @router.websocket("/__hmr")
    async def hmr_websocket(ws: WebSocket):
        if registry._watch_task is None:
            return await ws.close(reason="HMR not enabled")

        await ws.accept()
        registry.add_ws_client(ws)
        try:
            while True:
                await ws.receive_text()
        except WebSocketDisconnect:
            registry.remove_ws_client(ws)

    app.include_router(router)
    app.mount(
        assets_path,
        StaticFiles(directory=Path(bundle_dir), check_dir=False),
        name="assets",
    )

    return app
