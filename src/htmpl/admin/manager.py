"""
htmpl-manager: Local browser-based management for htmpl projects.

Architecture:
- CLI entry point with password generation
- FastAPI server with session-based auth
- Copier integration for template management
- Local git checkout of template library
"""

from __future__ import annotations

import asyncio
import logging
import secrets
import subprocess
import shutil
from pathlib import Path
from typing import Annotated, Any, Callable
from dataclasses import dataclass, field

import click
import tomlkit
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import Field

from htmpl.core import html, render_html, SafeHTML
from htmpl.assets import component, registry, Bundles
from htmpl.fastapi import ParsedForm, use_component, use_bundles, add_assets_routes, is_htmx, use_form
from htmpl.forms import BaseForm

logger = logging.getLogger("htmpl.admin")

# ============================================================================
# Configuration
# ============================================================================

TEMPLATE_REPO = "git@github.com:rmyers/cuneus.git"
CACHE_DIR = Path.home() / ".cache" / "htmpl-manager"
TEMPLATES_DIR = CACHE_DIR / "templates"
SESSION_COOKIE = "htmpl_session"


@dataclass
class ManagerConfig:
    """Loaded from pyproject.toml [tool.htmpl-manager]"""
    project_root: Path
    template_checkout: Path = field(default_factory=lambda: TEMPLATES_DIR)
    installed_plugins: list[str] = field(default_factory=list)
    copier_answers: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def load(cls, project_root: Path) -> "ManagerConfig":
        pyproject = project_root / "pyproject.toml"
        if not pyproject.exists():
            return cls(project_root=project_root)

        doc = tomlkit.parse(pyproject.read_text())
        tool_config = doc.get("tool", {}).get("htmpl-manager", {})

        return cls(
            project_root=project_root,
            template_checkout=Path(tool_config.get("template_checkout", TEMPLATES_DIR)),
            installed_plugins=tool_config.get("installed_plugins", []),
            copier_answers=tool_config.get("copier_answers", {}),
        )

    def save(self):
        pyproject = self.project_root / "pyproject.toml"
        if pyproject.exists():
            doc = tomlkit.parse(pyproject.read_text())
        else:
            doc = tomlkit.document()

        if "tool" not in doc:
            doc["tool"] = {}

        doc["tool"]["htmpl-manager"] = {
            "template_checkout": str(self.template_checkout),
            "installed_plugins": self.installed_plugins,
            "copier_answers": self.copier_answers,
        }
        pyproject.write_text(tomlkit.dumps(doc))


# ============================================================================
# Template Repository Management
# ============================================================================
@dataclass
class TemplateRepo:
    """Manages local checkout of template library."""
    path: Path
    remote: str = TEMPLATE_REPO

    # Env to prevent git from prompting for credentials
    GIT_ENV = {
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_SSH_COMMAND": "ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new",
    }

    async def _run_git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        """Run git command async without blocking, no TTY prompts."""
        import asyncio
        import os

        env = {**os.environ, **self.GIT_ENV}
        proc = await asyncio.create_subprocess_exec(
            "git", *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.DEVNULL,  # No input possible
            env=env,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30.0)

        result = subprocess.CompletedProcess(
            args=["git", *args],
            returncode=proc.returncode or 0,
            stdout=stdout.decode() if stdout else "",
            stderr=stderr.decode() if stderr else "",
        )

        if check and result.returncode != 0:
            raise subprocess.CalledProcessError(
                result.returncode, result.args, result.stdout, result.stderr
            )
        return result

    async def ensure_checkout(self) -> None:
        """Clone if not exists, fetch if it does."""
        if not self.path.exists():
            self.path.parent.mkdir(parents=True, exist_ok=True)
            await self._run_git("clone", "--depth=1", self.remote, str(self.path))
        else:
            # Fetch but don't fail if offline
            await self._run_git("-C", str(self.path), "fetch", "--tags", check=False)

    async def current_version(self) -> str | None:
        """Get current checked out tag/commit."""
        try:
            result = await self._run_git(
                "-C", str(self.path), "describe", "--tags", "--always", check=False
            )
            return result.stdout.strip() if result.returncode == 0 else None
        except asyncio.TimeoutError:
            return None

    async def available_versions(self) -> list[str]:
        """List available tags."""
        try:
            result = await self._run_git(
                "-C", str(self.path), "tag", "-l", "--sort=-v:refname", check=False
            )
            return [t for t in result.stdout.strip().split("\n") if t]
        except asyncio.TimeoutError:
            return []

    async def checkout_version(self, version: str) -> None:
        """Checkout specific tag."""
        await self._run_git("-C", str(self.path), "checkout", version)

    def list_plugins(self) -> list["PluginInfo"]:
        """Discover available plugins from templates directory."""
        plugins_dir = self.path / "plugins"
        if not plugins_dir.exists():
            return []

        plugins = []
        for plugin_path in plugins_dir.iterdir():
            if plugin_path.is_dir() and (plugin_path / "copier.yml").exists():
                plugins.append(PluginInfo.from_path(plugin_path))
        return plugins

@dataclass
class PluginInfo:
    """Metadata about an available plugin."""
    name: str
    path: Path
    description: str = ""
    category: str = "general"
    dependencies: list[str] = field(default_factory=list)

    @classmethod
    def from_path(cls, path: Path) -> "PluginInfo":
        import yaml
        copier_yml = path / "copier.yml"
        meta = yaml.safe_load(copier_yml.read_text()) if copier_yml.exists() else {}

        return cls(
            name=path.name,
            path=path,
            description=meta.get("_description", ""),
            category=meta.get("_category", "general"),
            dependencies=meta.get("_dependencies", []),
        )


# ============================================================================
# Copier Integration
# ============================================================================

class CopierRunner:
    """Wraps copier for template operations."""

    def __init__(self, config: ManagerConfig):
        self.config = config

    def install_plugin(
        self,
        plugin: PluginInfo,
        answers: dict[str, Any] | None = None,
        dry_run: bool = False,
    ) -> subprocess.CompletedProcess:
        """Install a plugin using copier."""
        cmd = ["copier", "copy", "--trust", "--defaults"]

        # Merge saved answers with provided ones
        all_answers = {**self.config.copier_answers, **(answers or {})}
        for key, value in all_answers.items():
            cmd.extend(["-d", f"{key}={value}"])

        if dry_run:
            cmd.append("--pretend")

        cmd.extend([str(plugin.path), str(self.config.project_root)])
        return subprocess.run(cmd, capture_output=True, text=True)

    def update_plugin(
        self,
        plugin: PluginInfo,
        show_diff: bool = True,
    ) -> subprocess.CompletedProcess:
        """Update an installed plugin."""
        cmd = ["copier", "update", "--trust"]
        if show_diff:
            cmd.append("--diff")
        cmd.append(str(self.config.project_root))
        return subprocess.run(cmd, capture_output=True, text=True)

    def create_route(
        self,
        route_name: str,
        route_path: str,
        template_type: str = "page",
    ) -> subprocess.CompletedProcess:
        """Scaffold a new route using the route template."""
        route_template = self.config.template_checkout / "scaffolds" / "route"

        cmd = [
            "copier", "copy", "--trust",
            "-d", f"route_name={route_name}",
            "-d", f"route_path={route_path}",
            "-d", f"template_type={template_type}",
            str(route_template),
            str(self.config.project_root),
        ]
        return subprocess.run(cmd, capture_output=True, text=True)


# ============================================================================
# Authentication
# ============================================================================


class SessionManager:
    """Simple token-based session for local dev server."""

    def __init__(self):
        self.token: str | None = None
        self._password: str | None = None

    def generate_password(self) -> str:
        """Generate a new password and session token."""
        self._password = secrets.token_urlsafe(12)
        self.token = secrets.token_urlsafe(32)
        return self._password

    def create_session(self, password: str) -> str | None:
        """Validate password and return session token."""
        if self._password and secrets.compare_digest(password, self._password):
            return self.token
        return None

    def validate_session(self, token: str) -> bool:
        """Check if session token is valid."""
        if not self.token:
            return False
        return secrets.compare_digest(token, self.token)


session_mgr = SessionManager()


def require_auth(request: Request) -> None:
    """Dependency to require authentication."""
    token = request.cookies.get(SESSION_COOKIE)
    if not token or not session_mgr.validate_session(token):
        raise HTTPException(status_code=401, detail="Unauthorized")


# ============================================================================
# UI Components
# ============================================================================

def StatCard(label: str, value: str | int, subtitle: str | None = None):
    display = f"{value:,}" if isinstance(value, int) else value
    sub = t'<small class="text-muted">{subtitle}</small>' if subtitle else t""
    return t'''<article>
        <h3>{display}</h3>
        <p class="text-muted">{label}</p>
        {sub}
    </article>'''


def PluginCard(plugin: PluginInfo, installed: bool = False):
    status = "✓ Installed" if installed else ""
    action = t'''<button
        class="outline"
        hx-post="/api/plugins/{plugin.name}/install"
        hx-swap="outerHTML"
        hx-target="closest article"
    >Install</button>''' if not installed else t'<span class="text-muted">{status}</span>'

    return t'''<article>
        <header>
            <strong>{plugin.name}</strong>
            <span class="badge">{plugin.category}</span>
        </header>
        <p>{plugin.description}</p>
        <footer>{action}</footer>
    </article>'''


def RouteForm(user_id: str):
    return t'''<form hx-post="/api/routes/create" hx-swap="innerHTML" hx-target="#result">
        <label>
            Route Name
            <input type="text" name="name" placeholder="user_profile" required>
        </label>
        <label>
            URL Path
            <input type="text" name="path" placeholder="/users/{user_id}" required>
        </label>
        <label>
            Template Type
            <select name="template_type">
                <option value="page">Full Page</option>
                <option value="partial">HTMX Partial</option>
                <option value="api">API Endpoint</option>
            </select>
        </label>
        <button type="submit">Create Route</button>
    </form>
    <div id="result"></div>'''


def Alert(message: str, variant: str = "success"):
    cls = "success" if variant == "success" else "error"
    icon = "✓" if variant == "success" else "✗"
    return t'<article class="{cls}"><p>{icon} {message}</p></article>'


@component('manager-nav')
async def ManagerNav():
    items = [
        ("Dashboard", "/"),
        ("Plugins", "/plugins"),
        ("Routes", "/routes"),
        ("Docs", "/docs"),
    ]
    nav_items = [t'<li><a href="{href}">{label}</a></li>' for label, href in items]

    return t'''<nav class="container">
        <ul><li><strong>htmpl Manager</strong></li></ul>
        <ul>{nav_items}</ul>
    </nav>'''


@component('manager-layout', css={"/static/css/manager.css"})
async def ManagerLayout(
    bundles: Annotated[Bundles, Depends(use_bundles)],
    navbar: Annotated[SafeHTML, use_component(ManagerNav)],
):
    def _layout(children, title: str = "htmpl Manager"):
        return html(t'''<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{title}</title>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@picocss/pico@2/css/pico.min.css">
    {bundles.head}
</head>
<body>
    {navbar}
    <main class="container">{children}</main>
    <script src="https://unpkg.com/htmx.org@2.0.4"></script>
</body>
</html>''')

    return _layout


class LoginForm(BaseForm):
    code: str = Field(description="Verify the code displayed on your terminal")


def login_form(**kwargs):
    return t'''<!DOCTYPE html>
<html data-theme="dark"><head><title>Login</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@picocss/pico@2/css/pico.min.css">
</head><body class="container">
<article style="max-width: 600px; margin: 4rem auto;">
    <h2>htmpl Manager</h2>
    {LoginForm.render(submit_text="Unlock", **kwargs)}
</article>
</body></html>'''


def handle_app_exception(request: Request, exc: HTTPException) -> RedirectResponse:
    if exc.status_code == 401:
        return RedirectResponse('/login')

    logger.error(f"Unknown error {exc.status_code}: {exc.detail}")
    return RedirectResponse('/error')


# ============================================================================
# Application Factory
# ============================================================================

def create_app(config: ManagerConfig) -> FastAPI:
    from contextlib import asynccontextmanager

    repo = TemplateRepo(config.template_checkout)
    copier = CopierRunner(config)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await registry.initialize(watch=True)
        yield
        await registry.teardown()

    app = FastAPI(title="htmpl Manager", lifespan=lifespan)
    app.add_exception_handler(401, handle_app_exception) # type: ignore

    # ---- Public routes ----

    @app.get("/login")
    async def login_page():
        return await render_html(t'''{login_form()}''')

    @app.post("/login")
    async def login_submit(parsed: Annotated[ParsedForm[LoginForm], use_form(LoginForm)]):
        if parsed.errors or not parsed.data:
            return await render_html(t"{login_form(errors=parsed.errors, values=parsed.values)}")

        if token := session_mgr.create_session(parsed.data.code):
            response = RedirectResponse("/", status_code=303)
            response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="strict")
            return response

        return RedirectResponse('/login?error="invalid token"', status_code=303)

    # ---- Protected routes ----

    @app.get("/")
    async def dashboard(
        _: Annotated[None, Depends(require_auth)],
        layout: Annotated[Callable, use_component(ManagerLayout)],
    ):
        await repo.ensure_checkout()
        version = await repo.current_version() or "unknown"
        available = await repo.available_versions()
        latest = available[0] if available else "unknown"
        plugins = repo.list_plugins()
        installed_count = len(config.installed_plugins)

        stats = t'''<div class="grid">
            {StatCard("Template Version", version, f"Latest: {latest}")}
            {StatCard("Installed Plugins", f"{installed_count} / {len(plugins)}")}
            {StatCard("Project", str(config.project_root.name))}
        </div>'''

        actions = t'''<section>
            <h2>Quick Actions</h2>
            <div class="grid">
                <a href="/plugins" role="button">Browse Plugins</a>
                <a href="/routes" role="button" class="outline">Create Route</a>
                <button hx-post="/api/templates/update" hx-target="#update-result" class="secondary">
                    Check Updates
                </button>
            </div>
            <div id="update-result"></div>
        </section>'''

        return await render_html(t'''
            <{layout} title="Dashboard">
                <h1>Project Dashboard</h1>
                {stats}
                {actions}
            </{layout}>
        ''')

    @app.get("/plugins")
    async def plugins_page(
        _: Annotated[None, Depends(require_auth)],
        layout: Annotated[Callable, use_component(ManagerLayout)],
    ):
        plugins = repo.list_plugins()
        cards = [
            PluginCard(p, installed=(p.name in config.installed_plugins))
            for p in plugins
        ]

        return await render_html(t'''
            <{layout} title="Plugins">
                <h1>Available Plugins</h1>
                <div class="grid">{cards}</div>
            </{layout}>
        ''')

    @app.post("/api/plugins/{name}/install")
    async def install_plugin(name: str, _: Annotated[None, Depends(require_auth)]):
        plugins = repo.list_plugins()
        plugin = next((p for p in plugins if p.name == name), None)
        if not plugin:
            raise HTTPException(404, "Plugin not found")

        result = copier.install_plugin(plugin)
        if result.returncode == 0:
            config.installed_plugins.append(name)
            config.save()
            return await render_html(PluginCard(plugin, installed=True))

        return await render_html(Alert(f"Install failed: {result.stderr}", "error"))

    @app.get("/routes")
    async def routes_page(
        _: Annotated[None, Depends(require_auth)],
        layout: Annotated[Callable, use_component(ManagerLayout)],
    ):
        return await render_html(t'''
            <{layout} title="Create Route">
                <h1>Create New Route</h1>
                {RouteForm(user_id="2345")}
            </{layout}>
        ''')

    @app.post("/api/routes/create")
    async def create_route(request: Request, _: Annotated[None, Depends(require_auth)]):
        form = await request.form()
        result = copier.create_route(
            route_name=str(form["name"]),
            route_path=str(form["path"]),
            template_type=str(form.get("template_type", "page")),
        )

        if result.returncode == 0:
            return await render_html(Alert(f"Route created: {form['path']}"))
        return await render_html(Alert(f"Failed: {result.stderr}", "error"))

    @app.post("/api/templates/update")
    async def update_templates(_: Annotated[None, Depends(require_auth)]):
        await repo.ensure_checkout()
        current = await repo.current_version()
        available = await repo.available_versions()

        if available and available[0] != current:
            await repo.checkout_version(available[0])
            return await render_html(Alert(f"Updated to {available[0]} from {current}"))
        return await render_html(Alert(f"Already up to date ({current})"))

    @app.get("/docs")
    async def docs_page(
        _: Annotated[None, Depends(require_auth)],
        layout: Annotated[Callable, use_component(ManagerLayout)],
    ):
        # TODO: Load component showcase from template repo
        return await render_html(t'''
            <{layout} title="Documentation">
                <h1>Component Documentation</h1>
                <p>Interactive documentation coming soon...</p>
            </{layout}>
        ''')

    add_assets_routes(app)
    return app


# ============================================================================
# CLI
# ============================================================================

@click.group()
def cli():
    """htmpl project manager."""
    pass


@cli.command()
@click.option("--port", default=8765, help="Port to run on")
@click.option("--host", default="127.0.0.1", help="Host to bind to")
@click.argument("project_root", type=click.Path(exists=True), default=".")
def serve(port: int, host: str, project_root: str):
    """Start the management server."""
    import uvicorn

    config = ManagerConfig.load(Path(project_root).resolve())
    password = session_mgr.generate_password()

    click.echo("\n" + "=" * 50)
    click.echo("htmpl Manager")
    click.echo("=" * 50)
    click.echo(f"\n  URL:      http://{host}:{port}")
    click.secho(f"  Password: {password}", fg="green", bold=True)
    click.echo("\n" + "=" * 50 + "\n")

    app = create_app(config)
    uvicorn.run(app, host=host, port=port, log_level="warning")


@cli.command()
@click.option("--version", "-v", help="Specific version to checkout")
def update(version: str | None):
    """Update local template checkout."""
    import asyncio

    async def _update():
        config = ManagerConfig.load(Path.cwd())
        repo = TemplateRepo(config.template_checkout)
        await repo.ensure_checkout()

        if version:
            await repo.checkout_version(version)
            click.echo(f"Checked out {version}")
        else:
            available = await repo.available_versions()
            if available:
                await repo.checkout_version(available[0])
                click.echo(f"Updated to latest: {available[0]}")

    asyncio.run(_update())


@cli.command()
@click.argument("plugin_name")
@click.option("--dry-run", is_flag=True, help="Preview changes without applying")
def install(plugin_name: str, dry_run: bool):
    """Install a plugin from templates."""
    import asyncio

    async def _install():
        config = ManagerConfig.load(Path.cwd())
        repo = TemplateRepo(config.template_checkout)
        await repo.ensure_checkout()

        plugins = repo.list_plugins()
        plugin = next((p for p in plugins if p.name == plugin_name), None)

        if not plugin:
            available = ", ".join(p.name for p in plugins)
            raise click.ClickException(f"Plugin '{plugin_name}' not found. Available: {available}")

        copier = CopierRunner(config)
        result = copier.install_plugin(plugin, dry_run=dry_run)

        if result.returncode == 0:
            if not dry_run:
                config.installed_plugins.append(plugin_name)
                config.save()
            click.echo(result.stdout)
            click.secho("✓ Success" if not dry_run else "Preview complete", fg="green")
        else:
            click.secho(f"Failed: {result.stderr}", fg="red")

    asyncio.run(_install())


@cli.command("list")
def list_plugins():
    """List available plugins."""
    import asyncio

    async def _list():
        config = ManagerConfig.load(Path.cwd())
        repo = TemplateRepo(config.template_checkout)
        await repo.ensure_checkout()

        plugins = repo.list_plugins()
        for p in plugins:
            status = "✓" if p.name in config.installed_plugins else " "
            click.echo(f"  [{status}] {p.name:20} - {p.description}")

    asyncio.run(_list())

if __name__ == "__main__":
    cli()
