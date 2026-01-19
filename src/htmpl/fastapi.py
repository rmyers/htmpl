"""FastAPI integration with component DI and automatic asset registration."""

from __future__ import annotations

import inspect
import logging
from pathlib import Path
from typing import (
    Any,
    Generic,
    TypeVar,
)

from fastapi import (
    APIRouter,
    FastAPI,
    Depends,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ValidationError

from .assets import (
    registry,
    AssetCollector,
    Bundles,
    ComponentFunc,
)
from .core import SafeHTML
from .forms import BaseForm, parse_form_errors

logger = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseForm)


def is_htmx(request: Request) -> bool:
    return request.headers.get("HX-Request") == "true"


def use_bundles(request: Request) -> Bundles:
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


class ParsedForm(BaseModel, Generic[T]):
    data: T | None = None
    values: dict
    errors: dict


async def parse_form(request: Request, form: type[T]) -> ParsedForm[T]:
    if request.method in ("POST", "PUT", "PATCH"):
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


def use_form(form: type[T]) -> ParsedForm[T]:
    async def setup(request: Request) -> ParsedForm[T]:
        return await parse_form(request, form)

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
