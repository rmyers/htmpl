"""
HTMX attribute helpers and async components.
"""

from __future__ import annotations

from typing import Literal
from dataclasses import dataclass, field

from .core import html, SafeHTML, cached


Swap = Literal[
    "innerHTML", "outerHTML", "beforebegin", "afterbegin", "beforeend", "afterend", "delete", "none"
]


@dataclass
class HX:
    """
    HTMX attribute builder.

    Usage:
        hx = HX(get="/api/data", target="#results", swap="innerHTML")
        await html(t'<button {hx}>Load</button>')
    """

    get: str | None = None
    post: str | None = None
    put: str | None = None
    patch: str | None = None
    delete: str | None = None
    target: str | None = None
    swap: Swap | None = None
    trigger: str | None = None
    push_url: bool | str | None = None
    select: str | None = None
    select_oob: str | None = None
    swap_oob: str | None = None
    include: str | None = None
    vals: str | None = None
    confirm: str | None = None
    disable: bool = False
    disabled_elt: str | None = None
    indicator: str | None = None
    boost: bool = False
    preserve: bool = False
    sync: str | None = None
    params: str | None = None
    encoding: str | None = None
    ext: str | None = None
    headers: str | None = None
    history: bool | None = None
    history_elt: bool = False
    on: dict[str, str] = field(default_factory=dict)

    def __str__(self) -> str:
        attrs: list[str] = []

        if self.get:
            attrs.append(f'hx-get="{self.get}"')
        if self.post:
            attrs.append(f'hx-post="{self.post}"')
        if self.put:
            attrs.append(f'hx-put="{self.put}"')
        if self.patch:
            attrs.append(f'hx-patch="{self.patch}"')
        if self.delete:
            attrs.append(f'hx-delete="{self.delete}"')
        if self.target:
            attrs.append(f'hx-target="{self.target}"')
        if self.swap:
            attrs.append(f'hx-swap="{self.swap}"')
        if self.trigger:
            attrs.append(f'hx-trigger="{self.trigger}"')
        if self.push_url is True:
            attrs.append('hx-push-url="true"')
        elif self.push_url:
            attrs.append(f'hx-push-url="{self.push_url}"')
        if self.select:
            attrs.append(f'hx-select="{self.select}"')
        if self.select_oob:
            attrs.append(f'hx-select-oob="{self.select_oob}"')
        if self.swap_oob:
            attrs.append(f'hx-swap-oob="{self.swap_oob}"')
        if self.include:
            attrs.append(f'hx-include="{self.include}"')
        if self.vals:
            attrs.append(f'hx-vals="{self.vals}"')
        if self.confirm:
            attrs.append(f'hx-confirm="{self.confirm}"')
        if self.disable:
            attrs.append("hx-disable")
        if self.disabled_elt:
            attrs.append(f'hx-disabled-elt="{self.disabled_elt}"')
        if self.indicator:
            attrs.append(f'hx-indicator="{self.indicator}"')
        if self.boost:
            attrs.append('hx-boost="true"')
        if self.preserve:
            attrs.append('hx-preserve="true"')
        if self.sync:
            attrs.append(f'hx-sync="{self.sync}"')
        if self.params:
            attrs.append(f'hx-params="{self.params}"')
        if self.encoding:
            attrs.append(f'hx-encoding="{self.encoding}"')
        if self.ext:
            attrs.append(f'hx-ext="{self.ext}"')
        if self.headers:
            attrs.append(f'hx-headers="{self.headers}"')
        if self.history is not None:
            attrs.append(f'hx-history="{str(self.history).lower()}"')
        if self.history_elt:
            attrs.append("hx-history-elt")
        for event, handler in self.on.items():
            attrs.append(f'hx-on:{event}="{handler}"')

        return " ".join(attrs)

    def __html__(self) -> str:
        return str(self)


@cached
async def HtmxScripts(*, debug: bool = False) -> SafeHTML:
    """HTMX script tag."""
    ext = "" if not debug else ".js"
    return await html(
        t'<script src="https://unpkg.com/htmx.org@2.0.4/dist/htmx.min{ext}"></script>'
    )


async def HtmxExtension(name: str) -> SafeHTML:
    """Load an HTMX extension."""
    return await html(t'<script src="https://unpkg.com/htmx-ext-{name}@2.0.4/{name}.js"></script>')


# Common HTMX patterns


async def LoadingButton(
    children: SafeHTML | str,
    *,
    post: str,
    target: str = "this",
    swap: Swap = "outerHTML",
    indicator: str | None = None,
    disabled_elt: str = "this",
    confirm: str | None = None,
) -> SafeHTML:
    """Button that shows loading state during request."""
    hx = HX(
        post=post,
        target=target,
        swap=swap,
        indicator=indicator,
        disabled_elt=disabled_elt,
        confirm=confirm,
    )
    return await html(t'<button type="button" {hx}>{children}</button>')


async def InfiniteScroll(
    src: str,
    *,
    target: str = "this",
    swap: Swap = "afterend",
    trigger: str = "revealed",
) -> SafeHTML:
    """Infinite scroll trigger element."""
    hx = HX(get=src, target=target, swap=swap, trigger=trigger)
    return await html(t"<div {hx}></div>")


async def LazyLoad(
    src: str,
    *,
    placeholder: SafeHTML | None = None,
    trigger: str = "load",
) -> SafeHTML:
    """Lazy loaded content."""
    hx = HX(get=src, trigger=trigger, swap="outerHTML")
    inner = placeholder or await html(t'<span aria-busy="true">Loading...</span>')
    return await html(t"<div {hx}>{inner}</div>")


async def PollingContent(
    src: str,
    *,
    interval: int = 5,
    children: SafeHTML | None = None,
) -> SafeHTML:
    """Content that polls for updates."""
    hx = HX(get=src, trigger=f"every {interval}s", swap="innerHTML")
    return await html(t"<div {hx}>{children}</div>")


async def SearchInput(
    name: str,
    *,
    src: str,
    target: str,
    placeholder: str = "Search...",
    debounce: int = 300,
) -> SafeHTML:
    """Search input with debounced requests."""
    hx = HX(
        get=src,
        target=target,
        trigger=f"input changed delay:{debounce}ms, search",
        swap="innerHTML",
    )
    return await html(t'<input type="search" name="{name}" placeholder="{placeholder}" {hx}>')


async def OobSwap(id: str, children: SafeHTML, *, swap: Swap = "innerHTML") -> SafeHTML:
    """Out-of-band swap container."""
    return await html(t'<div id="{id}" hx-swap-oob="{swap}">{children}</div>')
