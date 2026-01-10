"""
Tests for htmpl FastAPI integration.
"""

import pytest
from fastapi import FastAPI, Request, Depends
from fastapi.testclient import TestClient
from pydantic import Field, EmailStr

from htmpl import html, forms, SafeHTML
from htmpl.elements import section, h1, p, div, article, form, button
from htmpl.fastapi import (
    HTMLRouter,
    HTMLForm,
    FormValidationError,
    form_validation_error_handler,
    is_htmx,
    htmx_target,
    htmx_trigger,
    htmx_redirect,
    htmx_refresh,
    htmx_retarget,
    htmx_trigger_event,
)


class TestRouter:
    @pytest.fixture
    def app(self):
        app = FastAPI()
        router = HTMLRouter()

        @router.get("/")
        async def home():
            return section(h1("Home"))

        @router.get("/user/{name}")
        async def user(name: str):
            return p(f"Hello, {name}!")

        @router.get("/template")
        async def template_route():
            name = "World"
            return t"<div>Hello, {name}!</div>"

        @router.get("/safe")
        async def safe_route():
            return SafeHTML("<strong>Safe</strong>")

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
        router = HTMLRouter()

        class LoginSchema(forms.BaseForm):
            email: EmailStr = Field(examples=["foo@bar.com"], description="Your email dah")
            password: str = Field(min_length=8)

        class SignupSchema(forms.BaseForm):
            username: str = Field(min_length=3, max_length=20)
            email: EmailStr
            agree_tos: bool

        async def signup_form(renderer: type[SignupSchema], values, errors):
            return article(
                h1("Custom Login"),
                renderer.render(values=values, errors=errors),
            )

        async def login_form(renderer: type[LoginSchema], values, errors):
            return article(
                h1("Custom Login"),
                form(
                    renderer.render_field("email", values.get("email"), errors.get("email")),
                    renderer.render_field("password", error=errors.get("password")),
                    button("Custom Submit", type="submit"),
                    action="/custom-login",
                ),
            )

        @router.get("/login")
        async def login_page():
            return await login_form(LoginSchema, {}, {})

        @router.post("/login")
        async def login(data: LoginSchema = Depends(HTMLForm(LoginSchema, login_form))):
            return section(h1(f"Welcome, {data.email}!"))

        @router.get("/signup")
        async def signup_page(data: SignupSchema = Depends(HTMLForm(SignupSchema, signup_form))):
            return await signup_form(SignupSchema, {}, {})

        @router.post("/signup")
        async def signup(data: SignupSchema = Depends(HTMLForm(SignupSchema, signup_form))):
            return section(h1(f"Account created for {data.username}!"))

        app.include_router(router)
        app.add_exception_handler(FormValidationError, form_validation_error_handler)  # type: ignore
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

    def test_form_post_invalid_email(self, client):
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


class TestHtmxRequestHelpers:
    @pytest.fixture
    def app(self):
        app = FastAPI()

        @app.get("/check-htmx")
        async def check_htmx(request: Request):
            return {
                "is_htmx": is_htmx(request),
                "target": htmx_target(request),
                "trigger": htmx_trigger(request),
            }

        return app

    @pytest.fixture
    def client(self, app):
        return TestClient(app)

    def test_not_htmx(self, client):
        response = client.get("/check-htmx")
        data = response.json()
        assert data["is_htmx"] is False
        assert data["target"] is None
        assert data["trigger"] is None

    def test_is_htmx(self, client):
        response = client.get("/check-htmx", headers={"HX-Request": "true"})
        data = response.json()
        assert data["is_htmx"] is True

    def test_htmx_target(self, client):
        response = client.get(
            "/check-htmx",
            headers={
                "HX-Request": "true",
                "HX-Target": "#my-div",
            },
        )
        data = response.json()
        assert data["target"] == "#my-div"

    def test_htmx_trigger(self, client):
        response = client.get(
            "/check-htmx",
            headers={
                "HX-Request": "true",
                "HX-Trigger": "my-button",
            },
        )
        data = response.json()
        assert data["trigger"] == "my-button"


class TestHtmxResponseHelpers:
    def test_htmx_redirect(self):
        response = htmx_redirect("/new-location")
        assert response.status_code == 200
        assert response.headers["HX-Redirect"] == "/new-location"

    def test_htmx_refresh(self):
        response = htmx_refresh()
        assert response.status_code == 200
        assert response.headers["HX-Refresh"] == "true"

    def test_htmx_retarget(self):
        content = SafeHTML("<p>content</p>")
        response = htmx_retarget(content, "#other-target")
        assert response.body == b"<p>content</p>"
        assert response.headers["HX-Retarget"] == "#other-target"

    def test_htmx_trigger_event_default(self):
        content = SafeHTML("<p>done</p>")
        response = htmx_trigger_event(content, "myEvent")
        assert response.headers["HX-Trigger-After-Settle"] == "myEvent"

    def test_htmx_trigger_event_after_swap(self):
        content = SafeHTML("")
        response = htmx_trigger_event(content, "myEvent", after="swap")
        assert response.headers["HX-Trigger-After-Swap"] == "myEvent"

    def test_htmx_trigger_event_receive(self):
        content = SafeHTML("")
        response = htmx_trigger_event(content, "myEvent", after="receive")
        assert response.headers["HX-Trigger"] == "myEvent"


class TestIntegration:
    """Integration tests with a more complete app."""

    @pytest.fixture
    def app(self):
        app = FastAPI()
        router = HTMLRouter()

        @router.get("/")
        async def home() -> SafeHTML:
            return await html(t"""
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
        async def partial(request: Request) -> SafeHTML:
            if is_htmx(request):
                return await html(t"<p>Partial content loaded!</p>")
            # Full page for direct access
            return await html(t"""
                <!DOCTYPE html>
                <html><body><p>Partial content loaded!</p></body></html>
            """)

        @router.get("/users")
        async def users(q: str = "") -> SafeHTML:
            all_users = ["Alice", "Bob", "Charlie"]
            filtered = [u for u in all_users if q.lower() in u.lower()] if q else all_users
            return await html(t"""
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
