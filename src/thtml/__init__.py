"""
thtml - Type-safe HTML templating using Python 3.14 t-strings

A minimal, React-inspired templating library that leverages PEP 750
template strings for type-safe, composable HTML generation.
"""

from .core import (
    html,
    SafeHTML,
    Renderable,
    AsyncRenderable,
    raw,
    attr,
    cached,
    cached_lru,
    cached_ttl,
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

# Optional forms support (requires pydantic)
try:
    from .forms import FormRenderer, FieldConfig, parse_form_errors

    _HAS_FORMS = True
except ImportError:
    _HAS_FORMS = False

__version__ = "0.1.0"
__all__ = [
    # Core
    "html",
    "SafeHTML",
    "Renderable",
    "AsyncRenderable",
    "raw",
    "attr",
    "cached",
    "cached_lru",
    "cached_ttl",
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
]

if _HAS_FORMS:
    __all__ += ["FormRenderer", "FieldConfig", "parse_form_errors"]
