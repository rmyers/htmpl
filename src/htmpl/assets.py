# htmpl/assets.py
"""Asset registration and bundling system."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
import hashlib
import json
import os

BUNDLE_DIR = Path(os.environ.get("HTMPL_BUNDLE_DIR", "static/bundles"))
PREBUILT = os.environ.get("HTMPL_PREBUILT") == "1"

_components: dict[str, "Component"] = {}
_pages: dict[str, "Page"] = {}
_manifest: dict | None = None


@dataclass
class Component:
    """Component definition with its assets and dependencies."""

    name: str
    css: set[str] = field(default_factory=set)
    js: set[str] = field(default_factory=set)
    py: set[str] = field(default_factory=set)
    imports: set[str] = field(default_factory=set)


@dataclass
class Page:
    """Page definition with its assets, dependencies, and metadata."""

    name: str
    title: str
    css: set[str] = field(default_factory=set)
    js: set[str] = field(default_factory=set)
    py: set[str] = field(default_factory=set)
    imports: set[str] = field(default_factory=set)
    layout: str | None = None


def component(
    name: str | None = None,
    *,
    css: set[str] | None = None,
    js: set[str] | None = None,
    py: set[str] | None = None,
    imports: set[str] | None = None,
):
    """
    Register a component with its assets and dependencies.

    @component(
        css={"/static/css/dropdown.css"},
        py={"/static/py/dropdown.py"},
    )
    def dropdown(trigger, items): ...

    @component(
        css={"/static/css/account.css"},
        imports={"dropdown"},
    )
    def account_menu(user): ...
    """

    def decorator(fn: Callable) -> Callable:
        comp_name = name or fn.__name__
        _components[comp_name] = Component(
            name=comp_name,
            css=css or set(),
            js=js or set(),
            py=py or set(),
            imports=imports or set(),
        )
        fn._htmpl_component = comp_name
        return fn

    return decorator


def page(
    title: str = "Page",
    *,
    css: set[str] | None = None,
    js: set[str] | None = None,
    py: set[str] | None = None,
    imports: set[str] | None = None,
    layout: str | None = None,
):
    """
    Register a page with its assets and component dependencies.

    @router.page(
        "/dashboard",
        title="Dashboard",
        css={"/static/css/dashboard.css"},
        imports={"main_nav", "stats_widget"},
    )
    async def dashboard(request): ...
    """

    def decorator(fn: Callable) -> Callable:
        _pages[fn.__name__] = Page(
            name=fn.__name__,
            title=title,
            css=css or set(),
            js=js or set(),
            py=py or set(),
            imports=imports or set(),
            layout=layout,
        )
        fn._htmpl_page = fn.__name__
        return fn

    return decorator


@dataclass
class ResolvedAssets:
    """Collected assets from resolving a component tree."""

    css: set[str] = field(default_factory=set)
    js: set[str] = field(default_factory=set)
    py: set[str] = field(default_factory=set)

    def merge(self, other: "ResolvedAssets") -> None:
        self.css |= other.css
        self.js |= other.js
        self.py |= other.py


def resolve_component(comp_name: str, seen: set[str] | None = None) -> ResolvedAssets:
    """Recursively resolve all assets for a component."""
    seen = seen if seen is not None else set()

    if comp_name in seen:
        return ResolvedAssets()
    seen.add(comp_name)

    comp = _components.get(comp_name)
    if not comp:
        return ResolvedAssets()

    assets = ResolvedAssets()

    # Resolve imports first (depth-first)
    for imp in comp.imports:
        assets.merge(resolve_component(imp, seen))

    # Then add this component's assets
    assets.css |= comp.css
    assets.js |= comp.js
    assets.py |= comp.py

    return assets


def resolve_page(page_name: str) -> ResolvedAssets:
    """Resolve all assets for a page including all imported components."""
    page_def = _pages.get(page_name)
    if not page_def:
        return ResolvedAssets()

    assets = ResolvedAssets()
    seen: set[str] = set()

    # Layout first
    if page_def.layout:
        assets.merge(resolve_component(page_def.layout, seen))

    # Then imported components
    for imp in page_def.imports:
        assets.merge(resolve_component(imp, seen))

    # Finally page-specific assets
    assets.css |= page_def.css
    assets.js |= page_def.js
    assets.py |= page_def.py

    return assets


# --- Bundling ---


def _hash(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()[:12]


def _read(path: str) -> str:
    p = Path(path.lstrip("/"))
    return p.read_text() if p.exists() else ""


@dataclass
class Bundles:
    """Bundle URLs for a page."""

    css: str | None = None
    js: str | None = None
    py: str | None = None

    def head(self) -> str:
        """Generate HTML tags for document head."""
        parts = []
        if self.css:
            parts.append(f'<link rel="stylesheet" href="{self.css}">')
        if self.js:
            parts.append(f'<script src="{self.js}" defer></script>')
        if self.py:
            parts.append(
                '<script type="module" src="https://pyscript.net/releases/2024.11.1/core.js"></script>'
            )
            parts.append(f'<script type="py" src="{self.py}" async></script>')
        return "\n    ".join(parts)

    def to_dict(self) -> dict:
        return {"css": self.css, "js": self.js, "py": self.py}


def create_bundle(files: set[str], name: str, ext: str, header: str = "") -> str | None:
    """Create a bundled file from a set of source files."""
    if not files:
        return None

    BUNDLE_DIR.mkdir(parents=True, exist_ok=True)

    comment = {"css": "/*", "js": "//", "py": "#"}[ext]
    end = " */" if ext == "css" else ""

    parts = [header] if header else []
    for f in sorted(files):  # Sort for deterministic output
        parts.append(f"{comment} {f}{end}\n{_read(f)}")

    content = "\n\n".join(parts)
    filename = f"{name}.{_hash(content)}.{ext}"
    path = BUNDLE_DIR / filename

    if not path.exists():
        path.write_text(content)

    return f"/static/bundles/{filename}"


def bundle_page(page_name: str) -> Bundles:
    """Create all bundles for a page."""
    assets = resolve_page(page_name)

    py_header = "from pyscript import document, when, fetch, window\nfrom pyscript.ffi import create_proxy\n"

    return Bundles(
        css=create_bundle(assets.css, page_name, "css"),
        js=create_bundle(assets.js, page_name, "js"),
        py=create_bundle(assets.py, page_name, "py", py_header),
    )


# --- Manifest ---


def save_manifest() -> None:
    """Save all page bundles to manifest."""
    BUNDLE_DIR.mkdir(parents=True, exist_ok=True)

    data = {"pages": {}}
    for name in _pages:
        bundles = bundle_page(name)
        data["pages"][name] = bundles.to_dict()

    (BUNDLE_DIR / "manifest.json").write_text(json.dumps(data, indent=2))


def load_manifest() -> dict | None:
    """Load manifest from disk (cached)."""
    global _manifest
    if _manifest is None:
        path = BUNDLE_DIR / "manifest.json"
        _manifest = json.loads(path.read_text()) if path.exists() else {"pages": {}}
    return _manifest


def get_bundles(page_name: str) -> Bundles:
    """Get bundles for a page - from manifest if prebuilt, else generate."""
    if PREBUILT:
        if manifest := load_manifest():
            data = manifest.get("pages", {}).get(page_name, {})
            return Bundles(css=data.get("css"), js=data.get("js"), py=data.get("py"))
    return bundle_page(page_name)


# --- Introspection ---


def get_components() -> dict[str, Component]:
    return _components.copy()


def get_pages() -> dict[str, Page]:
    return _pages.copy()
