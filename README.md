# htmpl

Type-safe HTML templating for Python 3.14+ using [PEP 750](https://peps.python.org/pep-0750/) template strings.

```python
from htmpl import html
from htmpl.elements import div, h1, p, ul, li

async def greeting(name: str, items: list[str]):
    return div(
        h1(f"Hello, {name}!"),
        t"<p>You have <strong>{len(items)}</strong> items:</p>",
        ul([li(item) for item in items]),
        class_="card",
    )
```

## Why htmpl?

- **Type-safe** — Components are functions with typed parameters. Your IDE catches errors.
- **No new syntax** — It's just Python. No `{% %}` or `{{ }}` to learn.
- **Async-native** — Coroutines resolve automatically at render time. No await spam.
- **Composable** — Mix element factories and t-strings freely.
- **XSS-safe** — All interpolations escaped by default.
- **Fast** — Cache components with `@cached`, `@cached_lru`, or `@cached_ttl`.

## Installation

```bash
pip install htmpl              # Core only
pip install htmpl[all]         # Everything
```

Requires Python 3.14+.

## Quick Start

### Elements

Build HTML with function calls:

```python
from htmpl.elements import div, h1, p, a, ul, li, button

# Simple element
div("Hello")  # <div>Hello</div>

# With attributes
div("Hello", class_="greeting", id="main")  # <div class="greeting" id="main">Hello</div>

# Nested
div(
    h1("Title"),
    p("Some text"),
    a("Click me", href="/page"),
)

# Lists flatten automatically
ul([li(item) for item in ["one", "two", "three"]])
```

### T-strings

Use Python 3.14 template strings for inline HTML:

```python
from htmpl import html

name = "World"
await html(t"<h1>Hello, {name}!</h1>")
```

Values are escaped automatically:

```python
user_input = "<script>alert('xss')</script>"
await html(t"<p>{user_input}</p>")
# <p>&lt;script&gt;alert('xss')&lt;/script&gt;</p>
```

### Mix Both

Elements and t-strings compose freely:

```python
def UserCard(user: User):
    return article(
        t"<header>{user.name}</header>",
        p(user.bio),
        div(
            [Badge(role) for role in user.roles],
            class_="badges",
        ),
    )
```

### Async Components

Async functions just work—coroutines resolve at render time:

```python
async def UserProfile(user_id: int):
    user = await get_user(user_id)  # DB call
    posts = await get_posts(user_id)

    return section(
        h1(user.name),
        PostList(posts),  # Can be sync or async
    )

# No awaits needed when composing
def Dashboard(user_id: int):
    return div(
        UserProfile(user_id),  # Coroutine, resolved at render
        Sidebar(),
    )
```

### Conditional Rendering

Return `None` to render nothing:

```python
def AdminBadge(user: User):
    if not user.is_admin:
        return None
    return span("Admin", class_="badge")

# Renders badge only for admins
div(
    h1(user.name),
    AdminBadge(user),  # None disappears cleanly
)
```

## Caching

```python
from htmpl import cached, cached_lru, cached_ttl

@cached  # Forever
async def Footer():
    return footer(t"<p>© 2025</p>")

@cached_lru(maxsize=100)  # LRU eviction
async def UserBadge(role: str):
    return span(role, class_="badge")

@cached_ttl(seconds=60)  # Expires after 60s
async def GlobalStats():
    stats = await fetch_stats()
    return div(t"<strong>{stats.users}</strong> users")
```

## FastAPI Integration

```python
from fastapi import FastAPI
from htmpl.fastapi import Router
from htmpl.elements import section, h1, p

app = FastAPI()
router = Router()

@router.get("/")
async def home():
    return section(h1("Welcome"), p("Just return Elements."))

@router.get("/user/{name}")
async def user(name: str):
    return section(h1(f"Hello, {name}!"))

app.include_router(router)
```

The `Router` automatically converts `Element`, `Fragment`, `SafeHTML`, and `Template` returns to HTML responses.

## HTMX Integration

```python
from htmpl.htmx import HX, SearchInput, LazyLoad

# HX attribute builder
hx = HX(post="/api/save", target="#result", swap="innerHTML")
button("Save", **{str(k): v for k, v in hx})

# Or use built-in patterns
SearchInput("q", src="/search", target="#results", debounce=300)
LazyLoad("/api/content", placeholder=div("Loading...", aria_busy="true"))
```

## Forms

Render Pydantic models as forms with automatic HTML5 validation:

```python
from pydantic import BaseModel, Field, EmailStr
from htmpl.fastapi import Router
from htmpl.elements import section, h1

router = Router()

class LoginSchema(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)

@router.form("/login", LoginSchema, submit_text="Sign In")
async def login(data: LoginSchema):
    # Only called if validation passes
    user = await authenticate(data.email, data.password)
    return section(h1(f"Welcome, {user.name}!"))
```

The `@router.form` decorator:

- **GET /login** → Renders the form
- **POST /login** → Validates, re-renders with errors or calls your handler

Generates proper HTML5 validation attributes:

```html
<input type="email" name="email" required />
<input type="password" name="password" required minlength="8" />
```

### Custom Form Layouts

Use the `template` parameter for full control:

```python
from htmpl.elements import article, h2, form, div, button

def login_template(renderer, values, errors):
    return article(
        h2("Sign In"),
        form(
            renderer.inline("email", "password", values=values, errors=errors),
            button("Sign In", type="submit"),
            action="/login",
        ),
    )

@router.form("/login", LoginSchema, template=login_template)
async def login(data: LoginSchema):
    user = await authenticate(data.email, data.password)
    return section(h1(f"Welcome, {user.name}!"))
```

Or use `FormRenderer` directly for maximum flexibility:

```python
from htmpl.forms import FormRenderer

renderer = FormRenderer(SignupSchema)

form(
    renderer.inline("first_name", "last_name", values=values),
    renderer.group("Contact", "email", "phone", values=values, errors=errors),

    # Manual control
    div(
        renderer.label_for("password"),
        renderer.input("password", class_="custom"),
        renderer.error_for("password", errors),
    ),

    button("Submit", type="submit"),
    action="/submit",
)
```

## Components Library

Built-in Pico CSS components:

```python
from htmpl import Document, Page, Nav, Card, Form, Field, Button, Alert, Modal, Table, Grid

Page(
    "My App",
    nav=Nav("Brand", [("Home", "/"), ("About", "/about")]),
    children=section(
        Card(
            p("Card content"),
            title="Card Title",
        ),
    ),
)
```

## API Reference

### Core

| Function            | Description                        |
| ------------------- | ---------------------------------- |
| `html(template)`    | Process a t-string into `SafeHTML` |
| `raw(str)`          | Mark string as safe (no escaping)  |
| `attr(name, value)` | Build a safe HTML attribute        |
| `SafeHTML`          | Wrapper for pre-escaped content    |

### Elements

All standard HTML elements as functions:

```python
from htmpl.elements import (
    # Layout
    div, span, section, article, header, footer, nav, main, aside,
    # Text
    h1, h2, h3, h4, h5, h6, p, a, strong, em, code, pre,
    # Lists
    ul, ol, li,
    # Tables
    table, thead, tbody, tr, th, td,
    # Forms
    form, label, input_, button, select, option, textarea,
    # Media
    img, video, audio,
    # Other
    br, hr, fragment,
)
```

Attributes use `_` suffix for Python keywords: `class_`, `for_`, `type_`.

### Forms

| Method                    | Description               |
| ------------------------- | ------------------------- |
| `render()`                | Full form with all fields |
| `render_field(name)`      | Single field with label   |
| `input(name)`             | Just the input element    |
| `label_for(name)`         | Just the label            |
| `error_for(name, errors)` | Error message if present  |
| `fields(*names)`          | Multiple fields as list   |
| `inline(*names)`          | Fields in grid row        |
| `group(title, *names)`    | Fields in fieldset        |

## Comparison

| Feature        | htmpl | Jinja   | React    |
| -------------- | ----- | ------- | -------- |
| Type safety    | ✅    | ❌      | ✅ (TSX) |
| Python-native  | ✅    | ❌      | ❌       |
| Async support  | ✅    | ❌      | ❌       |
| No build step  | ✅    | ✅      | ❌       |
| IDE support    | ✅    | Limited | ✅       |
| Learning curve | Low   | Medium  | High     |

## License

MIT
