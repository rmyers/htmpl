"""
htmpl - Type-safe HTML templating using Python 3.14 t-strings

A minimal, React-inspired templating library that leverages PEP 750
template strings for type-safe, composable HTML generation.
"""

from tdom import html

__all__ = ["html"]

try:
    from .core import SafeHTML, render, render_html
    from .assets import registry, component, Component, ComponentFunc
    from .fastapi import (
        use_bundles,
        use_component,
        use_form,
        add_assets_routes,
        ParsedForm,
    )
    from .forms import BaseForm, parse_form_errors

    __all__ += [
        # core functions
        "SafeHTML",
        "render",
        "render_html",
        # Asset management
        "registry",
        "component",
        "Component",
        "ComponentFunc",
        # FastAPI dependencies
        "use_bundles",
        "use_component",
        "use_form",
        "add_assets_routes",
        # Forms
        "ParsedForm",
        "BaseForm",
        "parse_form_errors",
    ]

except ImportError:
    # Prevent import errors from running the cli commands
    # for example `uvx htmpl init` since we are not guarenteed to have FastAPI installed.
    # probably we should log a message instead?
    # TODO(rmyers): think about refactoring all external deps into a single module
    pass
