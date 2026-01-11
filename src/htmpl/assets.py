"""Asset registration and bundling system."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable, Protocol, TypeAlias, cast, runtime_checkable
import hashlib
import json
import os
import subprocess
import shutil
import logging
import time

from .core import SafeHTML

BUNDLE_DIR = Path(os.environ.get("HTMPL_BUNDLE_DIR", "static/bundles"))
PREBUILT = os.environ.get("HTMPL_PREBUILT") == "1"
MINIFY = os.environ.get("HTMPL_MINIFY", "1") == "1"

ESBUILD = shutil.which("esbuild")

logger = logging.getLogger(__name__)


@runtime_checkable
class ComponentFunc(Protocol):
    """Protocol for decorated component functions."""

    _htmpl_component: str

    def __call__(self, *args, **kwargs) -> Awaitable[SafeHTML]: ...


# --- Data Classes ---


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


# --- Types ---


class LayoutRenderer(Protocol):
    """Protocol for layout render functions."""

    def __call__(
        self, content: SafeHTML, title: str, bundles: Bundles
    ) -> Awaitable[SafeHTML]: ...


LayoutFunc: TypeAlias = Callable[[SafeHTML, str, Bundles], Awaitable[SafeHTML]]


# --- Registry ---


class Registry:
    """
    Singleton registry for components, layouts, and pages.

    Usage:
        from htmpl.assets import registry

        # Register
        registry.add_component(comp)
        registry.add_page(page)

        # Retrieve
        comp = registry.get_component("name")
        pages = registry.pages
    """

    _instance: "Registry | None" = None
    _components: dict[str, Component]
    _layouts: dict[str, Component]
    _pages: dict[str, Page]
    _manifest: dict | None

    def __new__(cls) -> "Registry":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._components = {}
            cls._instance._layouts = {}
            cls._instance._pages = {}
            cls._instance._manifest = None
        return cls._instance

    @property
    def components(self) -> dict[str, Component]:
        return self._components.copy()

    @property
    def layouts(self) -> dict[str, Component]:
        return self._layouts.copy()

    @property
    def pages(self) -> dict[str, Page]:
        return self._pages.copy()

    def add_component(self, comp: Component) -> None:
        self._components[comp.name] = comp

    def add_layout(self, comp: Component) -> None:
        self._components[comp.name] = comp
        self._layouts[comp.name] = comp

    def add_page(self, page: Page) -> None:
        self._pages[page.name] = page

    def get_component(self, name: str) -> Component | None:
        return self._components.get(name)

    def get_layout(self, name: str) -> Component | None:
        return self._layouts.get(name)

    def get_page(self, name: str) -> Page | None:
        return self._pages.get(name)

    def clear(self) -> None:
        """Clear all registrations. Useful for testing."""
        self._components.clear()
        self._layouts.clear()
        self._pages.clear()
        self._manifest = None


# Global singleton instance
registry = Registry()


# --- Asset Collection ---


@dataclass
class AssetCollector:
    """Collects assets from rendered components during a request."""

    css: set[str] = field(default_factory=set)
    js: set[str] = field(default_factory=set)
    py: set[str] = field(default_factory=set)
    _seen: set[str] = field(default_factory=set)

    def add(self, comp_name: str) -> None:
        """Register a component's assets. Idempotent."""
        if comp_name in self._seen:
            return
        self._seen.add(comp_name)

        comp = registry.get_component(comp_name)
        if comp:
            self.css |= comp.css
            self.js |= comp.js
            self.py |= comp.py

    def bundles(self) -> Bundles:
        """Generate bundles from collected assets."""
        return Bundles(
            css=create_bundle(self.css, "css"),
            js=create_bundle(self.js, "js"),
            py=create_bundle(self.py, "py"),
        )


@dataclass
class PageContext:
    """Runtime page context with asset collection and layout."""

    name: str
    title: str
    layout: LayoutFunc | None = None
    assets: AssetCollector = field(default_factory=AssetCollector)
    _bundles: Bundles | None = field(default=None, repr=False)

    @property
    def bundles(self) -> Bundles:
        """Lazily generate bundles from collected assets."""
        if self._bundles is None:
            self._bundles = self.assets.bundles()
        return self._bundles

    async def render(self, content: SafeHTML) -> SafeHTML:
        """Render content through the page's layout."""
        if self.layout is None:
            return content
        return await self.layout(content, self.title, self.bundles)


# --- Decorators ---


def component(
    name: str | None = None,
    *,
    css: set[str] | None = None,
    js: set[str] | None = None,
    py: set[str] | None = None,
    uses: set[ComponentFunc] | None = None,
):
    """
    Register a component with its assets and dependencies.

    @component(
        css={"/static/css/dropdown.css"},
        py={"/static/py/dropdown.py"},
    )
    async def dropdown(trigger, items): ...
    """

    def decorator(fn: Callable) -> ComponentFunc:
        comp_name = name or fn.__name__

        imports: set[str] = set()
        for comp in uses or set():
            if not callable(comp):
                raise TypeError(
                    f"Expected a component function, got {type(comp).__name__}"
                )
            dep_name = getattr(comp, "_htmpl_component", None)
            if dep_name is None:
                raise TypeError(
                    f"'{type(comp).__name__}' is not a registered component. "
                    f"Add the @component decorator to register it."
                )
            imports.add(dep_name)

        registry.add_component(
            Component(
                name=comp_name,
                css=css or set(),
                js=js or set(),
                py=py or set(),
                imports=imports,
            )
        )
        fn = cast(ComponentFunc, fn)
        fn._htmpl_component = comp_name
        return fn

    return decorator


def layout(
    name: str | None = None,
    *,
    css: set[str] | None = None,
    js: set[str] | None = None,
    py: set[str] | None = None,
):
    """
    Register a layout with its assets.

    Layouts are components that return a renderer function.

    @layout(css={"/static/app.css"})
    async def AppLayout(
        nav: Annotated[SafeHTML, use_component(NavBar)],
    ):
        async def render(content: SafeHTML, title: str, bundles: Bundles) -> SafeHTML:
            return await html(t'...')
        return render
    """

    def decorator(fn: Callable) -> Callable:
        layout_name = name or fn.__name__

        registry.add_layout(
            Component(
                name=layout_name,
                css=css or set(),
                js=js or set(),
                py=py or set(),
            )
        )

        fn._htmpl_layout = layout_name
        return fn

    return decorator


# --- Resolution ---


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

    comp = registry.get_component(comp_name)
    if not comp:
        return ResolvedAssets()

    assets = ResolvedAssets()

    for imp in comp.imports:
        assets.merge(resolve_component(imp, seen))

    assets.css |= comp.css
    assets.js |= comp.js
    assets.py |= comp.py

    return assets


def resolve_page(page_name: str) -> ResolvedAssets:
    """Resolve all assets for a page including all imported components."""
    page_def = registry.get_page(page_name)
    if not page_def:
        return ResolvedAssets()

    assets = ResolvedAssets()
    seen: set[str] = set()

    if page_def.layout:
        assets.merge(resolve_component(page_def.layout, seen))

    for imp in page_def.imports:
        assets.merge(resolve_component(imp, seen))

    assets.css |= page_def.css
    assets.js |= page_def.js
    assets.py |= page_def.py

    return assets


# --- Bundling ---


def _hash(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()[:12]


def _bundle_with_esbuild(files: list[Path], outfile: Path, ext: str) -> bool:
    """Bundle files using esbuild. Returns True on success."""
    entry = outfile.with_suffix(f".entry.{ext}")
    try:
        if ext == "css":
            imports = "\n".join(f'@import "{f.resolve()}";' for f in files)
        else:
            imports = "\n".join(f'import "{f.resolve()}";' for f in files)

        entry.write_text(imports)

        cmd = [
            ESBUILD,
            str(entry),
            "--bundle",
            f"--outfile={outfile}",
            "--external:*.png",
            "--external:*.jpg",
            "--external:*.gif",
            "--external:*.svg",
            "--external:*.woff",
            "--external:*.woff2",
        ]
        if MINIFY:
            cmd.append("--minify")
        subprocess.run(cmd, check=True, capture_output=True)
        entry.unlink()
        return True
    except subprocess.CalledProcessError as exc:
        logger.warning(f"esbuild failed: {exc.stderr} {exc.stdout}")
        if entry.exists():
            entry.unlink()
        return False


def create_bundle(files: set[str], ext: str) -> str | None:
    """Create a bundled file from a set of source files."""
    if not files:
        return None

    BUNDLE_DIR.mkdir(parents=True, exist_ok=True)

    prefix = {"css": "styles", "js": "scripts", "py": "pyscripts"}[ext]

    local_files: list[Path] = []
    file_names: list[str] = []
    for f in sorted(files):
        p = Path(f.lstrip("/"))
        if p.exists():
            local_files.append(p)
            file_names.append(f"{p.name}-{p.stat().st_mtime}")

    if not local_files:
        return None

    file_hash = _hash(":".join(file_names))
    filename = f"{prefix}-{file_hash}.{ext}"
    path = BUNDLE_DIR / filename
    final_path = f"/static/bundles/{filename}"

    if path.exists():
        return final_path

    logger.info(f"building: {filename} from: {file_names}")
    start_time = time.perf_counter()

    if ext in ("css", "js") and ESBUILD:
        if _bundle_with_esbuild(local_files, path, ext):
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            logger.info(f"built with esbuild in {elapsed_ms:.1f}ms")
            return final_path

    _fallback_bundle(local_files, path)
    elapsed_ms = (time.perf_counter() - start_time) * 1000
    logger.info(f"built with fallback in {elapsed_ms:.1f}ms")
    return final_path


def _fallback_bundle(files: list[Path], outfile: Path) -> None:
    """Manual concatenation fallback when esbuild unavailable."""
    parts = [f.read_text() for f in files]
    outfile.write_text("\n\n".join(parts))


def bundle_page(page_name: str) -> Bundles:
    """Create all bundles for a page."""
    assets = resolve_page(page_name)
    return Bundles(
        css=create_bundle(assets.css, "css"),
        js=create_bundle(assets.js, "js"),
        py=create_bundle(assets.py, "py"),
    )


# --- Manifest ---


def save_manifest() -> None:
    """Save all page bundles to manifest."""
    BUNDLE_DIR.mkdir(parents=True, exist_ok=True)
    data = {"pages": {}}
    for name in registry.pages:
        bundles = bundle_page(name)
        data["pages"][name] = bundles.to_dict()
    (BUNDLE_DIR / "manifest.json").write_text(json.dumps(data, indent=2))


def load_manifest() -> dict | None:
    """Load manifest from disk (cached)."""
    if registry._manifest is None:
        path = BUNDLE_DIR / "manifest.json"
        registry._manifest = (
            json.loads(path.read_text()) if path.exists() else {"pages": {}}
        )
    return registry._manifest


def get_bundles(page_name: str) -> Bundles:
    """Get bundles for a page - from manifest if prebuilt, else generate."""
    if PREBUILT:
        if manifest := load_manifest():
            data = manifest.get("pages", {}).get(page_name, {})
            return Bundles(css=data.get("css"), js=data.get("js"), py=data.get("py"))
    return bundle_page(page_name)
