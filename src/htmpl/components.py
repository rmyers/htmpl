"""
Async Pico CSS-based component library.
"""

from __future__ import annotations

from typing import Literal, Any
from .core import html, SafeHTML, cached, attr


Theme = Literal["light", "dark", "auto"]
ButtonVariant = Literal["primary", "secondary", "contrast", "outline"]
AlertVariant = Literal["info", "success", "warning", "error"]


# Layout Components


async def Document(
    title: str,
    children: SafeHTML,
    *,
    theme: Theme = "dark",
    description: str | None = None,
    head: SafeHTML | None = None,
    scripts: SafeHTML | None = None,
) -> SafeHTML:
    """Base HTML document with Pico CSS."""
    meta_desc = (
        await html(t'<meta name="description" content="{description}">') if description else None
    )

    return await html(t'''<!DOCTYPE html>
<html lang="en" data-theme="{theme}">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{title}</title>
    {meta_desc}
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@picocss/pico@2/css/pico.min.css">
    <style>
        :root {{ --pico-font-size: 100%; }}
        .grid-auto {{ grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); }}
        .text-center {{ text-align: center; }}
        .text-muted {{ opacity: 0.7; }}
        .mt-1 {{ margin-top: 1rem; }}
        .mb-1 {{ margin-bottom: 1rem; }}
        .visually-hidden {{
            position: absolute;
            width: 1px;
            height: 1px;
            padding: 0;
            margin: -1px;
            overflow: hidden;
            clip: rect(0, 0, 0, 0);
            border: 0;
        }}
    </style>
    {head}
</head>
<body>
    {children}
    {scripts}
</body>
</html>''')


async def Page(
    title: str,
    children: SafeHTML,
    *,
    nav: SafeHTML | None = None,
    footer: SafeHTML | None = None,
    theme: Theme = "auto",
    description: str | None = None,
    head: SafeHTML | None = None,
    scripts: SafeHTML | None = None,
) -> SafeHTML:
    """Standard page layout with nav and container."""
    return await Document(
        title=title,
        theme=theme,
        description=description,
        head=head,
        scripts=scripts,
        children=await html(t"""
            {nav}
            <main class="container">
                {children}
            </main>
            {footer}
        """),
    )


# Navigation


async def Nav(
    brand: str,
    items: list[tuple[str, str]],
    *,
    end_items: SafeHTML | None = None,
) -> SafeHTML:
    """Primary navigation bar."""
    links = await html(t"{[NavLink(label, href) for label, href in items]}")
    return await html(
        t'<nav class="container"><ul><li><strong>{brand}</strong></li></ul><ul>{links}{end_items}</ul></nav>'
    )


async def NavLink(label: str, href: str, *, active: bool = False) -> SafeHTML:
    """Navigation link item."""
    return await html(
        t'<li><a href="{href}" {attr("aria-current", "page" if active else None)}>{label}</a></li>'
    )


async def Dropdown(
    label: str,
    items: list[tuple[str, str]],
    *,
    align: Literal["left", "right"] = "left",
) -> SafeHTML:
    """Dropdown menu."""
    menu_items = await html(t"{[DropdownItem(lbl, href) for lbl, href in items]}")
    return await html(
        t'<li><details class="dropdown"><summary>{label}</summary><ul {attr("dir", "rtl" if align == "right" else None)}>{menu_items}</ul></details></li>'
    )


async def DropdownItem(label: str, href: str) -> SafeHTML:
    return await html(t'<li><a href="{href}">{label}</a></li>')


# Cards & Containers


async def Card(
    children: SafeHTML,
    *,
    title: str | None = None,
    footer: SafeHTML | None = None,
) -> SafeHTML:
    """Article card component."""
    header = await html(t"<header>{title}</header>") if title else None
    foot = await html(t"<footer>{footer}</footer>") if footer else None
    return await html(t"<article>{header}{children}{foot}</article>")


async def Grid(children: SafeHTML, *, auto: bool = False) -> SafeHTML:
    """Grid container. auto=True uses auto-fit columns."""
    cls = "grid grid-auto" if auto else "grid"
    return await html(t'<div class="{cls}">{children}</div>')


async def HGroup(title: str, subtitle: str) -> SafeHTML:
    """Heading group with title and subtitle."""
    return await html(t"<hgroup><h1>{title}</h1><p>{subtitle}</p></hgroup>")


# Forms


async def Form(
    children: SafeHTML,
    *,
    action: str = "",
    method: Literal["get", "post"] = "post",
    enctype: str | None = None,
) -> SafeHTML:
    """Form wrapper."""
    return await html(
        t'<form action="{action}" method="{method}" {attr("enctype", enctype)}>{children}</form>'
    )


async def Field(
    name: str,
    *,
    label: str | None = None,
    type: str = "text",
    placeholder: str = "",
    value: str = "",
    required: bool = False,
    disabled: bool = False,
    readonly: bool = False,
    error: str | None = None,
    hint: str | None = None,
) -> SafeHTML:
    """Form field with label, input, and optional error/hint."""
    hint_id = f"{name}-hint" if hint or error else None
    hint_el = await html(t'<small id="{hint_id}">{error or hint}</small>') if hint_id else None
    input_el = await html(
        t'<input type="{type}" name="{name}" value="{value}" placeholder="{placeholder}" required="{required}" disabled="{disabled}" readonly="{readonly}" {attr("aria-invalid", "true" if error else None)} {attr("aria-describedby", hint_id)}>'
    )

    return await html(t"<label>{label}{input_el}{hint_el}</label>")


async def TextArea(
    name: str,
    *,
    label: str | None = None,
    placeholder: str = "",
    value: str = "",
    rows: int = 4,
    required: bool = False,
    disabled: bool = False,
) -> SafeHTML:
    """Textarea field."""
    textarea = await html(
        t'<textarea name="{name}" placeholder="{placeholder}" rows="{rows}" required="{required}" disabled="{disabled}">{value}</textarea>'
    )
    return await html(t"<label>{label}{textarea}</label>")


async def Select(
    name: str,
    options: list[tuple[str, str]],
    *,
    label: str | None = None,
    selected: str = "",
    required: bool = False,
    disabled: bool = False,
) -> SafeHTML:
    """Select dropdown."""
    opts = await html(t"{[SelectOption(v, txt, selected) for v, txt in options]}")
    select_el = await html(
        t'<select name="{name}" required="{required}" disabled="{disabled}">{opts}</select>'
    )
    return await html(t"<label>{label}{select_el}</label>")


async def SelectOption(value: str, text: str, selected: str) -> SafeHTML:
    sel = "selected" if value == selected else ""
    return await html(t'<option value="{value}" {sel}>{text}</option>')


async def Checkbox(
    name: str,
    *,
    label: str,
    checked: bool = False,
    disabled: bool = False,
) -> SafeHTML:
    """Checkbox input."""
    chk = "checked" if checked else ""
    return await html(
        t'<label><input type="checkbox" name="{name}" {chk} disabled="{disabled}">{label}</label>'
    )


async def Button(
    children: SafeHTML | str,
    *,
    type: Literal["submit", "button", "reset"] = "submit",
    variant: ButtonVariant = "primary",
    disabled: bool = False,
    busy: bool = False,
) -> SafeHTML:
    """Button component."""
    cls = "" if variant == "primary" else variant
    return await html(
        t'<button type="{type}" class="{cls}" disabled="{disabled}" {attr("aria-busy", "true" if busy else None)}>{children}</button>'
    )


async def ButtonLink(
    children: SafeHTML | str,
    href: str,
    *,
    variant: ButtonVariant = "primary",
) -> SafeHTML:
    """Link styled as button."""
    cls = "" if variant == "primary" else variant
    return await html(t'<a href="{href}" role="button" class="{cls}">{children}</a>')


# Feedback


async def Alert(
    children: SafeHTML | str,
    *,
    variant: AlertVariant = "info",
) -> SafeHTML:
    """Alert/notice component using ins/del/mark elements."""
    match variant:
        case "success":
            return await html(t"<ins>{children}</ins>")
        case "error":
            return await html(t"<del>{children}</del>")
        case "warning":
            return await html(t"<mark>{children}</mark>")
        case _:
            return await html(t"<p><small>{children}</small></p>")


async def Modal(
    id: str,
    children: SafeHTML,
    *,
    title: str | None = None,
    open: bool = False,
) -> SafeHTML:
    """Dialog modal."""
    open_attr = "open" if open else ""
    header = (
        await html(
            t'<header><button aria-label="Close" rel="prev" onclick="this.closest(\'dialog\').close()"></button><h3>{title}</h3></header>'
        )
        if title
        else None
    )
    return await html(
        t'<dialog id="{id}" {open_attr}><article>{header}{children}</article></dialog>'
    )


# Data Display


async def Table(
    headers: list[str],
    rows: list[list[Any]],
) -> SafeHTML:
    """Data table."""
    head = await html(t"{[TableHeader(h) for h in headers]}")
    body = await html(t"{[TableRow(row) for row in rows]}")
    return await html(t"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>")


async def TableHeader(text: str) -> SafeHTML:
    return await html(t"<th>{text}</th>")


async def TableRow(cells: list[Any]) -> SafeHTML:
    """Table row."""
    return await html(t"<tr>{[TableCell(c) for c in cells]}</tr>")


async def TableCell(content: Any) -> SafeHTML:
    return await html(t"<td>{content}</td>")


# Loading States


async def Loading(*, text: str = "Loading...") -> SafeHTML:
    """Loading indicator."""
    return await html(t'<article aria-busy="true">{text}</article>')


async def Skeleton(*, height: str = "1rem") -> SafeHTML:
    """Skeleton loading placeholder."""
    return await html(t'<div aria-busy="true" style="height: {height}"></div>')


# Utilities


@cached
async def Icon(name: str, *, size: int = 24, label: str | None = None) -> SafeHTML:
    """Lucide icon via CDN. Cached since these are static."""
    aria = attr("aria-label", label) if label else SafeHTML('aria-hidden="true"')
    return await html(t'<i data-lucide="{name}" style="width:{size}px;height:{size}px" {aria}></i>')


@cached
async def LucideScripts() -> SafeHTML:
    """Script tags for Lucide icons."""
    return await html(t"""
        <script src="https://unpkg.com/lucide@latest"></script>
        <script>lucide.createIcons();</script>
    """)


async def VisuallyHidden(children: SafeHTML | str) -> SafeHTML:
    """Screen reader only content."""
    return await html(t'<span class="visually-hidden">{children}</span>')
