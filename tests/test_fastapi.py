"""
Tests for htmpl FastAPI integration.
"""

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from htmpl import html, SafeHTML
from htmpl.fastapi import (
    Router,
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
        router = Router()

        @router.get('/')
        async def home() -> SafeHTML:
            return await html(t'''
                <!DOCTYPE html>
                <html>
                <body>
                    <h1>Home</h1>
                </body>
                </html>
            ''')


        app.include_router(router)
        return app

    @pytest.fixture
    def client(self, app):
        return TestClient(app)

    def test_get_routes(self, client):
        response = client.get('/')
        assert response.status_code == 200, response.text
        assert "Home" in response.text


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
        response = client.get("/check-htmx", headers={
            "HX-Request": "true",
            "HX-Target": "#my-div",
        })
        data = response.json()
        assert data["target"] == "#my-div"

    def test_htmx_trigger(self, client):
        response = client.get("/check-htmx", headers={
            "HX-Request": "true",
            "HX-Trigger": "my-button",
        })
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
        router = Router()

        @router.get("/")
        async def home() -> SafeHTML:
            return await html(t'''
                <!DOCTYPE html>
                <html>
                <body>
                    <h1>Home</h1>
                    <div id="content">
                        <button hx-get="/partial" hx-target="#content">Load</button>
                    </div>
                </body>
                </html>
            ''')

        @router.get("/partial")
        async def partial(request: Request) -> SafeHTML:
            if is_htmx(request):
                return await html(t"<p>Partial content loaded!</p>")
            # Full page for direct access
            return await html(t'''
                <!DOCTYPE html>
                <html><body><p>Partial content loaded!</p></body></html>
            ''')

        @router.get("/users")
        async def users(q: str = "") -> SafeHTML:
            all_users = ["Alice", "Bob", "Charlie"]
            filtered = [u for u in all_users if q.lower() in u.lower()] if q else all_users
            return await html(t'''
                <ul>
                    {[t"<li>{user}</li>" for user in filtered]}
                </ul>
            ''')

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
