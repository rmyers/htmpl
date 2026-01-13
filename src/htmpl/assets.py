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
import time

from .core import SafeHTML

BUNDLE_DIR = Path(os.environ.get("HTMPL_BUNDLE_DIR", "static/bundles"))
PREBUILT = os.environ.get("HTMPL_PREBUILT") == "1"
MINIFY = os.environ.get("HTMPL_MINIFY", "1") == "1"

ESBUILD = shutil.which("esbuild")

logger = logging.getLogger(__name__)


def qualified_name(fn: Callable) -> str:
    """Get fully qualified name for a function."""
    return f"{fn.__module__}.{fn.__name__}"


@runtime_checkable
class ComponentFunc(Protocol):
    """Protocol for decorated component functions."""

    _htmpl_component: str

    def __call__(self, *args, **kwargs) -> Awaitable[SafeHTML]: ...


# --- Data Classes ---


@dataclass
class Component:
    """Component definition with its assets."""

    name: str
    css: set[str] = field(default_factory=set)
    js: set[str] = field(default_factory=set)
    py: set[str] = field(default_factory=set)


@dataclass
class Bundles:
    """Bundle URLs for collected components."""

    _collector: AssetCollector

    async def head(self) -> SafeHTML:
        """Generate HTML tags for document head."""
        from .core import html, Template

        # Resolve at render time after all components registered
        resolved = self._collector.bundles()

        result: Template = t""
        for url in resolved.css:
            result += t'<link rel="stylesheet" href="{url}">'
        for url in resolved.js:
            result += t'<script src="{url}" defer></script>'
        if resolved.py:
            result += t'<script type="module" src="https://pyscript.net/releases/2024.11.1/core.js"></script>'
            for url in resolved.py:
                result += t'<script type="py" src="{url}" async></script>'

        return await html(result)


@dataclass
class ResolvedBundles:
    """Resolved bundle URLs."""

    css: list[str] = field(default_factory=list)
    js: list[str] = field(default_factory=list)
    py: list[str] = field(default_factory=list)


# --- Types ---


class LayoutRenderer(Protocol):
    """Protocol for layout render functions."""

    def __call__(
        self, content: SafeHTML, bundles: Bundles, **kwargs
    ) -> Awaitable[SafeHTML]: ...


# --- Registry ---


class Registry:
    """Singleton registry for components and layouts."""

    _instance: "Registry | None" = None
    _components: dict[str, Component]
    _layouts: dict[str, Component]
    _manifest: dict | None

    def __new__(cls) -> "Registry":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._components = {}
            cls._instance._layouts = {}
            cls._instance._manifest = None
        return cls._instance

    @property
    def components(self) -> dict[str, Component]:
        return self._components.copy()

    @property
    def layouts(self) -> dict[str, Component]:
        return self._layouts.copy()

    def add_component(self, comp: Component) -> None:
        self._components[comp.name] = comp

    def add_layout(self, comp: Component) -> None:
        self._components[comp.name] = comp
        self._layouts[comp.name] = comp

    def get_component(self, name: str) -> Component | None:
        return self._components.get(name)

    def get_layout(self, name: str) -> Component | None:
        return self._layouts.get(name)

    def resolve(self, fn: Callable) -> Component | None:
        """Resolve a function to its registered component."""
        name = getattr(fn, "_htmpl_component", None) or getattr(fn, "_htmpl_layout", None)
        return self._components.get(name) if name else None

    def clear(self) -> None:
        self._components.clear()
        self._layouts.clear()
        self._manifest = None


registry = Registry()


# --- Asset Collector ---


@dataclass
class AssetCollector:
    """Collects assets during request, deduplicates, resolves to bundles."""

    css: set[str] = field(default_factory=set)
    js: set[str] = field(default_factory=set)
    py: set[str] = field(default_factory=set)

    def add(self, comp: Component) -> None:
        """Add a component's assets to the collector."""
        self.css |= comp.css
        self.js |= comp.js
        self.py |= comp.py

    def add_by_name(self, name: str) -> None:
        """Add assets by component name."""
        if comp := registry.get_component(name):
            self.add(comp)

    def bundles(self) -> ResolvedBundles:
        """Resolve collected assets to bundle URLs."""
        return ResolvedBundles(
            css=_get_bundle_urls(self.css, "css"),
            js=_get_bundle_urls(self.js, "js"),
            py=_get_bundle_urls(self.py, "py"),
        )


def _get_bundle_urls(files: set[str], ext: str) -> list[str]:
    """Get bundle URL(s) for a set of files."""
    if not files:
        return []
    url = create_bundle(files, ext)
    return [url] if url else []


# --- Decorators ---


def component(
    *,
    css: set[str] | None = None,
    js: set[str] | None = None,
    py: set[str] | None = None,
):
    """Register a component with its assets."""

    def decorator(fn: Callable) -> ComponentFunc:
        name = qualified_name(fn)

        registry.add_component(
            Component(
                name=name,
                css=css or set(),
                js=js or set(),
                py=py or set(),
            )
        )
        fn = cast(ComponentFunc, fn)
        fn._htmpl_component = name
        return fn

    return decorator


def layout(
    *,
    css: set[str] | None = None,
    js: set[str] | None = None,
    py: set[str] | None = None,
    **defaults,
):
    """Register a layout with its assets and default kwargs.

    Usage:
        @layout(css={"static/css/app.css"}, title="Page", body_class="")
        async def AppLayout(
            content: SafeHTML,
            bundles: Annotated[Bundles, use_bundles()],
            nav: Annotated[SafeHTML, use_component(NavBar)],
            title: str,
            body_class: str,
        ):
            return await html(t'<html>...')
    """

    def decorator(fn: Callable) -> Callable:
        name = qualified_name(fn)

        registry.add_layout(
            Component(
                name=name,
                css=css or set(),
                js=js or set(),
                py=py or set(),
            )
        )
        fn._htmpl_layout = name
        fn._htmpl_defaults = defaults
        return fn

    return decorator


# --- Bundling ---


def _hash(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()[:12]


def _bundle_with_esbuild(files: list[Path], outfile: Path, ext: str) -> bool:
    """Bundle files using esbuild. Returns True on success."""
    if not ESBUILD:
        return False
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
        logger.warning(f"esbuild failed: {exc.stderr}")
        if entry.exists():
            entry.unlink()
        return False


def _fallback_bundle(files: list[Path], outfile: Path) -> None:
    """Manual concatenation fallback."""
    parts = [f.read_text() for f in files]
    outfile.write_text("\n\n".join(parts))


def create_bundle(files: set[str], ext: str) -> str | None:
    """Create a bundle for a set of files, returns URL."""
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

    logger.info(f"building: {filename}")
    start_time = time.perf_counter()

    if ext in ("css", "js") and _bundle_with_esbuild(local_files, path, ext):
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.info(f"built with esbuild in {elapsed_ms:.1f}ms")
        return final_path

    _fallback_bundle(local_files, path)
    elapsed_ms = (time.perf_counter() - start_time) * 1000
    logger.info(f"built with fallback in {elapsed_ms:.1f}ms")
    return final_path


# --- Manifest (for prebuilding) ---


def save_manifest() -> None:
    """Prebuild all unique bundles and save manifest."""
    BUNDLE_DIR.mkdir(parents=True, exist_ok=True)

    all_css: set[str] = set()
    all_js: set[str] = set()
    all_py: set[str] = set()

    for comp in registry.components.values():
        all_css |= comp.css
        all_js |= comp.js
        all_py |= comp.py

    data: dict = {"bundles": {}}
    if css := create_bundle(all_css, "css"):
        data["bundles"]["css"] = css
    if js := create_bundle(all_js, "js"):
        data["bundles"]["js"] = js
    if py := create_bundle(all_py, "py"):
        data["bundles"]["py"] = py

    (BUNDLE_DIR / "manifest.json").write_text(json.dumps(data, indent=2))
    registry._manifest = data


def load_manifest() -> dict:
    """Load manifest from disk (cached)."""
    if registry._manifest is None:
        path = BUNDLE_DIR / "manifest.json"
        registry._manifest = (
            json.loads(path.read_text()) if path.exists() else {"bundles": {}}
        )
    return registry._manifest or {}
