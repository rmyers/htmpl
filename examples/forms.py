"""
Example form handling with Pydantic + htmpl + HTMX.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, FastAPI, Request
from pydantic import Field, EmailStr, field_validator

from htmpl import html, SafeHTML, render_html
from htmpl.assets import Bundles, layout
from htmpl.elements import button, section, h1, h2, p, article, form
from htmpl.forms import BaseForm, parse_form_errors
from htmpl.fastapi import PageRenderer, use_layout, use_bundles


router = APIRouter()


# --- Layout ---


@layout(title="Forms Demo")
async def FormsLayout(
    content: SafeHTML,
    bundles: Annotated[Bundles, Depends(use_bundles)],
    title: str,
):
    return await html(t"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>{title}</title>
            <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@picocss/pico@2/css/pico.min.css">
            <script src="https://unpkg.com/htmx.org@2.0.4"></script>
            <style>.error {{ color: var(--pico-del-color); }}</style>
            {await bundles.head()}
        </head>
        <body>
            <main class="container">{content}</main>
        </body>
        </html>
    """)


# --- Schema definitions with validation rules ---


class SignupForm(BaseForm):
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


class LoginForm(BaseForm):
    email: EmailStr = Field(title="Email")
    password: str = Field(title="Password")
    remember_me: bool = Field(default=False, title="Remember me")


class ContactForm(BaseForm):
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


# --- Templates ---


async def signup_template(form_class: type[SignupForm], values: dict, errors: dict):
    return article(
        h2("Create Account"),
        form(
            form_class.inline("username", "age", values=values, errors=errors),
            form_class.group("Contact", "email", "bio", values=values, errors=errors),
            form_class.inline("password", "confirm_password", values=values, errors=errors),
            form_class.render_field("plan", values.get("plan"), errors.get("plan")),
            form_class.render_field("agree_tos", values.get("agree_tos"), errors.get("agree_tos")),
            button("Sign Up", type="submit"),
            action="/signup",
            method="post",
        ),
    )


async def login_template(form_class: type[LoginForm], values: dict, errors: dict):
    return article(
        h1("Login"),
        form_class.render(action="/login", values=values, errors=errors, submit_text="Sign In"),
    )


async def contact_template(form_class: type[ContactForm], values: dict, errors: dict):
    return section(
        h1("Contact Us"),
        form_class.render(action="/contact", values=values, errors=errors, submit_text="Send Message"),
    )


# --- Routes ---


@router.get("/signup")
async def signup_page(page: Annotated[PageRenderer, use_layout(FormsLayout)]):
    values = {"username": "Bob"}
    return await page(await signup_template(SignupForm, values, {}), title="Sign Up")


@router.post("/signup")
async def signup_submit(
    page: Annotated[PageRenderer[SignupForm], use_layout(FormsLayout, form=SignupForm)],
):
    if page.errors:
        return await page.form_error(signup_template, title="Sign Up")

    # Success! Would save to DB here
    return await page(
        article(
            h1(f"Welcome, {page.data.username}!"),
            p("Your account has been created."),
        ),
        title="Welcome",
    )


@router.get("/login")
async def login_page(page: Annotated[PageRenderer, use_layout(FormsLayout)]):
    return await page(await login_template(LoginForm, {}, {}), title="Login")


@router.post("/login")
async def login_submit(
    page: Annotated[PageRenderer[LoginForm], use_layout(FormsLayout, form=LoginForm)],
):
    if page.errors:
        return await page.form_error(login_template, title="Login")

    # Would authenticate here
    return page.redirect("/dashboard")


@router.get("/contact")
async def contact_page(page: Annotated[PageRenderer, use_layout(FormsLayout)]):
    return await page(await contact_template(ContactForm, {}, {}), title="Contact Us")


@router.post("/contact")
async def contact_submit(
    page: Annotated[PageRenderer[ContactForm], use_layout(FormsLayout, form=ContactForm)],
):
    if page.errors:
        return await page.form_error(contact_template, title="Contact Us")

    # Would send email here
    return await page(
        article(
            h1("Message Sent"),
            p(f"Thanks {page.data.name}, we'll get back to you soon!"),
        ),
        title="Message Sent",
    )


# --- Inline HTMX validation endpoint ---


@router.post("/validate/{field}")
async def validate_field(field: str, request: Request):
    """Validate a single field via HTMX."""
    form_data = await request.form()
    value = form_data.get(field, "")

    field_info = SignupForm.model_fields.get(field)
    if not field_info:
        return await render_html(t"")

    try:
        SignupForm.__pydantic_validator__.validate_assignment(
            SignupForm.model_construct(),
            field,
            value,
        )
        return await render_html(t'<small class="success">✓</small>')
    except Exception as e:
        errors = parse_form_errors(e)
        msg = errors.get(field, "Invalid")
        return await render_html(t'<small class="error">{msg}</small>')


# App setup

app = FastAPI(debug=True)
app.include_router(router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("forms:app", host="0.0.0.0", port=8000, reload=True)
