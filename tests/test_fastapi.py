"""
Tests for htmpl FastAPI integration.
"""
from typing import Annotated

from fastapi.responses import HTMLResponse
import pytest
from fastapi import APIRouter, FastAPI, Request
from fastapi.testclient import TestClient
from pydantic import Field, EmailStr

from htmpl import html, forms, SafeHTML, render_html
from htmpl.elements import section, h1, p, article, form, button
from htmpl.htmx import is_htmx
from htmpl.fastapi import (
    PageRenderer,
    page,
)


class TestRouter:
    @pytest.fixture
    def app(self):
        app = FastAPI()
        router = APIRouter()

        @router.get("/")
        async def home(pr: Annotated[PageRenderer, page("home")]):
            return await pr(section(h1("Home")))

        @router.get("/user/{name}")
        async def user(name: str, pr: Annotated[PageRenderer, page("user")]):
            return await pr(p(f"Hello, {name}!"))

        @router.get("/template")
        async def template_route(pr: Annotated[PageRenderer, page("tr")]):
            name = "World"
            return await pr(t"<div>Hello, {name}!</div>")

        @router.get("/safe")
        async def safe_route(pr: Annotated[PageRenderer, page("sr")]):
            return await pr(SafeHTML("<strong>Safe</strong>"))

        @router.get("/json")
        async def json_route():
            return {"message": "json"}

        app.include_router(router)
        return app

    @pytest.fixture
    def client(self, app):
        return TestClient(app)

    def test_element_response(self, client):
        response = client.get("/")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "<section><h1>Home</h1></section>" in response.text

    def test_element_with_params(self, client):
        response = client.get("/user/Bob")
        assert response.status_code == 200
        assert "<p>Hello, Bob!</p>" in response.text

    def test_template_response(self, client):
        response = client.get("/template")
        assert response.status_code == 200
        assert "<div>Hello, World!</div>" in response.text

    def test_safehtml_response(self, client):
        response = client.get("/safe")
        assert response.status_code == 200
        assert "<strong>Safe</strong>" in response.text

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
            email: EmailStr = Field(examples=["foo@bar.com"], description="Your email dah")
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
                h1("Custom Login"),
                form(
                    form_class.render_field("email", values.get("email"), errors.get("email")),
                    form_class.render_field("password", error=errors.get("password")),
                    button("Custom Submit", type="submit"),
                    action="/login",
                    method="post",
                ),
            )

        @router.get("/login")
        async def login_page(pr: Annotated[PageRenderer, page("login_get")]):
            return await pr(await login_template(LoginSchema, {}, {}))

        @router.post("/login")
        async def login(
            pr: Annotated[PageRenderer[LoginSchema], page("login_post", form=LoginSchema)],
        ):
            if pr.errors:
                return await pr.form_error(login_template)
            return await pr(section(h1(f"Welcome, {pr.data.email}!")))

        @router.get("/signup")
        async def signup_page(pr: Annotated[PageRenderer, page("signup_get")]):
            return await pr(await signup_template(SignupSchema, {}, {}))

        @router.post("/signup")
        async def signup(
            pr: Annotated[PageRenderer[SignupSchema], page("signup_post", form=SignupSchema)],
        ):
            if pr.errors:
                return await pr.form_error(signup_template)
            return await pr(section(h1(f"Account created for {pr.data.username}!")))

        app.include_router(router)
        return app

    @pytest.fixture
    def client(self, app):
        return TestClient(app)

    def test_form_get_renders_form(self, client):
        response = client.get("/login")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "<form" in response.text
        assert 'name="email"' in response.text
        assert 'name="password"' in response.text
        assert 'placeholder="foo@bar.com"' in response.text
        assert "<small>Your email dah</small>" in response.text
        assert "Custom Submit" in response.text

    def test_form_post_valid_data(self, client):
        response = client.post(
            "/login",
            data={
                "email": "user@example.com",
                "password": "secretpassword",
            },
        )
        assert response.status_code == 200
        assert "Welcome, user@example.com!" in response.text

    def test_form_post_invalid_email(self, client: TestClient):
        response = client.post(
            "/login",
            data={
                "email": "not-an-email",
                "password": "secretpassword",
            },
        )
        assert response.status_code == 200
        assert "<form" in response.text
        assert 'aria-invalid="true"' in response.text
        assert 'value="not-an-email"' in response.text

    def test_form_post_password_too_short(self, client):
        response = client.post(
            "/login",
            data={
                "email": "user@example.com",
                "password": "short",
            },
        )
        assert response.status_code == 200
        assert "<form" in response.text
        assert 'value="user@example.com"' in response.text

    def test_form_post_missing_fields(self, client):
        response = client.post("/login", data={})
        assert response.status_code == 200
        assert "<form" in response.text

    def test_form_checkbox_true(self, client):
        response = client.post(
            "/signup",
            data={
                "username": "testuser",
                "email": "test@example.com",
                "agree_tos": "on",
            },
        )
        assert response.status_code == 200
        assert "Account created for testuser!" in response.text

    def test_form_checkbox_false(self, client):
        response = client.post(
            "/signup",
            data={
                "username": "testuser",
                "email": "test@example.com",
                # agree_tos not present = False
            },
        )
        assert response.status_code == 200
        # Validation should fail since agree_tos is required
        assert "<form" in response.text

    def test_form_custom_template_post_valid(self, client):
        response = client.post(
            "/login",
            data={
                "email": "user@example.com",
                "password": "secretpassword",
            },
        )
        assert response.status_code == 200
        assert "Welcome, user@example.com!" in response.text

    def test_form_custom_template_post_invalid(self, client):
        response = client.post(
            "/login",
            data={
                "email": "bad-email",
                "password": "secretpassword",
            },
        )
        assert response.status_code == 200
        assert "Custom Login" in response.text
        assert 'aria-invalid="true"' in response.text


class TestPageRenderer:
    """Test PageRenderer features."""

    @pytest.fixture
    def app(self):
        app = FastAPI()
        router = APIRouter()

        @router.get("/redirect-test")
        async def redirect_test(pr: Annotated[PageRenderer, page("redirect")]):
            return pr.redirect("/target")

        @router.get("/htmx-redirect-test")
        async def htmx_redirect_test(pr: Annotated[PageRenderer, page("htmx_redirect")]):
            return pr.redirect("/target")

        @router.get("/refresh-test")
        async def refresh_test(pr: Annotated[PageRenderer, page("refresh")]):
            return pr.refresh()

        @router.get("/is-htmx")
        async def is_htmx_route(pr: Annotated[PageRenderer, page("is_htmx")]):
            return await pr(p(f"is_htmx: {pr.is_htmx}"))

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
        response = client.get("/htmx-redirect-test", headers={"HX-Request": "true"})
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


class TestIntegration:
    """Integration tests with a more complete app."""

    @pytest.fixture
    def app(self):
        app = FastAPI()
        router = APIRouter()

        @router.get("/")
        async def home() -> HTMLResponse:
            return await render_html(
                t"""
                <!DOCTYPE html>
                <html>
                <body>
                    <h1>Home</h1>
                    <div id="content">
                        <button hx-get="/partial" hx-target="#content">Load</button>
                    </div>
                </body>
                </html>
            """
            )

        @router.get("/partial")
        async def partial(request: Request) -> HTMLResponse:
            if is_htmx(request):
                return await render_html(t"<p>Partial content loaded!</p>")
            # Full page for direct access
            return await render_html(
                t"""
                <!DOCTYPE html>
                <html><body><p>Partial content loaded!</p></body></html>
            """
            )

        @router.get("/users")
        async def users(q: str = "") -> HTMLResponse:
            all_users = ["Alice", "Bob", "Charlie"]
            filtered = [u for u in all_users if q.lower() in u.lower()] if q else all_users
            return await render_html(
                t"""
                <ul>
                    {[t"<li>{user}</li>" for user in filtered]}
                </ul>
            """
            )

        app.include_router(router)
        return app

    @pytest.fixture
    def client(self, app):
        return TestClient(app)

    def test_home_page(self, client):
        response = client.get("/")
        assert response.status_code == 200
        assert "<!DOCTYPE html>" in response.text
        assert "<h1>Home</h1>" in response.text
        assert 'hx-get="/partial"' in response.text

    def test_partial_htmx(self, client):
        response = client.get("/partial", headers={"HX-Request": "true"})
        assert response.status_code == 200
        assert response.text == "<p>Partial content loaded!</p>"
        assert "<!DOCTYPE" not in response.text

    def test_partial_direct(self, client):
        response = client.get("/partial")
        assert "<!DOCTYPE html>" in response.text

    def test_users_no_filter(self, client):
        response = client.get("/users")
        assert "<li>Alice</li>" in response.text
        assert "<li>Bob</li>" in response.text
        assert "<li>Charlie</li>" in response.text

    def test_users_filtered(self, client):
        response = client.get("/users?q=ali")
        assert "<li>Alice</li>" in response.text
        assert "<li>Bob</li>" not in response.text
