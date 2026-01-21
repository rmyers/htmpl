"""Tests for htmpl FastAPI integration."""

import re
from typing import Annotated, Any

import tempfile
from pathlib import Path
from fastapi.responses import HTMLResponse
import pytest
from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.testclient import TestClient
from pydantic import Field, EmailStr

from tdom import html
from htmpl import forms, SafeHTML, render_html, render
from htmpl.assets import (
    Bundles,
    AssetCollector,
    component,
    registry,
)
from htmpl.fastapi import ParsedForm, use_form, use_component, use_bundles, is_htmx


@pytest.fixture(scope="function")
async def setup_registry():
    with tempfile.TemporaryDirectory() as tempy:
        temp = Path(tempy)
        dist_dir = temp / "dist"
        dist_dir.mkdir()
        static_dir = temp / "static"
        static_dir.mkdir()
        button_css = static_dir / "button.css"
        button_css.write_text("button")
        card_css = static_dir / "card.css"
        card_css.write_text("card")
        card_js = static_dir / "card.js"
        card_js.write_text("card.js")
        nav_js = static_dir / "nav.js"
        nav_js.write_text("nav")
        nav_py = static_dir / "nav.py"
        nav_py.write_text("nav")
        app_css = static_dir / "app.css"
        app_css.write_text("app")
        await registry.initialize(
            frozen=False, watch=True, static_dir=static_dir, bundle_dir=dist_dir
        )
        yield tempy

    await registry.teardown()


@pytest.fixture(scope="function")
async def prod_registry():
    with tempfile.TemporaryDirectory() as tempy:
        temp = Path(tempy)
        dist_dir = temp / "dist"
        dist_dir.mkdir()
        static_dir = temp / "static"
        static_dir.mkdir()
        await registry.initialize(
            frozen=True, watch=False, static_dir=static_dir, bundle_dir=dist_dir
        )
        yield

    await registry.teardown()


@component("fancy-button", css={"button.css"})
def Button(label: str):
    return html(t"<button class='btn'>{label}</button>")


@component("app-card", css={"card.css"}, js={"card.js"})
def Card(children, title: str):
    return html(t"<div class='card'><h3>{title}</h3>{children}</div>")


@component("nav-bar", js={"nav.js"}, py={"nav.py"})
async def NavBar():
    def _comp(user: str = "Guest"):
        return html(t"<nav>Welcome, {user}</nav>")
    return _comp


@component("app-layout",css={"app.css"})
async def AppLayout(
    bundles: Annotated[Bundles, Depends(use_bundles)],
    nav: Annotated[SafeHTML, use_component(NavBar)],
):

    def _component(children, title="Page", body_class=""):
        return html(t"""
            <!DOCTYPE html>
            <html>
            <head>
                <title>{title}</title>
                {bundles.head}
            </head>
            <body class="{body_class}">
                {nav}
                <main>{children}</main>
            </body>
            </html>
        """)
    return _component


@component("min-layout")
async def MinimalLayout(
    bundles: Annotated[Bundles, Depends(use_bundles)],
):
    def _component(children):
        return html(t"<head>{bundles.head}</head><div class='minimal'>{children}</div>")
    return _component


@component("render-layout", css={"app.css"})
async def RenderLayout(children, bundles: Bundles):
    f = html(t"<head>{bundles:safe}</head><div class='minimal'>{children}</div>")
    return f

class TestAssetCollector:
    def assert_matches(self, collection, pattern: str):
        """Assert all items in collection match the regex pattern."""
        regex = re.compile(pattern)
        for item in collection:
            assert regex.match(item), f"'{item}' does not match pattern '{pattern}'"

    async def test_empty_collector(self, setup_registry: EmailStr):
        collector = AssetCollector()
        resolved = collector.bundles()
        assert resolved.css == []
        assert resolved.js == []

    async def test_add_by_name(self, setup_registry: EmailStr):
        # await registry.initialize()
        collector = AssetCollector()
        collector.add_by_name("app-card")
        assert len(collector.css) == 1
        assert len(collector.js) == 1
        self.assert_matches(collector.css, r"/assets/styles-[a-f0-9]+\.css$")
        self.assert_matches(collector.js, r"/assets/scripts-[a-f0-9]+\.js$")

    async def test_deduplication(self, setup_registry: EmailStr):
        collector = AssetCollector()
        collector.add_by_name("fancy-button")
        collector.add_by_name("fancy-button")
        assert len(collector.css) == 1
        self.assert_matches(collector.css, r"/assets/styles-[a-f0-9]+\.css$")


class TestRouter:
    @pytest.fixture
    def app(self):
        app = FastAPI()
        router = APIRouter()

        @router.get("/")
        async def home(page: Annotated[SafeHTML, use_component(AppLayout)]):
            return await render_html(t'<{page} title="Home"><section><h1>Home</h1></section></{page}>')

        @router.get("/user/{name}")
        async def user(name: str, page: Annotated[SafeHTML, use_component(AppLayout)]):
            return await render_html(t'<{page} title="User: {name}"><section><p>Hello, {name}!</p></section></{page}>')

        @router.get("/minimal")
        async def minimal(page: Annotated[SafeHTML, use_component(MinimalLayout)]):
            return await render_html(t'<{page}><p>Minimal page</p></{page}>')

        @router.get("/custom-class")
        async def custom_class(page: Annotated[SafeHTML, use_component(AppLayout)]):
            return await render_html(t'<{page} title="Custom" body_class="dark-mode"><p>Custom</p></{page}>')

        @router.get("/default-title")
        async def default_title(page: Annotated[SafeHTML, use_component(AppLayout)]):
            # Uses default title="Page" from decorator
            return await render_html(t'<{page}><p>Default</p></{page}>')

        @router.get("/render-test")
        async def render_testing(bundles: Bundles = Depends(use_bundles)):
            return await render(
                t"""
                    <render-layout bundles={bundles.head}>
                        <app-card title='test'>boo</app-card>
                    </render-layout>
                """,
                registry.components
            )

        @router.get("/json")
        async def json_route():
            return {"message": "json"}

        app.include_router(router)
        return app

    @pytest.fixture
    def client(self, app: FastAPI):
        return TestClient(app)

    @pytest.fixture(autouse=True)
    def setup(self, setup_registry: EmailStr):
        pass

    def test_layout_renders(self, client: TestClient):
        response = client.get("/")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "<!DOCTYPE html>" in response.text
        assert "<title>Home</title>" in response.text
        assert "<section><h1>Home</h1></section>" in response.text

    def test_nav_component_rendered(self, client: TestClient):
        response = client.get("/")
        assert "<nav>Welcome, Guest</nav>" in response.text

    def test_layout_with_params(self, client: TestClient):
        response = client.get("/user/Bob")
        assert response.status_code == 200
        assert "<title>User: Bob</title>" in response.text
        assert "<p>Hello, Bob!</p>" in response.text

    def test_minimal_layout(self, client: TestClient, prod_registry: None):
        response = client.get("/minimal")
        assert response.status_code == 200
        assert '<div class="minimal">' in response.text
        assert "<!DOCTYPE" not in response.text

    def test_custom_body_class(self, client: TestClient):
        response = client.get("/custom-class")
        assert 'class="dark-mode"' in response.text

    def test_default_title_from_decorator(self, client: TestClient):
        response = client.get("/default-title")
        assert "<title>Page</title>" in response.text

    def test_render_bundles_assets(self, client: TestClient):
        response = client.get("/render-test")
        assert '<div class="card"><h3>test</h3>boo</div>' in response.text

    def test_json_passthrough(self, client: TestClient):
        response = client.get("/json")
        assert response.status_code == 200
        assert response.json() == {"message": "json"}


class TestFormRouter:
    @pytest.fixture
    def app(self):
        app = FastAPI()
        router = APIRouter()

        class LoginSchema(forms.BaseForm):
            email: EmailStr = Field(examples=["foo@bar.com"], description="Your email")
            password: str = Field(min_length=8)

        class SignupSchema(forms.BaseForm):
            username: str = Field(min_length=3, max_length=20)
            email: EmailStr
            agree_tos: bool

        @router.get("/login")
        async def login_page(page: Annotated[SafeHTML, use_component(MinimalLayout)]):
            rendered = LoginSchema.render(submit_text="Login")
            return await render_html(t"<{page}>{rendered}</{page}>")

        @router.post("/login")
        async def login(
            page: Annotated[SafeHTML, use_component(MinimalLayout)],
            parsed: Annotated[ParsedForm[LoginSchema], use_form(LoginSchema)]
        ):
            if parsed.errors:
                rendered = LoginSchema.render(values=parsed.values, errors=parsed.errors, submit_text="Login")
                return await render_html(t"<{page}>{rendered}</{page}>")

            assert parsed.data is not None
            return await render_html(t"<{page}><h1>Welcome, {parsed.data.email}!</h1></{page}>")

        @router.get("/signup")
        async def signup_page(page: Annotated[SafeHTML, use_component(MinimalLayout)],):
            rendered = SignupSchema.render(submit_text="Login")
            return await render_html(t"<{page}>{rendered}</{page}>")

        @router.post("/signup")
        async def signup(
            page: Annotated[SafeHTML, use_component(MinimalLayout)],
            parsed: Annotated[ParsedForm[SignupSchema], use_form(SignupSchema)],
        ):
            if parsed.errors:
                rendered = SignupSchema.render(values=parsed.values, errors=parsed.errors, submit_text="Login")
                return await render_html(t"<{page}>{rendered}</{page}>")

            assert parsed.data is not None
            return await render_html(t"<{page}><h1>Account created for {parsed.data.username}!</h1></{page}>")

        app.include_router(router)
        return app

    @pytest.fixture
    def client(self, app: FastAPI):
        return TestClient(app)

    @pytest.fixture(autouse=True)
    def setup(self, setup_registry: EmailStr):
        pass

    def test_form_get_renders(self, client: TestClient):
        response = client.get("/login")
        assert response.status_code == 200
        assert "<form" in response.text
        assert 'name="email"' in response.text

    def test_form_post_valid(self, client: TestClient):
        response = client.post(
            "/login",
            data={"email": "user@example.com", "password": "secretpassword"},
        )
        assert response.status_code == 200
        assert "Welcome, user@example.com!" in response.text

    def test_form_post_invalid(self, client: TestClient):
        response = client.post(
            "/login",
            data={"email": "not-an-email", "password": "secretpassword"},
        )
        assert response.status_code == 200
        assert "<form" in response.text
        assert 'aria-invalid="true"' in response.text

    def test_form_checkbox(self, client: TestClient):
        response = client.post(
            "/signup",
            data={"username": "testuser", "email": "test@example.com", "agree_tos": "on"},
        )
        assert "Account created for testuser!" in response.text


class UNTestPageRenderer:
    @pytest.fixture
    def app(self, setup_registry: EmailStr):
        app = FastAPI()
        router = APIRouter()

        # @router.get("/redirect-test")
        # async def redirect_test(page: Annotated[PageRenderer, use_layout(MinimalLayout)]):
        #     return page.redirect("/target")

        # @router.get("/refresh-test")
        # async def refresh_test(page: Annotated[PageRenderer, use_layout(MinimalLayout)]):
        #     return page.refresh()

        # @router.get("/is-htmx")
        # async def is_htmx_route(page: Annotated[PageRenderer, use_layout(MinimalLayout)]):
        #     return await page(p(f"is_htmx: {page.is_htmx}"))

        app.include_router(router)
        return app

    @pytest.fixture
    def client(self, app: FastAPI):
        return TestClient(app, follow_redirects=False)

    def test_redirect_standard(self, client):
        response = client.get("/redirect-test")
        assert response.status_code == 303
        assert response.headers["location"] == "/target"

    def test_redirect_htmx(self, client):
        response = client.get("/redirect-test", headers={"HX-Request": "true"})
        assert response.status_code == 200
        assert response.headers["HX-Redirect"] == "/target"

    def test_refresh_standard(self, client):
        response = client.get("/refresh-test")
        assert response.status_code == 303

    def test_refresh_htmx(self, client):
        response = client.get("/refresh-test", headers={"HX-Request": "true"})
        assert response.status_code == 200
        assert response.headers["HX-Refresh"] == "true"

    def test_is_htmx_false(self, client):
        response = client.get("/is-htmx")
        assert "is_htmx: False" in response.text

    def test_is_htmx_true(self, client):
        response = client.get("/is-htmx", headers={"HX-Request": "true"})
        assert "is_htmx: True" in response.text


class TestAssetIntegration:
    """Integration tests for asset collection through the request cycle."""

    @pytest.fixture
    def app(self, setup_registry: EmailStr):
        app = FastAPI()
        router = APIRouter()

        @router.get("/with-layout")
        async def with_layout(page: Annotated[SafeHTML, use_component(AppLayout)]):
            return await render_html(t"<{page} title='Test'><h1>With Layout</h1></{page}>")

        @router.get("/partial")
        async def partial():
            # No use_layout = no collector = no asset tracking
            btn = Button("Click")
            return await render_html(btn)

        app.include_router(router)
        return app

    @pytest.fixture
    def client(self, app: FastAPI):
        return TestClient(app)

    def test_layout_collects_assets(self, client: TestClient):
        response = client.get("/with-layout")
        assert response.status_code == 200
        assert "<head>" in response.text
        # NavBar component should be rendered
        assert "<nav>Welcome, Guest</nav>" in response.text

    def test_partial_no_layout(self, client: TestClient):
        response = client.get("/partial")
        assert response.status_code == 200
        assert '<button class="btn">Click</button>' in response.text
        assert "<!DOCTYPE" not in response.text


class TestIntegration:
    """Integration tests with raw render_html usage."""

    @pytest.fixture
    def app(self, setup_registry: EmailStr):
        app = FastAPI()
        router = APIRouter()

        @router.get("/")
        async def home() -> HTMLResponse:
            return await render_html(t"""
                <!DOCTYPE html>
                <html>
                <body>
                    <h1>Home</h1>
                    <button hx-get="/partial" hx-target="#content">Load</button>
                </body>
                </html>
            """)

        @router.get("/partial")
        async def partial(request: Request) -> HTMLResponse:
            if is_htmx(request):
                return await render_html(t"<p>Partial loaded!</p>")
            return await render_html(
                t"<!DOCTYPE html><html><body><p>Partial loaded!</p></body></html>"
            )

        @router.get("/users")
        async def users(q: str = "") -> HTMLResponse:
            all_users = ["Alice", "Bob", "Charlie"]
            filtered = [u for u in all_users if q.lower() in u.lower()] if q else all_users
            return await render_html(t"<ul>{[t'<li>{user}</li>' for user in filtered]}</ul>")

        app.include_router(router)
        return app

    @pytest.fixture
    def client(self, app: FastAPI):
        return TestClient(app)

    def test_home_page(self, client: TestClient):
        response = client.get("/")
        assert response.status_code == 200
        assert "<!DOCTYPE html>" in response.text
        assert 'hx-get="/partial"' in response.text

    def test_partial_htmx(self, client: TestClient):
        response = client.get("/partial", headers={"HX-Request": "true"})
        assert response.text == "<p>Partial loaded!</p>"

    def test_partial_direct(self, client: TestClient):
        response = client.get("/partial")
        assert "<!DOCTYPE html>" in response.text

    def test_users_filtered(self, client: TestClient):
        response = client.get("/users?q=ali")
        assert "<li>Alice</li>" in response.text
        assert "<li>Bob</li>" not in response.text
