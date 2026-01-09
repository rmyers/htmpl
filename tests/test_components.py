"""
Tests for htmpl components.
"""

import pytest
from htmpl.components import (
    Document,
    Page,
    Nav,
    NavLink,
    Dropdown,
    Card,
    Grid,
    HGroup,
    Form,
    Field,
    TextArea,
    Select,
    Checkbox,
    Button,
    ButtonLink,
    Alert,
    Modal,
    Table,
    Loading,
)
from htmpl import html


class TestLayout:
    @pytest.mark.asyncio
    async def test_document_minimal(self):
        result = await Document("Test", await html(t"<p>content</p>"))
        assert "<!DOCTYPE html>" in result.content
        assert "<title>Test</title>" in result.content
        assert "<p>content</p>" in result.content
        assert "pico" in result.content

    @pytest.mark.asyncio
    async def test_document_with_theme(self):
        result = await Document("Test", await html(t""), theme="dark")
        assert 'data-theme="dark"' in result.content

    @pytest.mark.asyncio
    async def test_document_with_description(self):
        result = await Document("Test", await html(t""), description="A test page")
        assert 'name="description"' in result.content
        assert 'content="A test page"' in result.content

    @pytest.mark.asyncio
    async def test_page_with_nav(self):
        nav = await html(t"<nav>navigation</nav>")
        result = await Page("Test", await html(t"<p>body</p>"), nav=nav)
        assert "<nav>navigation</nav>" in result.content
        assert '<main class="container">' in result.content


class TestNavigation:
    @pytest.mark.asyncio
    async def test_nav_basic(self):
        result = await Nav("Brand", [("Home", "/"), ("About", "/about")])
        assert "<strong>Brand</strong>" in result.content
        assert 'href="/"' in result.content
        assert 'href="/about"' in result.content

    @pytest.mark.asyncio
    async def test_nav_link_active(self):
        result = await NavLink("Home", "/", active=True)
        assert 'aria-current="page"' in result.content

    @pytest.mark.asyncio
    async def test_dropdown(self):
        result = await Dropdown("Menu", [("Item 1", "/1"), ("Item 2", "/2")])
        assert "<details" in result.content
        assert "<summary>Menu</summary>" in result.content
        assert 'href="/1"' in result.content

    @pytest.mark.asyncio
    async def test_dropdown_right_align(self):
        result = await Dropdown("Menu", [], align="right")
        assert 'dir="rtl"' in result.content


class TestCards:
    @pytest.mark.asyncio
    async def test_card_basic(self):
        result = await Card(await html(t"<p>content</p>"))
        assert "<article>" in result.content
        assert "<p>content</p>" in result.content

    @pytest.mark.asyncio
    async def test_card_with_title(self):
        result = await Card(await html(t"body"), title="Title")
        assert "<header>Title</header>" in result.content

    @pytest.mark.asyncio
    async def test_card_with_footer(self):
        result = await Card(await html(t"body"), footer=await html(t"<button>OK</button>"))
        assert "<footer><button>OK</button></footer>" in result.content

    @pytest.mark.asyncio
    async def test_grid_basic(self):
        result = await Grid(await html(t"<div>item</div>"))
        assert 'class="grid"' in result.content

    @pytest.mark.asyncio
    async def test_grid_auto(self):
        result = await Grid(await html(t"<div>item</div>"), auto=True)
        assert 'class="grid grid-auto"' in result.content

    @pytest.mark.asyncio
    async def test_hgroup(self):
        result = await HGroup("Title", "Subtitle")
        assert "<hgroup>" in result.content
        assert "<h1>Title</h1>" in result.content
        assert "<p>Subtitle</p>" in result.content


class TestForms:
    @pytest.mark.asyncio
    async def test_form_basic(self):
        result = await Form(await html(t"<input>"), action="/submit")
        assert 'action="/submit"' in result.content
        assert 'method="post"' in result.content

    @pytest.mark.asyncio
    async def test_form_get_method(self):
        result = await Form(await html(t""), method="get")
        assert 'method="get"' in result.content

    @pytest.mark.asyncio
    async def test_field_basic(self):
        result = await Field("email", label="Email", type="email")
        assert "<label>" in result.content
        assert "Email" in result.content
        assert 'name="email"' in result.content
        assert 'type="email"' in result.content

    @pytest.mark.asyncio
    async def test_field_with_value(self):
        result = await Field("name", value="Bob")
        assert 'value="Bob"' in result.content

    @pytest.mark.asyncio
    async def test_field_with_error(self):
        result = await Field("email", error="Invalid email")
        assert 'aria-invalid="true"' in result.content
        assert "Invalid email" in result.content

    @pytest.mark.asyncio
    async def test_field_disabled(self):
        result = await Field("name", disabled=True)
        assert 'disabled="True"' in result.content

    @pytest.mark.asyncio
    async def test_textarea(self):
        result = await TextArea("bio", label="Bio", value="Hello", rows=6)
        assert "<textarea" in result.content
        assert 'name="bio"' in result.content
        assert 'rows="6"' in result.content
        assert "Hello</textarea>" in result.content

    @pytest.mark.asyncio
    async def test_select(self):
        result = await Select("color", [("r", "Red"), ("g", "Green")], label="Color")
        assert "<select" in result.content
        assert 'value="r"' in result.content
        assert "Red</option>" in result.content

    @pytest.mark.asyncio
    async def test_select_with_selected(self):
        result = await Select("color", [("r", "Red"), ("g", "Green")], selected="g")
        assert 'value="g" selected' in result.content

    @pytest.mark.asyncio
    async def test_checkbox(self):
        result = await Checkbox("agree", label="I agree")
        assert 'type="checkbox"' in result.content
        assert 'name="agree"' in result.content
        assert "I agree" in result.content

    @pytest.mark.asyncio
    async def test_checkbox_checked(self):
        result = await Checkbox("agree", label="I agree", checked=True)
        assert "checked" in result.content

    @pytest.mark.asyncio
    async def test_button_primary(self):
        result = await Button("Submit")
        assert "<button" in result.content
        assert "Submit</button>" in result.content
        assert 'type="submit"' in result.content

    @pytest.mark.asyncio
    async def test_button_variant(self):
        result = await Button("Cancel", variant="secondary")
        assert 'class="secondary"' in result.content

    @pytest.mark.asyncio
    async def test_button_busy(self):
        result = await Button("Loading", busy=True)
        assert 'aria-busy="true"' in result.content

    @pytest.mark.asyncio
    async def test_button_link(self):
        result = await ButtonLink("Go", "/path")
        assert 'href="/path"' in result.content
        assert 'role="button"' in result.content


class TestFeedback:
    @pytest.mark.asyncio
    async def test_alert_info(self):
        result = await Alert("Info message")
        assert "<small>" in result.content

    @pytest.mark.asyncio
    async def test_alert_success(self):
        result = await Alert("Success!", variant="success")
        assert "<ins>" in result.content

    @pytest.mark.asyncio
    async def test_alert_error(self):
        result = await Alert("Error!", variant="error")
        assert "<del>" in result.content

    @pytest.mark.asyncio
    async def test_alert_warning(self):
        result = await Alert("Warning!", variant="warning")
        assert "<mark>" in result.content

    @pytest.mark.asyncio
    async def test_modal(self):
        result = await Modal("my-modal", await html(t"<p>content</p>"), title="Title")
        assert '<dialog id="my-modal"' in result.content
        assert "<h3>Title</h3>" in result.content

    @pytest.mark.asyncio
    async def test_modal_open(self):
        result = await Modal("m", await html(t""), open=True)
        assert "open" in result.content


class TestDataDisplay:
    @pytest.mark.asyncio
    async def test_table(self):
        result = await Table(
            ["Name", "Age"],
            [["Alice", 30], ["Bob", 25]],
        )
        assert "<table>" in result.content
        assert "<th>Name</th>" in result.content
        assert "<td>Alice</td>" in result.content
        assert "<td>30</td>" in result.content

    @pytest.mark.asyncio
    async def test_loading(self):
        result = await Loading()
        assert 'aria-busy="true"' in result.content
        assert "Loading..." in result.content

    @pytest.mark.asyncio
    async def test_loading_custom_text(self):
        result = await Loading(text="Please wait...")
        assert "Please wait..." in result.content
