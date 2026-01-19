"""
Tests for htmpl form handling.
"""

from typing import Literal

import pytest
from pydantic import BaseModel, Field, ValidationError, EmailStr

from htmpl.forms import (
    BaseForm,
    FieldConfig,
    parse_form_errors,
    _label_from_name,
    _infer_input_type,
)


# Test models


class SimpleForm(BaseForm):
    name: str
    email: str


class ValidatedForm(BaseForm):
    username: str = Field(min_length=3, max_length=20)
    age: int = Field(ge=18, le=120)
    website: str = Field(default="")


class FullForm(BaseForm):
    name: str = Field(title="Full Name", description="Enter your name")
    email: EmailStr = Field(title="Email Address")
    password: str = Field(min_length=8)
    bio: str = Field(
        default="", json_schema_extra={"form_widget": "textarea", "rows": 6}
    )
    role: Literal["admin", "user", "guest"] = Field(default="user")
    agree: bool = Field(default=False, title="I agree to terms")


class ChoicesForm(BaseForm):
    priority: str = Field(
        default="normal",
        json_schema_extra={
            "form_widget": "radio",
            "form_choices": [["low", "Low"], ["normal", "Normal"], ["high", "High"]],
        },
    )
    country: str = Field(
        json_schema_extra={
            "form_widget": "select",
            "form_choices": [
                ["us", "United States"],
                ["uk", "United Kingdom"],
                ["ca", "Canada"],
            ],
        },
    )


class TestHelpers:
    def test_label_from_name(self):
        assert _label_from_name("first_name") == "First Name"
        assert _label_from_name("email") == "Email"
        assert _label_from_name("user_id") == "User Id"

    def test_infer_input_type_by_type(self):
        assert _infer_input_type(int, "count") == "number"
        assert _infer_input_type(float, "price") == "number"
        assert _infer_input_type(bool, "active") == "checkbox"
        assert _infer_input_type(str, "name") == "text"

    def test_infer_input_type_by_name(self):
        assert _infer_input_type(str, "password") == "password"
        assert _infer_input_type(str, "user_password") == "password"
        assert _infer_input_type(str, "email") == "email"
        assert _infer_input_type(str, "user_email") == "email"
        assert _infer_input_type(str, "website") == "url"
        assert _infer_input_type(str, "phone") == "tel"
        assert _infer_input_type(str, "telephone") == "tel"
        assert _infer_input_type(str, "birth_date") == "date"
        assert _infer_input_type(str, "start_time") == "time"
        assert _infer_input_type(str, "created_datetime") == "datetime-local"


class TestFieldConfig:
    def test_basic_config(self):
        renderer = SimpleForm

        assert "name" in renderer.get_field_configs()
        assert "email" in renderer.get_field_configs()

        name_cfg = renderer.get_field_configs()["name"]
        assert name_cfg.name == "name"
        assert name_cfg.label == "Name"
        assert name_cfg.type == "text"
        assert name_cfg.required is True
        assert name_cfg.widget == "input"

    def test_validation_constraints(self):
        renderer = ValidatedForm

        username_cfg = renderer.get_field_configs()["username"]
        assert username_cfg.minlength == 3
        assert username_cfg.maxlength == 20

        age_cfg = renderer.get_field_configs()["age"]
        assert age_cfg.min == 18
        assert age_cfg.max == 120
        assert age_cfg.type == "number"

    def test_custom_title(self):
        renderer = FullForm

        name_cfg = renderer.get_field_configs()["name"]
        assert name_cfg.label == "Full Name"

        email_cfg = renderer.get_field_configs()["email"]
        assert email_cfg.label == "Email Address"

    def test_widget_override(self):
        renderer = FullForm

        bio_cfg = renderer.get_field_configs()["bio"]
        assert bio_cfg.widget == "textarea"
        assert bio_cfg.rows == 6

    def test_literal_creates_choices(self):
        renderer = FullForm

        role_cfg = renderer.get_field_configs()["role"]
        assert role_cfg.widget == "select"
        assert role_cfg.choices == [
            ["admin", "admin"],
            ["user", "user"],
            ["guest", "guest"],
        ]

    def test_bool_creates_checkbox(self):
        renderer = FullForm

        agree_cfg = renderer.get_field_configs()["agree"]
        assert agree_cfg.widget == "checkbox"
        assert agree_cfg.type == "checkbox"

    def test_custom_choices(self):
        renderer = ChoicesForm

        priority_cfg = renderer.get_field_configs()["priority"]
        assert priority_cfg.widget == "radio"
        assert priority_cfg.choices == [
            ["low", "Low"],
            ["normal", "Normal"],
            ["high", "High"],
        ]

        country_cfg = renderer.get_field_configs()["country"]
        assert country_cfg.widget == "select"
        assert ["us", "United States"] in country_cfg.choices

    def test_configure_override(self):
        renderer = SimpleForm
        renderer.configure_field("name", label="Your Name", placeholder="John Doe")

        name_cfg = renderer.get_field_configs()["name"]
        assert name_cfg.label == "Your Name"
        assert name_cfg.placeholder == "John Doe"


class TestFormRendering:
    def test_render_simple_form(self):
        renderer = SimpleForm
        element = renderer.render(action="/submit")

        html = str(element)

        assert "<form" in html
        assert 'action="/submit"' in html
        assert 'method="post"' in html
        assert 'name="name"' in html
        assert 'name="email"' in html
        assert 'type="submit"' in html
        assert "Submit" in html

    def test_render_with_values(self):
        renderer = SimpleForm
        element = renderer.render(
            action="/submit",
            values={"name": "Bob", "email": "bob@example.com"},
        )

        html = str(element)

        assert 'value="Bob"' in html
        assert 'value="bob@example.com"' in html

    def test_render_with_errors(self):
        renderer = SimpleForm
        element = renderer.render(
            action="/submit",
            values={"name": "", "email": "invalid"},
            errors={"name": "Name is required", "email": "Invalid email"},
        )

        html = str(element)

        assert 'aria-invalid="true"' in html
        assert "Name is required" in html
        assert "Invalid email" in html
        assert 'class="error"' in html

    def test_render_descriptions(self):
        renderer = FullForm
        element = renderer.render(action="/submit")

        html = str(element)

        assert 'name="name"' in html
        assert "<small>Enter your name</small>" in html

    def test_custom_submit_text(self):
        renderer = SimpleForm
        element = renderer.render(action="/submit", submit_text="Create Account")

        html = str(element)

        assert "Create Account" in html

    def test_extra_form_attrs(self):
        renderer = SimpleForm
        element = renderer.render(
            action="/submit",
            id="signup-form",
            class_="my-form",
        )

        html = str(element)

        assert 'id="signup-form"' in html
        assert 'class="my-form"' in html


class TestFieldRendering:
    def test_render_input(self):
        renderer = ValidatedForm
        element = renderer.render_field("username")

        html = str(element)

        assert "<label>" in html
        assert "<input" in html
        assert 'name="username"' in html
        assert 'minlength="3"' in html
        assert 'maxlength="20"' in html
        assert "required" in html

    def test_render_number_input(self):
        renderer = ValidatedForm
        element = renderer.render_field("age", value=25)

        html = str(element)

        assert 'type="number"' in html
        assert 'min="18"' in html
        assert 'max="120"' in html
        assert 'value="25"' in html

    def test_render_textarea(self):
        renderer = FullForm
        element = renderer.render_field("bio", value="Hello world")

        html = str(element)

        assert "<textarea" in html
        assert 'name="bio"' in html
        assert 'rows="6"' in html
        assert "Hello world</textarea>" in html

    def test_render_select(self):
        renderer = FullForm
        element = renderer.render_field("role", value="admin")

        html = str(element)

        assert "<select" in html
        assert 'name="role"' in html
        assert '<option value="admin" selected' in html
        assert '<option value="user"' in html
        assert '<option value="guest"' in html

    def test_render_checkbox(self):
        renderer = FullForm
        element = renderer.render_field("agree", value=True)

        html = str(element)

        assert 'type="checkbox"' in html
        assert 'name="agree"' in html
        assert "checked" in html
        assert "I agree to terms" in html

    def test_render_radio(self):
        renderer = ChoicesForm
        element = renderer.render_field("priority", value="high")

        html = str(element)

        assert "<fieldset>" in html
        assert "<legend>" in html
        assert 'type="radio"' in html
        assert 'value="low"' in html
        assert 'value="normal"' in html
        assert 'value="high" checked' in html

    def test_render_unknown_field_raises(self):
        renderer = SimpleForm

        with pytest.raises(ValueError, match="Unknown field"):
            renderer.render_field("unknown")


class TestParseFormErrors:
    def test_single_error(self):
        class TestModel(BaseModel):
            name: str = Field(min_length=3)

        try:
            TestModel(name="ab")
        except ValidationError as e:
            errors = parse_form_errors(e)
            assert "name" in errors
            assert len(errors) == 1

    def test_multiple_errors(self):
        class TestModel(BaseModel):
            name: str = Field(min_length=3)
            age: int = Field(ge=0)

        try:
            TestModel(name="ab", age=-1)
        except ValidationError as e:
            errors = parse_form_errors(e)
            assert "name" in errors
            assert "age" in errors
            assert len(errors) == 2

    def test_missing_field_error(self):
        try:
            SimpleForm()  # type: ignore
        except ValidationError as e:
            errors = parse_form_errors(e)
            assert "name" in errors
            assert "email" in errors


class TestEmailInference:
    def test_email_str_type(self):
        renderer = FullForm
        element = renderer.render_field("email")

        html = str(element)

        assert 'type="email"' in html


class TestCustomLayout:
    def test_input_only(self):
        renderer = SimpleForm
        element = renderer.input("name", value="Bob")

        html = str(element)

        assert "<input" in html
        assert 'value="Bob"' in html
        assert 'id="name"' in html
        assert "<label>" not in html

    def test_input_with_extra_attrs(self):
        renderer = SimpleForm
        element = renderer.input("name", class_="custom", data_test="value")

        html = str(element)

        assert 'class="custom"' in html
        assert 'data-test="value"' in html

    def test_label_for(self):
        renderer = FullForm
        element = renderer.label_for("email")

        html = str(element)

        assert "<label" in html
        assert 'for="email"' in html
        assert "Email Address" in html

    def test_error_for_with_error(self):
        renderer = SimpleForm
        element = renderer.error_for("name", {"name": "Required"})

        html = str(element)

        assert "Required" in html
        assert 'class="error"' in html

    def test_error_for_without_error(self):
        renderer = SimpleForm
        element = renderer.error_for("name", {})

        assert element is None

    def test_fields_list(self):
        renderer = SimpleForm
        elements = renderer.form_fields("name", "email", values={"name": "Bob"})

        assert len(elements) == 2

        html = str(elements[0])
        assert 'name="name"' in html
        assert 'value="Bob"' in html

    def test_inline_fields(self):
        renderer = SimpleForm
        element = renderer.inline("name", "email")

        html = str(element)

        assert 'class="grid"' in html
        assert 'name="name"' in html
        assert 'name="email"' in html

    def test_group_fields(self):
        renderer = FullForm
        element = renderer.group("Account Info", "name", "email")

        html = str(element)

        assert "<fieldset>" in html
        assert "<legend>" in html
        assert "Account Info" in html
        assert 'name="name"' in html
        assert 'name="email"' in html
