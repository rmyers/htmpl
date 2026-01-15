"""Asset registration and bundling system."""

from ast import Or
from collections import defaultdict, OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from string.templatelib import Template
from typing import Awaitable, Callable, Literal, Protocol, cast, runtime_checkable
import hashlib
import json
import os
import subprocess
import shutil
import logging
import time

from pydantic import BaseModel

from .core import SafeHTML, html

BUNDLE_DIR = Path(os.environ.get("HTMPL_BUNDLE_DIR", "static/bundles"))
PREBUILT = os.environ.get("HTMPL_PREBUILT") == "1"
MINIFY = os.environ.get("HTMPL_MINIFY", "1") == "1"

ESBUILD = shutil.which("esbuild")

logger = logging.getLogger(__name__)

AssetType = Literal['css', 'js', 'py']
componentName = str

class ManifestNotConfigured(Exception):
    pass

def qualified_name(fn: Callable) -> str:
    """Get fully qualified name for a function."""
    return f"{fn.__module__}.{fn.__name__}"


@runtime_checkable
class ComponentFunc(Protocol):
    """Protocol for decorated component functions."""

    _htmpl_component: str

    def __call__(self, *args, **kwargs) -> Awaitable[SafeHTML]: ...


def safe_path(path: str) -> Path | None:
    root = Path().cwd()
    rel = Path(path.lstrip('/'))
    resolved = (root / rel).resolve()
    if not resolved.is_relative_to(root.resolve()):
        return None
    if resolved.exists():
        return Path(rel)
    return None

@dataclass
class Component:
    """Component definition with its assets."""

    name: str
    css: set[str] = field(default_factory=set)
    js: set[str] = field(default_factory=set)
    py: set[str] = field(default_factory=set)

    def __hash__(self):
        return hash(self.name)

    @property
    def path_set(self) -> dict[AssetType, list[Path]]:
        return {
            'css': list(filter(None, [safe_path(c) for c in self.css])),
            'js': list(filter(None, [safe_path(j) for j in self.js])),
            'py': list(filter(None, [safe_path(p) for p in self.py])),
        }

    @property
    def file_set(self) -> dict[AssetType, list[str] | None]:
        _path_set = self.path_set
        return {
            'css': [str(p) for p in _path_set.get('css', [])] or None,
            'js': [str(p) for p in _path_set.get('js', [])] or None,
            'py': [str(p) for p in _path_set.get('py', [])] or None,
        }

    @property
    def assets(self) -> list[str]:
        return [
            path
            for files in self.file_set.values()
            if files
            for path in files
        ]

    def generate_bundles(self) -> dict[AssetType, str | None]:
        _file_set = self.file_set
        return {
            "css": create_bundle(set(_file_set["css"]), 'css') if _file_set['css'] else None,
            "js": create_bundle(set(_file_set["js"]), 'js') if _file_set['js'] else None,
            "py": create_bundle(set(_file_set["py"]), 'py') if _file_set['py'] else None,
        }



@dataclass
class Bundles:
    """Bundle URLs for collected components."""

    _collector: AssetCollector

    @property
    def head(self) -> Awaitable[SafeHTML]:
        """Generate HTML tags for document head."""
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

        return html(result)


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


from watchfiles import watch, Change
import threading

class AssetWatcher:
    def __init__(self, root: Path = Path("static")):
        self._root = root
        self._dirty: set[Path] = set()
        self._watched_files: set[Path] = set()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def track(self, path: Path):
        """Register a file we care about."""
        self._watched_files.add(path.resolve())
        # Start watcher on first track
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()

    def is_dirty(self, path: Path) -> bool:
        return path.resolve() in self._dirty

    def clear_dirty(self, path: Path):
        self._dirty.discard(path.resolve())

    def _run(self):
        for changes in watch(self._root, stop_event=self._stop):
            for change_type, changed_path in changes:
                p = Path(changed_path).resolve()
                if p in self._watched_files:
                    self._dirty.add(p)


class Manifest(BaseModel):
    components: dict[componentName, dict[AssetType, list[str] | None]] = {}
    bundles: dict[componentName, dict[AssetType, str | None]] = {}

    def add_component(self, comp: Component) -> None:
        self.components[comp.name] = comp.file_set
        self.bundles[comp.name] = comp.generate_bundles()



class Registry:
    """Singleton registry for components and layouts."""

    _components: dict[str, Component]
    _layouts: dict[str, Component]
    _assets: dict[str, set[Component]]
    _manifest: Manifest | None

    def __init__(self):
        self._components = {}
        self._layouts = {}
        self._assets = defaultdict(set)
        self._manifest = None

    def initialize(self, frozen: bool = False, watch: bool = False) -> None:
        """Configure the registry

        Args:
            frozen: Load the manifest from disk and do not allow components to build assets
            watch: In dev mode watch the static directory and rebuild manifest on changes
        """
        self._load_manifest(frozen=frozen)

    def _load_manifest(self, frozen: bool = False) -> None:
        path = BUNDLE_DIR / "manifest.json"
        try:
            self._manifest = Manifest.model_validate(
                json.loads(path.read_text()) if path.exists() else {}
            )
        except Exception:
            self._manifest = Manifest(components={}, bundles={})

        if frozen:
            return

        for name, comp in self._components.items():
            if name.startswith('__mp_main__'):
                continue
            self._manifest.add_component(comp)

    @property
    def components(self) -> dict[str, Component]:
        return self._components.copy()

    @property
    def layouts(self) -> dict[str, Component]:
        return self._layouts.copy()

    def add_component(self, comp: Component) -> None:
        self._components[comp.name] = comp
        for asset in comp.assets:
            self._assets[asset].add(comp)

    def add_layout(self, comp: Component) -> None:
        self._components[comp.name] = comp
        self._layouts[comp.name] = comp
        for asset in comp.assets:
            self._assets[asset].add(comp)

    def get_component(self, name: str) -> dict[AssetType, str | None] | None:
        if self._manifest is None:
            raise ManifestNotConfigured("Manifest not configured, please run registry.initialize()")
        return self._manifest.bundles.get(name)

    def save_manifest(self):
        if self._manifest is None:
            self._load_manifest(frozen=False)
        assert self._manifest is not None
        (BUNDLE_DIR / "manifest.json").write_text(self._manifest.model_dump_json(indent=2))

    def resolve(self, fn: Callable) -> Component | None:
        """Resolve a function to its registered component."""
        name = getattr(fn, "_htmpl_component", None) or getattr(fn, "_htmpl_layout", None)
        return self._components.get(name) if name else None

    def clear(self) -> None:
        self._components.clear()
        self._layouts.clear()
        self._assets.clear()
        self._manifest = None


registry = Registry()


@dataclass(slots=True)
class AssetCollector:
    """Collects assets during request, deduplicates, resolves to bundles."""

    # Using ordered dict to preserve order and remove duplicates
    css: OrderedDict[str, int] = field(default_factory=OrderedDict)
    js: OrderedDict[str, int] = field(default_factory=OrderedDict)
    py: OrderedDict[str, int] = field(default_factory=OrderedDict)

    def add_by_name(self, name: str) -> None:
        """Add assets by component name."""
        logger.info(f'adding asset by name: {name}')
        if comp := registry.get_component(name):
            if _css := comp.get('css'):
                self.css[_css] = 1
            if _js := comp.get('js'):
                self.js[_js] = 1
            if _py := comp.get('py'):
                self.py[_py] = 1

    def bundles(self) -> ResolvedBundles:
        """Resolve collected assets to bundle URLs."""
        logger.info(f'loaded {self.css}')
        return ResolvedBundles(
            css=list(self.css.keys()),
            js=list(self.js.keys()),
            py=list(self.py.keys()),
        )


def _get_bundle_urls(files: set[str], ext: str) -> str | None:
    """Get bundle URL(s) for a set of files."""
    return create_bundle(files, ext)


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


philly = {}
frank = {}

def create_bundle(files: set[str], ext: str) -> str | None:
    """Create a bundle for a set of files, returns URL."""
    if not files:
        return None

    BUNDLE_DIR.mkdir(parents=True, exist_ok=True)

    prefix = {"css": "styles", "js": "scripts", "py": "pyscripts"}[ext]

    local_files: list[Path] = []
    file_names: list[str] = []
    for f in sorted(files):
        p = Path(os.path.normpath(f.lstrip("/")))
        if p.exists():
            local_files.append(p)
            if p.name in philly:
                logger.info(f'philly {p.name}: {philly[p.name].stat().st_mtime} vs {frank[p.name]}')
            else:
                philly[p.name] = p
                frank[p.name] = p.stat().st_mtime
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

    bundles = defaultdict(dict)

    for comp_name, comp in registry.components.items():
        bundles[comp_name]["css"] = create_bundle(comp.css, 'css')
        bundles[comp_name]["js"] = create_bundle(comp.js, 'js')
        bundles[comp_name]["py"] = create_bundle(comp.py, 'py')

    logger.info(json.dumps(bundles, indent=2))
    # (BUNDLE_DIR / "manifest.json").write_text(json.dumps(bundles, indent=2))
    #registry._manifest = bundles


def load_manifest() -> dict:
    """Load manifest from disk (cached)."""
    if registry._manifest is None:
        path = BUNDLE_DIR / "manifest.json"
        registry._manifest = (
            json.loads(path.read_text()) if path.exists() else {"bundles": {}}
        )
    return registry._manifest or {}
