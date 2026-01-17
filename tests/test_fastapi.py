"""Tests for htmpl FastAPI integration."""

import re
from typing import Annotated

import tempfile
from pathlib import Path
from fastapi.responses import HTMLResponse
import pytest
from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.testclient import TestClient
from pydantic import Field, EmailStr

from htmpl import html, forms, SafeHTML, render_html
from htmpl.elements import section, h1, p, article, form, button
from htmpl.htmx import is_htmx
from htmpl.assets import (
    Bundles,
    AssetCollector,
    component,
    layout,
    registry,
    qualified_name,
)
from htmpl.fastapi import PageRenderer, use_layout, use_component, use_bundles


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


@component(css={"button.css"})
async def Button(label: str):
    return await html(t"<button class='btn'>{label}</button>")


@component(css={"card.css"}, js={"card.js"})
async def Card(title: str, body: SafeHTML):
    return await html(t"<div class='card'><h3>{title}</h3>{body}</div>")


@component(js={"nav.js"}, py={"nav.py"})
async def NavBar(user: str = "Guest"):
    return await html(t"<nav>Welcome, {user}</nav>")


@layout(css={"app.css"}, title="Page", body_class="")
async def AppLayout(
    content: SafeHTML,
    bundles: Annotated[Bundles, Depends(use_bundles)],
    nav: Annotated[SafeHTML, use_component(NavBar)],
    title: str,
    body_class: str,
):
    return await html(t"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>{title}</title>
            {bundles.head}
        </head>
        <body class="{body_class}">
            {nav}
            <main>{content}</main>
        </body>
        </html>
    """)


@layout()
async def MinimalLayout(
    content: SafeHTML,
    bundles: Annotated[Bundles, Depends(use_bundles)],
):
    return await html(t"<head>{bundles.head}</head><div class='minimal'>{content}</div>")


# --- Tests ---


class TestQualifiedName:
    def test_qualified_name(self):
        assert qualified_name(Button) == "test_fastapi.Button"
        assert qualified_name(AppLayout) == "test_fastapi.AppLayout"


class TestAssetCollector:
    def assert_matches(self, collection, pattern: str):
        """Assert all items in collection match the regex pattern."""
        regex = re.compile(pattern)
        for item in collection:
            assert regex.match(item), f"'{item}' does not match pattern '{pattern}'"

    async def test_empty_collector(self, setup_registry):
        collector = AssetCollector()
        resolved = collector.bundles()
        assert resolved.css == []
        assert resolved.js == []

    async def test_add_by_name(self, setup_registry):
        # await registry.initialize()
        collector = AssetCollector()
        collector.add_by_name(qualified_name(Card))
        assert len(collector.css) == 1
        assert len(collector.js) == 1
        self.assert_matches(collector.css, r"/assets/styles-[a-f0-9]+\.css$")
        self.assert_matches(collector.js, r"/assets/scripts-[a-f0-9]+\.js$")

    async def test_deduplication(self, setup_registry):
        collector = AssetCollector()
        collector.add_by_name(qualified_name(Button))
        collector.add_by_name(qualified_name(Button))
        assert len(collector.css) == 1
        self.assert_matches(collector.css, r"/assets/styles-[a-f0-9]+\.css$")


class TestRouter:
    @pytest.fixture
    def app(self):
        app = FastAPI()
        router = APIRouter()

        @router.get("/")
        async def home(page: Annotated[PageRenderer, use_layout(AppLayout)]):
            return await page(section(h1("Home")), title="Home")

        @router.get("/user/{name}")
        async def user(name: str, page: Annotated[PageRenderer, use_layout(AppLayout)]):
            return await page(p(f"Hello, {name}!"), title=f"User: {name}")

        @router.get("/minimal")
        async def minimal(page: Annotated[PageRenderer, use_layout(MinimalLayout)]):
            return await page(p("Minimal page"))

        @router.get("/custom-class")
        async def custom_class(page: Annotated[PageRenderer, use_layout(AppLayout)]):
            return await page(p("Custom"), title="Custom", body_class="dark-mode")

        @router.get("/default-title")
        async def default_title(page: Annotated[PageRenderer, use_layout(AppLayout)]):
            # Uses default title="Page" from decorator
            return await page(p("Default"))

        @router.get("/json")
        async def json_route():
            return {"message": "json"}

        app.include_router(router)
        return app

    @pytest.fixture
    def client(self, app):
        return TestClient(app)

    @pytest.fixture(autouse=True)
    def setup(self, setup_registry):
        pass

    def test_layout_renders(self, client):
        response = client.get("/")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "<!DOCTYPE html>" in response.text
        assert "<title>Home</title>" in response.text
        assert "<section><h1>Home</h1></section>" in response.text

    def test_nav_component_rendered(self, client):
        response = client.get("/")
        assert "<nav>Welcome, Guest</nav>" in response.text

    def test_layout_with_params(self, client):
        response = client.get("/user/Bob")
        assert response.status_code == 200
        assert "<title>User: Bob</title>" in response.text
        assert "<p>Hello, Bob!</p>" in response.text

    def test_minimal_layout(self, client, prod_registry):
        response = client.get("/minimal")
        assert response.status_code == 200
        assert "<div class='minimal'>" in response.text
        assert "<!DOCTYPE" not in response.text

    def test_custom_body_class(self, client):
        response = client.get("/custom-class")
        assert 'class="dark-mode"' in response.text

    def test_default_title_from_decorator(self, client):
        response = client.get("/default-title")
        assert "<title>Page</title>" in response.text

    def test_json_passthrough(self, client):
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

        async def signup_template(form_class: type[SignupSchema], values, errors):
            return article(
                h1("Signup"),
                form_class.render(action="/signup", values=values, errors=errors),
            )

        async def login_template(form_class: type[LoginSchema], values, errors):
            return article(
                h1("Login"),
                form(
                    form_class.render_field("email", values.get("email"), errors.get("email")),
                    form_class.render_field("password", error=errors.get("password")),
                    button("Submit", type="submit"),
                    action="/login",
                    method="post",
                ),
            )

        @router.get("/login")
        async def login_page(page: Annotated[PageRenderer, use_layout(MinimalLayout)]):
            return await page(await login_template(LoginSchema, {}, {}))

        @router.post("/login")
        async def login(
            page: Annotated[PageRenderer[LoginSchema], use_layout(MinimalLayout, form=LoginSchema)],
        ):
            if page.errors:
                return await page.form_error(login_template)
            assert page.data is not None
            return await page(section(h1(f"Welcome, {page.data.email}!")))

        @router.get("/signup")
        async def signup_page(page: Annotated[PageRenderer, use_layout(MinimalLayout)]):
            return await page(await signup_template(SignupSchema, {}, {}))

        @router.post("/signup")
        async def signup(
            page: Annotated[
                PageRenderer[SignupSchema], use_layout(MinimalLayout, form=SignupSchema)
            ],
        ):
            if page.errors:
                return await page.form_error(signup_template)
            assert page.data is not None
            return await page(section(h1(f"Account created for {page.data.username}!")))

        app.include_router(router)
        return app

    @pytest.fixture
    def client(self, app):
        return TestClient(app)

    @pytest.fixture(autouse=True)
    def setup(self, setup_registry):
        pass

    def test_form_get_renders(self, client):
        response = client.get("/login")
        assert response.status_code == 200
        assert "<form" in response.text
        assert 'name="email"' in response.text

    def test_form_post_valid(self, client):
        response = client.post(
            "/login",
            data={"email": "user@example.com", "password": "secretpassword"},
        )
        assert response.status_code == 200
        assert "Welcome, user@example.com!" in response.text

    def test_form_post_invalid(self, client):
        response = client.post(
            "/login",
            data={"email": "not-an-email", "password": "secretpassword"},
        )
        assert response.status_code == 200
        assert "<form" in response.text
        assert 'aria-invalid="true"' in response.text

    def test_form_checkbox(self, client):
        response = client.post(
            "/signup",
            data={"username": "testuser", "email": "test@example.com", "agree_tos": "on"},
        )
        assert "Account created for testuser!" in response.text


class TestPageRenderer:
    @pytest.fixture
    def app(self, setup_registry):
        app = FastAPI()
        router = APIRouter()

        @router.get("/redirect-test")
        async def redirect_test(page: Annotated[PageRenderer, use_layout(MinimalLayout)]):
            return page.redirect("/target")

        @router.get("/refresh-test")
        async def refresh_test(page: Annotated[PageRenderer, use_layout(MinimalLayout)]):
            return page.refresh()

        @router.get("/is-htmx")
        async def is_htmx_route(page: Annotated[PageRenderer, use_layout(MinimalLayout)]):
            return await page(p(f"is_htmx: {page.is_htmx}"))

        app.include_router(router)
        return app

    @pytest.fixture
    def client(self, app):
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
    def app(self, setup_registry):
        app = FastAPI()
        router = APIRouter()

        @router.get("/with-layout")
        async def with_layout(page: Annotated[PageRenderer, use_layout(AppLayout)]):
            return await page(section(h1("With Layout")), title="Test")

        @router.get("/partial")
        async def partial():
            # No use_layout = no collector = no asset tracking
            btn = await Button("Click")
            return await render_html(btn)

        app.include_router(router)
        return app

    @pytest.fixture
    def client(self, app):
        return TestClient(app)

    def test_layout_collects_assets(self, client):
        response = client.get("/with-layout")
        assert response.status_code == 200
        assert "<head>" in response.text
        # NavBar component should be rendered
        assert "<nav>Welcome, Guest</nav>" in response.text

    def test_partial_no_layout(self, client):
        response = client.get("/partial")
        assert response.status_code == 200
        assert "<button class='btn'>Click</button>" in response.text
        assert "<!DOCTYPE" not in response.text


class TestIntegration:
    """Integration tests with raw render_html usage."""

    @pytest.fixture
    def app(self, setup_registry):
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
    def client(self, app):
        return TestClient(app)

    def test_home_page(self, client):
        response = client.get("/")
        assert response.status_code == 200
        assert "<!DOCTYPE html>" in response.text
        assert 'hx-get="/partial"' in response.text

    def test_partial_htmx(self, client):
        response = client.get("/partial", headers={"HX-Request": "true"})
        assert response.text == "<p>Partial loaded!</p>"

    def test_partial_direct(self, client):
        response = client.get("/partial")
        assert "<!DOCTYPE html>" in response.text

    def test_users_filtered(self, client):
        response = client.get("/users?q=ali")
        assert "<li>Alice</li>" in response.text
        assert "<li>Bob</li>" not in response.text
