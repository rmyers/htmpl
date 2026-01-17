"""Asset registration and bundling system."""

import asyncio
import hashlib
import json
import os
import subprocess
import shutil
import logging
import time
from collections import defaultdict, OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from string.templatelib import Template
from typing import Awaitable, Callable, Literal, Protocol, cast, runtime_checkable
from weakref import WeakSet

from fastapi import WebSocket
from pydantic import BaseModel
from watchfiles import awatch

from .core import SafeHTML, html

ESBUILD = shutil.which("esbuild")

logger = logging.getLogger(__name__)

AssetType = Literal["css", "js", "py"]
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


class LayoutRenderer(Protocol):
    """Protocol for layout render functions."""

    def __call__(self, content: SafeHTML, bundles: Bundles, **kwargs) -> Awaitable[SafeHTML]: ...


ALLOWED_EXTENSIONS = {".css", ".js", ".ts", ".py"}


def safe_path(path: str, root: Path) -> Path | None:
    rel = Path(path.lstrip("/"))

    # Explicit blocklist checks
    if ".." in rel.parts:
        logger.warning(f"Attempting to use relative paths {rel}")
        return None
    if any(part.startswith(".") for part in rel.parts):
        logger.warning(f"Attempting to use hidden files {rel}")
        return None  # No hidden files
    if rel.suffix.lower() not in ALLOWED_EXTENSIONS:
        logger.warning(f"Suffix not allowed {rel}")
        return None

    # Strip root dir name if path starts with it
    # e.g., "static/button.css" with root="/tmp/static" -> "button.css"
    if rel.parts and rel.parts[0] == root.name:
        rel = Path(*rel.parts[1:]) if len(rel.parts) > 1 else Path()

    # Resolve WITHOUT following symlinks first
    candidate = root / rel

    # Reject symlinks entirely
    if candidate.is_symlink():
        logger.warning(f"Attempting to use symlinked files {rel}")
        return None

    resolved = candidate.resolve()
    root_path = root.resolve()

    if not resolved.is_relative_to(root_path):
        logger.warning(f"Attempting to add asset not contained in static dir {resolved}")
        return None
    if not resolved.exists():
        logger.warning(f"Asset file not found {resolved}")
        return None
    return resolved


@dataclass
class Component:
    """Component definition with its assets."""

    name: str
    css: set[str] = field(default_factory=set)
    js: set[str] = field(default_factory=set)
    py: set[str] = field(default_factory=set)

    def __hash__(self):
        return hash(self.name)

    def path_set(self, root: Path) -> dict[AssetType, list[Path]]:
        return {
            "css": list(filter(None, [safe_path(c, root) for c in self.css])),
            "js": list(filter(None, [safe_path(j, root) for j in self.js])),
            "py": list(filter(None, [safe_path(p, root) for p in self.py])),
        }

    def file_set(self, root: Path) -> dict[AssetType, list[str] | None]:
        _path_set = self.path_set(root)
        return {
            "css": [str(p) for p in _path_set.get("css", [])] or None,
            "js": [str(p) for p in _path_set.get("js", [])] or None,
            "py": [str(p) for p in _path_set.get("py", [])] or None,
        }

    def assets(self, root: Path) -> list[Path]:
        return [path.resolve() for files in self.path_set(root).values() if files for path in files]

    def generate_bundles(
        self, statics: Path, bundles: Path, assets: str
    ) -> dict[AssetType, str | None]:
        _file_set = self.file_set(statics)
        _css: str | None = None
        _js: str | None = None
        _py: str | None = None
        if css := _file_set.get("css"):
            _css = create_bundle(set(css), "css", bundles, assets)
        if js := _file_set.get("js"):
            _js = create_bundle(set(js), "js", bundles, assets)
        if py := _file_set.get("py"):
            _py = create_bundle(set(py), "py", bundles, assets)
        return {
            "css": _css,
            "js": _js,
            "py": _py,
        }


HMR = Template("""
<script>
(function () {
  const ws = new WebSocket(`ws://${location.host}/__hmr`);
  let connected = false;
  ws.onopen = () => (connected = true);
  ws.onmessage = () => location.reload();
  ws.onclose = () => connected && setTimeout(() => location.reload(), 1000);
})();
</script>
""")


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
            result += t'<script type="module" src="https://pyscript.net/releases/2025.11.2/core.js"></script>'
            for url in resolved.py:
                result += t'<script type="py" src="{url}" async></script>'
        if registry.watch:
            result += HMR

        return html(result)


@dataclass
class ResolvedBundles:
    """Resolved bundle URLs."""

    css: list[str] = field(default_factory=list)
    js: list[str] = field(default_factory=list)
    py: list[str] = field(default_factory=list)


class Manifest(BaseModel):
    bundles: dict[componentName, dict[AssetType, str | None]] = {}

    def add_component(self, comp: Component, static: Path, bundles: Path, assets: str) -> None:
        self.bundles[comp.name] = comp.generate_bundles(static, bundles, assets)


class Registry:
    """Singleton registry for components and layouts."""

    _instance: "Registry | None" = None
    _components: dict[str, Component]
    _layouts: dict[str, Component]
    _assets: dict[Path, set[Component]]
    _frozen: bool = False
    _watch: bool = False
    _manifest: Manifest | None = None
    _static_dir: Path
    _bundle_dir: Path
    _assets_path: str
    _clients: WeakSet[WebSocket]
    _watch_task: asyncio.Task | None

    def __new__(cls) -> "Registry":
        if cls._instance is None:  # pragma: no branch
            cls._instance = super().__new__(cls)
            cls._instance._components = {}
            cls._instance._layouts = {}
            cls._instance._assets = defaultdict(set)
            cls._clients = WeakSet()
            cls._watch_task = None
        return cls._instance

    async def initialize(
        self,
        frozen: bool = False,
        watch: bool = False,
        static_dir: Path = Path("static"),
        bundle_dir: Path = Path("dist/bundles"),
        assets_path: str = "/assets",
    ) -> None:
        """Configure the registry

        Args:
            frozen: Load the manifest from disk and do not allow components to build assets: default False
            watch: In dev mode watch the static directory and rebuild manifest on changes: default False
            static_dir: Path to static files directory: default ('static')
            bundle_dir: Path to bundled output files: default ('dist/bundles')
            asset_path: URL root to expose bundled assets: default ('/assets')
        """
        logger.info(
            f"Initializing 'registry'"
            f" frozen={frozen} watch={watch} static_dir={static_dir}"
            f" bundle_dir={bundle_dir} assets_path={assets_path}"
        )
        self._frozen = frozen
        self._watch = watch
        self._static_dir = static_dir
        self._bundle_dir = bundle_dir
        self._assets_path = assets_path
        self._load_assets()
        self._load_manifest(frozen=frozen)
        await self._start_ws_watch()

    def _load_assets(self) -> None:
        for name, comp in self._components.items():
            if name.startswith("__mp_main__"):  # pragma: no cover
                continue
            for asset in comp.assets(self.static_dir):
                self._assets[asset].add(comp)

    def _load_manifest(self, frozen: bool = False) -> None:
        path = self._bundle_dir / "manifest.json"
        try:
            self._manifest = Manifest.model_validate(
                json.loads(path.read_text()) if path.exists() else {}
            )
        except Exception:  # pragma: no cover
            self._manifest = Manifest(bundles={})

        if frozen:
            return

        self._bundle_dir.mkdir(parents=True, exist_ok=True)

        for name, comp in self._components.items():
            if name.startswith("__mp_main__"):  # pragma: no cover
                continue
            logger.info(f"add component to manifest {name}")
            self._manifest.add_component(comp, self.static_dir, self.bundles_dir, self._assets_path)
        self.save_manifest()

    async def _broadcast_reload(self):
        for ws in list(self._clients):
            try:
                await ws.send_text("reload")
            except:
                self._clients.discard(ws)

    async def _watch_loop(self, root: Path):
        if self._manifest is None:
            raise ManifestNotConfigured("Error brosky")

        logger.info(f"Starting watcher process on files in '{root}'")
        async for changes in awatch(root):
            has_changes = False
            for _, changed_path in changes:
                p = Path(changed_path).resolve()
                for comp in self._assets.get(p, []):
                    has_changes = True
                    logger.info(f"Rebuilding component: {comp.name}")
                    self._manifest.add_component(
                        comp, self.static_dir, self.bundles_dir, self._assets_path
                    )
                    await self._broadcast_reload()

            if has_changes:
                self.save_manifest()

    async def _start_ws_watch(self) -> None:
        if self._watch and self._watch_task is None:
            self._watch_task = asyncio.create_task(self._watch_loop(self._static_dir))

    def add_ws_client(self, ws: WebSocket) -> None:
        self._clients.add(ws)

    def remove_ws_client(self, ws: WebSocket) -> None:
        self._clients.discard(ws)

    async def teardown(self):
        self._assets.clear()
        self._manifest = None
        self._frozen = False
        self._watch = False
        if self._watch_task:
            self._watch_task.cancel()
            self._watch_task = None

    @property
    def components(self) -> dict[str, Component]:
        return self._components.copy()

    @property
    def layouts(self) -> dict[str, Component]:
        return self._layouts.copy()

    @property
    def watch(self) -> bool:
        return self._watch

    @property
    def frozen(self) -> bool:
        return self._frozen

    @property
    def static_dir(self) -> Path:
        return self._static_dir

    @property
    def bundles_dir(self) -> Path:
        return self._bundle_dir

    def add_component(self, comp: Component) -> None:
        self._components[comp.name] = comp

    def add_layout(self, comp: Component) -> None:
        self._components[comp.name] = comp
        self._layouts[comp.name] = comp

    def get_component(self, name: str) -> dict[AssetType, str | None] | None:
        if self._manifest is None:
            raise ManifestNotConfigured("Manifest not configured, please run registry.initialize()")
        return self._manifest.bundles.get(name)

    def save_manifest(self):
        if self._manifest is None:
            self._load_manifest(frozen=False)
        assert self._manifest is not None
        (self._bundle_dir / "manifest.json").write_text(self._manifest.model_dump_json(indent=2))

    def resolve(self, fn: Callable) -> Component | None:
        """Resolve a function to its registered component."""
        name = getattr(fn, "_htmpl_component", None) or getattr(fn, "_htmpl_layout", None)
        return self._components.get(name) if name else None


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
        logger.info(f"adding asset by name: {name}")
        if comp := registry.get_component(name):
            if _css := comp.get("css"):
                self.css[_css] = 1
            if _js := comp.get("js"):
                self.js[_js] = 1
            if _py := comp.get("py"):
                self.py[_py] = 1

    def bundles(self) -> ResolvedBundles:
        """Resolve collected assets to bundle URLs."""
        logger.info(f"loaded {self.css}")
        return ResolvedBundles(
            css=list(self.css.keys()),
            js=list(self.js.keys()),
            py=list(self.py.keys()),
        )


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
            "--minify",
            "--sourcemap",
        ]
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


def create_bundle(files: set[str], ext: str, bundle_dir: Path, assets_path: str) -> str | None:
    """Create a bundle for a set of files, returns URL."""
    if not files:
        return None

    prefix = {"css": "styles", "js": "scripts", "py": "pyscripts"}[ext]

    local_files: list[Path] = []
    file_names: list[str] = []
    for f in sorted(files):
        p = Path(f)
        if p.exists():
            local_files.append(p)
            file_names.append(f"{p.name}-{p.stat().st_mtime}")

    if not local_files:
        return None

    file_hash = _hash(":".join(file_names))
    filename = f"{prefix}-{file_hash}.{ext}"
    path = bundle_dir / filename
    final_path = f"{assets_path}/{filename}"

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
