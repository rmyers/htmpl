"""
Core async template processing engine.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterable, Awaitable, Iterable
from dataclasses import dataclass
from functools import wraps
from html import escape
from inspect import isasyncgen, isawaitable
from string.templatelib import Template, Interpolation
from typing import Protocol, runtime_checkable, Any, Callable, TypeVar


@runtime_checkable
class Renderable(Protocol):
    """Protocol for objects that can render themselves as HTML."""

    def __html__(self) -> str: ...


@runtime_checkable
class AsyncRenderable(Protocol):
    """Protocol for objects that render asynchronously."""

    async def __html__(self) -> str: ...


@dataclass(frozen=True, slots=True)
class SafeHTML:
    """
    Marks content as already escaped/safe.
    Immutable and hashable for use as cache keys.
    """

    content: str

    def __html__(self) -> str:
        return self.content

    def __str__(self) -> str:
        return self.content

    def __bool__(self) -> bool:
        return bool(self.content)

    def __add__(self, other: SafeHTML | str) -> SafeHTML:
        if isinstance(other, SafeHTML):
            return SafeHTML(self.content + other.content)
        return SafeHTML(self.content + escape(str(other)))

    def __radd__(self, other: SafeHTML | str) -> SafeHTML:
        if isinstance(other, SafeHTML):
            return SafeHTML(other.content + self.content)
        return SafeHTML(escape(str(other)) + self.content)


def raw(content: str) -> SafeHTML:
    """Mark a string as safe/pre-escaped HTML. Use with caution."""
    return SafeHTML(content)


def attr(name: str, value: str | bool | None) -> SafeHTML:
    """
    Build a safe HTML attribute.

    - None or False: returns empty (attribute omitted)
    - True: returns just the attribute name (boolean attribute)
    - str: returns name="escaped_value"
    """
    if value is None or value is False:
        return SafeHTML("")
    if value is True:
        return SafeHTML(name)
    return SafeHTML(f'{name}="{escape(str(value))}"')


async def html(template: Template) -> SafeHTML:
    """
    Process a t-string template into escaped HTML.

    Automatically awaits coroutines and async iterables found in interpolations.
    """
    parts: list[str] = []

    for item in template:
        match item:
            case str() as text:
                parts.append(text)
            case Interpolation(value, _, conversion, format_spec):
                rendered = await _render_value(value, conversion, format_spec)
                parts.append(rendered)

    return SafeHTML("".join(parts).strip())


async def _render_value(value: Any, conversion: str | None, format_spec: str) -> str:
    """Render a single interpolated value, awaiting if necessary."""

    # Await coroutines first
    if isawaitable(value):
        value = await value

    # None renders as nothing
    if value is None:
        return ""

    # Renderable objects (sync or async)
    if hasattr(value, "__html__"):
        result = value.__html__()
        if isawaitable(result):
            return await result
        return result

    # Nested templates
    if isinstance(value, Template):
        result = await html(value)
        return result.__html__()

    # Async iterables (async generators, etc.)
    if isasyncgen(value) or isinstance(value, AsyncIterable):
        parts = []
        async for item in value:
            parts.append(await _render_value(item, None, ""))
        return "".join(parts)

    # Sync iterables (except strings/bytes)
    if isinstance(value, Iterable) and not isinstance(value, (str, bytes)):
        parts = []
        for item in value:
            parts.append(await _render_value(item, None, ""))
        return "".join(parts)

    # Apply conversion
    if conversion == "r":
        value = repr(value)
    elif conversion == "s":
        value = str(value)
    elif conversion == "a":
        value = ascii(value)

    # Apply format spec
    if format_spec:
        value = format(value, format_spec)

    # Escape and return
    return escape(str(value))


# Async caching utilities

T = TypeVar("T")


def cached(func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
    """
    Cache an async component forever. Use for static content.

    Usage:
        @cached
        async def Footer() -> SafeHTML:
            return await html(t'<footer>...</footer>')
    """
    cache: dict[tuple, T] = {}

    @wraps(func)
    async def wrapper(*args, **kwargs) -> T:
        key = (args, tuple(sorted(kwargs.items())))
        if key not in cache:
            cache[key] = await func(*args, **kwargs)
        return cache[key]

    wrapper.cache_clear = lambda: cache.clear()
    return wrapper


def cached_lru(maxsize: int = 128):
    """
    Cache an async component with LRU eviction.

    Usage:
        @cached_lru(maxsize=64)
        async def UserBadge(role: str) -> SafeHTML:
            ...
    """

    def decorator(func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        from collections import OrderedDict

        cache: OrderedDict[tuple, T] = OrderedDict()

        @wraps(func)
        async def wrapper(*args, **kwargs) -> T:
            key = (args, tuple(sorted(kwargs.items())))
            if key in cache:
                cache.move_to_end(key)
                return cache[key]

            result = await func(*args, **kwargs)
            cache[key] = result

            while len(cache) > maxsize:
                cache.popitem(last=False)

            return result

        wrapper.cache_clear = lambda: cache.clear()
        wrapper.cache_info = lambda: {"size": len(cache), "maxsize": maxsize}
        return wrapper

    return decorator


def cached_ttl(seconds: int = 300):
    """
    Cache an async component with TTL expiration.

    Usage:
        @cached_ttl(seconds=60)
        async def GlobalStats() -> SafeHTML:
            stats = await fetch_expensive_stats()
            ...
    """
    import time

    def decorator(func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        cache: dict[tuple, tuple[float, T]] = {}

        @wraps(func)
        async def wrapper(*args, **kwargs) -> T:
            key = (args, tuple(sorted(kwargs.items())))
            now = time.monotonic()

            if key in cache:
                expires, value = cache[key]
                if now < expires:
                    return value

            result = await func(*args, **kwargs)
            cache[key] = (now + seconds, result)
            return result

        wrapper.cache_clear = lambda: cache.clear()
        return wrapper

    return decorator
