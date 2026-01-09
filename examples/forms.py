"""
Example form handling with Pydantic + htmpl + HTMX.
"""

from typing import Literal

from fastapi import FastAPI, Request, Form
from pydantic import BaseModel, Field, EmailStr, field_validator

from htmpl import html, SafeHTML
from htmpl.elements import button, section, h1, h2, p, div, article, form
from htmpl.forms import FormRenderer, parse_form_errors
from htmpl.fastapi import html_response
from htmpl.htmx import HX


app = FastAPI(debug=True)


# --- Schema definitions with validation rules ---


class SignupSchema(BaseModel):
    username: str = Field(
        min_length=3,
        max_length=20,
        title="Username",
        description="Letters, numbers, underscores only",
        json_schema_extra={"pattern": r"^\w+$"},
    )
    email: EmailStr = Field(title="Email Address")
    password: str = Field(
        min_length=8,
        title="Password",
        description="At least 8 characters",
    )
    confirm_password: str = Field(min_length=8, title="Confirm Password")
    age: int = Field(ge=18, le=120, title="Age")
    plan: Literal["free", "pro", "enterprise"] = Field(
        default="free",
        title="Plan",
        json_schema_extra={
            "form_widget": "select",
            "form_choices": [
                ["free", "Free - $0/mo"],
                ["pro", "Pro - $10/mo"],
                ["enterprise", "Enterprise - $50/mo"],
            ],
        },
    )
    bio: str = Field(
        default="",
        max_length=500,
        title="Bio",
        json_schema_extra={"form_widget": "textarea"},
    )
    agree_tos: bool = Field(title="I agree to the Terms of Service")

    @field_validator("confirm_password")
    @classmethod
    def passwords_match(cls, v, info):
        if "password" in info.data and v != info.data["password"]:
            raise ValueError("Passwords do not match")
        return v


class LoginSchema(BaseModel):
    email: EmailStr = Field(title="Email")
    password: str = Field(title="Password")
    remember_me: bool = Field(default=False, title="Remember me")


class ContactSchema(BaseModel):
    name: str = Field(min_length=2, title="Your Name")
    email: EmailStr = Field(title="Email")
    subject: str = Field(min_length=5, max_length=100, title="Subject")
    message: str = Field(
        min_length=20,
        max_length=2000,
        title="Message",
        json_schema_extra={"form_widget": "textarea", "rows": 6},
    )
    priority: Literal["low", "normal", "high"] = Field(
        default="normal",
        title="Priority",
        json_schema_extra={
            "form_widget": "radio",
            "form_choices": [["low", "Low"], ["normal", "Normal"], ["high", "High"]],
        },
    )


# --- Create form renderers ---

signup_form = FormRenderer(SignupSchema)
login_form = FormRenderer(LoginSchema)
contact_form = FormRenderer(ContactSchema)


def render_signup(values: dict, errors: dict):
    return form(
        h2("Create Account"),
        # Inline fields (grid row)
        signup_form.inline("username", "age", values=values, errors=errors),
        # Grouped fields
        signup_form.group("Contact", "email", "bio", values=values, errors=errors),
        signup_form.inline("password", "confirm_password", values=values, errors=errors),
        # Regular wrapped field
        signup_form.render_field("agree_tos", value=values, error=errors),
        button("Sign Up", type="submit"),
        action="/signup",
        method="post",
        hx_boost="true",
    )


# --- Routes ---


@app.get("/signup")
@html_response
async def signup_page() -> SafeHTML:
    values = {"username": "Bob"}
    custom_form = render_signup(values, {})

    return await html(t"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Sign Up</title>
            <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@picocss/pico@2/css/pico.min.css">
            <script src="https://unpkg.com/htmx.org@2.0.4"></script>
            <style>.error {{ color: var(--pico-del-color); }}</style>
        </head>
        <body>
            <main class="container">
                {custom_form}
            </main>
        </body>
        </html>
    """)


@app.post("/signup")
@html_response
async def signup_submit(request: Request) -> SafeHTML:
    form_data = await request.form()
    data = dict(form_data)
    print(data)
    # Convert checkbox
    data["agree_tos"] = "agree_tos" in data

    # Validate
    try:
        validated = SignupSchema(**data)
        # Success! Would save to DB here
        return await html(t"""
            {
            article(
                h1("Welcome, {validated.username}!"),
                p("Your account has been created."),
            )
        }
        """)
    except Exception as e:
        print(e)
        errors = parse_form_errors(e)
        # Re-render form with errors
        custom_form = render_signup(data, errors)

        return await html(t"""
            <!DOCTYPE html>
            <html>
            <head>
                <title>Sign Up</title>
                <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@picocss/pico@2/css/pico.min.css">
                <script src="https://unpkg.com/htmx.org@2.0.4"></script>
                <style>.error {{ color: var(--pico-del-color); }}</style>
            </head>
            <body>
                <main class="container">
                    {custom_form}
                </main>
            </body>
            </html>
        """)


@app.get("/login")
@html_response
async def login_page() -> SafeHTML:
    return await html(t"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Login</title>
            <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@picocss/pico@2/css/pico.min.css">
            <style>.error {{ color: var(--pico-del-color); }}</style>
        </head>
        <body>
            <main class="container">
                {
        article(
            h1("Login"),
            login_form.render(action="/login", submit_text="Sign In"),
        )
    }
            </main>
        </body>
        </html>
    """)


@app.get("/contact")
@html_response
async def contact_page() -> SafeHTML:
    return await html(t"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Contact Us</title>
            <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@picocss/pico@2/css/pico.min.css">
            <style>.error {{ color: var(--pico-del-color); }}</style>
        </head>
        <body>
            <main class="container">
                {
        section(
            h1("Contact Us"),
            contact_form.render(action="/contact", submit_text="Send Message"),
        )
    }
            </main>
        </body>
        </html>
    """)


# --- Inline HTMX validation endpoint ---


@app.post("/validate/{field}")
@html_response
async def validate_field(field: str, request: Request) -> SafeHTML:
    """Validate a single field via HTMX."""
    form_data = await request.form()
    value = form_data.get(field, "")

    # Partial validation using field's type
    field_info = SignupSchema.model_fields.get(field)
    if not field_info:
        return await html(t"")

    try:
        # Validate just this field
        SignupSchema.__pydantic_validator__.validate_assignment(
            SignupSchema.model_construct(),
            field,
            value,
        )
        return await html(t'<small class="success">✓</small>')
    except Exception as e:
        errors = parse_form_errors(e)
        msg = errors.get(field, "Invalid")
        return await html(t'<small class="error">{msg}</small>')


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("forms:app", host="0.0.0.0", port=8000, reload=True)
