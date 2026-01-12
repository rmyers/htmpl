"""
htmpl - Type-safe HTML templating using Python 3.14 t-strings

A minimal, React-inspired templating library that leverages PEP 750
template strings for type-safe, composable HTML generation.
"""

from .core import (
    AsyncRenderable,
    Renderable,
    SafeHTML,
    attr,
    cached,
    cached_lru,
    cached_ttl,
    html,
    raw,
    render_html,
)
from .elements import Element, Fragment, fragment
from .components import (
    Document,
    Page,
    Nav,
    Card,
    Form,
    Field,
    Button,
    Alert,
    Modal,
    Table,
    Grid,
)
from .forms import (
    BaseForm,
    FieldConfig,
    parse_form_errors,
)

__version__ = "0.1.0"
__all__ = [
    # Core
    "AsyncRenderable",
    "Renderable",
    "SafeHTML",
    "attr",
    "cached",
    "cached_lru",
    "cached_ttl",
    "html",
    "raw",
    "render_html",
    # Elements
    "Element",
    "Fragment",
    "fragment",
    # Components
    "Document",
    "Page",
    "Nav",
    "Card",
    "Form",
    "Field",
    "Button",
    "Alert",
    "Modal",
    "Table",
    "Grid",
    # Forms
    "BaseForm",
    "FieldConfig",
    "parse_form_errors",
]
