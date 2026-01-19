"""
htmpl - Type-safe HTML templating using Python 3.14 t-strings

A minimal, React-inspired templating library that leverages PEP 750
template strings for type-safe, composable HTML generation.
"""

from tdom import html
from .core import (
    SafeHTML,
    render_html,
)
from .forms import (
    BaseForm,
    FieldConfig,
    parse_form_errors,
)

__version__ = "0.1.0"
__all__ = [
    # TDOM re-export
    "html",
    # Core
    "SafeHTML",
    "render_html",
    # Forms
    "BaseForm",
    "FieldConfig",
    "parse_form_errors",
]
