"""Asset registration and bundling system."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable, Protocol, cast, runtime_checkable
import hashlib
import json
import os
import subprocess
import shutil
import logging

from .core import SafeHTML

BUNDLE_DIR = Path(os.environ.get("HTMPL_BUNDLE_DIR", "static/bundles"))
PREBUILT = os.environ.get("HTMPL_PREBUILT") == "1"
MINIFY = os.environ.get("HTMPL_MINIFY", "1") == "1"

# Check for esbuild binary
ESBUILD = shutil.which("esbuild")

_components: dict[str, "Component"] = {}
_pages: dict[str, "Page"] = {}
_manifest: dict | None = None

logger = logging.getLogger(__name__)


@runtime_checkable
class ComponentFunc(Protocol):
    """
    Protocol for decorated component functions.

    Components must be decorated with @component to be used in page(uses={...}).
    """

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

    @component(
        css={"/static/css/account.css"},
        uses={dropdown},  # Reference other components directly
    )
    async def account_menu(user): ...
    """

    def decorator(fn: Callable) -> ComponentFunc:
        comp_name = name or fn.__name__

        # Resolve component references to names
        imports: set[str] = set()
        for comp in uses or set():
            if not callable(comp):
                raise TypeError(f"Expected a component function, got {type(comp).__name__}")
            dep_name = getattr(comp, "_htmpl_component", None)
            if dep_name is None:
                raise TypeError(
                    f"'{type(comp).__name__}' is not a registered component. "
                    f"Add the @component decorator to register it."
                )
            imports.add(dep_name)

        _components[comp_name] = Component(
            name=comp_name,
            css=css or set(),
            js=js or set(),
            py=py or set(),
            imports=imports,
        )
        fn = cast(ComponentFunc, fn)
        fn._htmpl_component = comp_name
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


def _bundle_with_esbuild(files: list[Path], outfile: Path) -> bool:
    """Bundle files using esbuild. Returns True on success."""
    try:
        cmd = [
            ESBUILD,
            *[str(f) for f in files],
            "--bundle",
            f"--outfile={outfile}",
        ]
        if MINIFY:
            cmd.append("--minify")
        subprocess.run(cmd, check=True, capture_output=True)
        return True
    except subprocess.CalledProcessError as exc:
        logger.warning(f"esbuild failed: {exc.stderr} {exc.stdout}")
        return False


def create_bundle(files: set[str], ext: str) -> str | None:
    """Create a bundled file from a set of source files."""
    if not files:
        return None

    BUNDLE_DIR.mkdir(parents=True, exist_ok=True)

    prefix = {"css": "styles", "js": "scripts", "py": "pyscripts"}[ext]

    # Resolve local file paths
    local_files: list[Path] = []
    file_names: list[str] = []
    for f in sorted(files):
        p = Path(f.lstrip("/"))
        if p.exists():
            local_files.append(p)
            # store the name and modify time to generate hash
            file_names.append(f"{p.name}-{p.stat().st_mtime}")

    if not local_files:
        return None

    file_hash = _hash(":".join(file_names))
    filename = f"{prefix}-{file_hash}.{ext}"
    path = BUNDLE_DIR / filename
    # TODO(rmyers): this needs to be configurable
    final_path = f"/static/bundles/{filename}"

    if path.exists():
        return final_path

    # Try esbuild for CSS/JS
    if ext in ("css", "js") and ESBUILD:
        logger.info("building...")

        if _bundle_with_esbuild(local_files, path):
            return final_path

    _fallback_bundle(local_files, path)
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
