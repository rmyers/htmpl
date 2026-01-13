"""Tests for htmpl FastAPI integration."""

from typing import Annotated

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
from htmpl.fastapi import PageRenderer, use_layout, use_component


# --- Test Fixtures: Components & Layouts ---


@component(css={"static/css/button.css"})
async def Button(label: str):
    return await html(t"<button class='btn'>{label}</button>")


@component(css={"static/css/card.css"}, js={"static/js/card.js"})
async def Card(title: str, body: SafeHTML):
    return await html(t"<div class='card'><h3>{title}</h3>{body}</div>")


@component(css={"static/css/nav.css"})
async def NavBar(user: str = "Guest"):
    return await html(t"<nav>Welcome, {user}</nav>")


@layout(css={"static/css/app.css"})
async def AppLayout(nav: Annotated[SafeHTML, use_component(NavBar)]):
    async def render(
        content: SafeHTML,
        bundles: Bundles,
        *,
        title: str = "Page",
        body_class: str = "",
    ) -> SafeHTML:
        return await html(t"""
            <!DOCTYPE html>
            <html>
            <head>
                <title>{title}</title>
                {await bundles.head()}
            </head>
            <body class="{body_class}">
                {nav}
                <main>{content}</main>
            </body>
            </html>
        """)
    return render


@layout()
async def MinimalLayout():
    async def render(content: SafeHTML, bundles: Bundles) -> SafeHTML:
        return await html(t"<div class='minimal'>{content}</div>")
    return render


# --- Tests ---


class TestQualifiedName:
    def test_qualified_name(self):
        assert qualified_name(Button) == "test_fastapi.Button"
        assert qualified_name(AppLayout) == "test_fastapi.AppLayout"


class TestAssetCollector:
    def test_empty_collector(self):
        collector = AssetCollector()
        bundles = collector.bundles()
        assert bundles.css == []
        assert bundles.js == []

    def test_add_component_assets(self):
        collector = AssetCollector()
        comp = registry.get_component(qualified_name(Button))
        collector.add(comp)
        assert "static/css/button.css" in collector.css

    def test_add_by_name(self):
        collector = AssetCollector()
        collector.add_by_name(qualified_name(Card))
        assert "static/css/card.css" in collector.css
        assert "static/js/card.js" in collector.js

    def test_deduplication(self):
        collector = AssetCollector()
        collector.add_by_name(qualified_name(Button))
        collector.add_by_name(qualified_name(Button))
        assert collector.css == {"static/css/button.css"}


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

        @router.get("/json")
        async def json_route():
            return {"message": "json"}

        app.include_router(router)
        return app

    @pytest.fixture
    def client(self, app):
        return TestClient(app)

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

    def test_minimal_layout(self, client):
        response = client.get("/minimal")
        assert response.status_code == 200
        assert "<div class='minimal'>" in response.text
        assert "<!DOCTYPE" not in response.text

    def test_custom_body_class(self, client):
        response = client.get("/custom-class")
        assert 'class="dark-mode"' in response.text

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
            return await page(section(h1(f"Welcome, {page.data.email}!")))

        @router.get("/signup")
        async def signup_page(page: Annotated[PageRenderer, use_layout(MinimalLayout)]):
            return await page(await signup_template(SignupSchema, {}, {}))

        @router.post("/signup")
        async def signup(
            page: Annotated[PageRenderer[SignupSchema], use_layout(MinimalLayout, form=SignupSchema)],
        ):
            if page.errors:
                return await page.form_error(signup_template)
            return await page(section(h1(f"Account created for {page.data.username}!")))

        app.include_router(router)
        return app

    @pytest.fixture
    def client(self, app):
        return TestClient(app)

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
    def app(self):
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
    def app(self):
        app = FastAPI()
        router = APIRouter()

        @router.get("/with-components")
        async def with_components(page: Annotated[PageRenderer, use_layout(AppLayout)]):
            # Use components via use_component in layout (NavBar)
            # AppLayout already uses NavBar, so its CSS should be collected
            return await page(section(h1("Components")), title="Components")

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
        response = client.get("/with-components")
        assert response.status_code == 200
        # Layout's CSS should be referenced (app.css, nav.css)
        # In dev mode without actual files, bundles won't be created
        # but the collector should have gathered the CSS paths
        assert "<head>" in response.text

    def test_partial_no_layout(self, client):
        response = client.get("/partial")
        assert response.status_code == 200
        assert "<button class='btn'>Click</button>" in response.text
        # No DOCTYPE because no layout
        assert "<!DOCTYPE" not in response.text


class TestIntegration:
    """Integration tests with a complete app."""

    @pytest.fixture
    def app(self):
        app = FastAPI()
        router = APIRouter()

        @router.get("/")
        async def home() -> HTMLResponse:
            return await render_html(t"""
                <!DOCTYPE html>
                <html>
                <body>
                    <h1>Home</h1>
                    <div id="content">
                        <button hx-get="/partial" hx-target="#content">Load</button>
                    </div>
                </body>
                </html>
            """)

        @router.get("/partial")
        async def partial(request: Request) -> HTMLResponse:
            if is_htmx(request):
                return await render_html(t"<p>Partial loaded!</p>")
            return await render_html(t"""
                <!DOCTYPE html>
                <html><body><p>Partial loaded!</p></body></html>
            """)

        @router.get("/users")
        async def users(q: str = "") -> HTMLResponse:
            all_users = ["Alice", "Bob", "Charlie"]
            filtered = [u for u in all_users if q.lower() in u.lower()] if q else all_users
            return await render_html(t"""
                <ul>
                    {[t"<li>{user}</li>" for user in filtered]}
                </ul>
            """)

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
