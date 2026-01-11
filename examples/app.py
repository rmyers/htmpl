"""
Example Julython-style app using htmpl with Elements.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from pprint import pprint
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, EmailStr

from htmpl import html, SafeHTML, raw
from htmpl.assets import Bundles, component, layout, registry, save_manifest
from htmpl.core import cached_ttl
from htmpl.elements import (
    section,
    div,
    article,
    nav,
    ul,
    li,
    main,
    h1,
    h2,
    h3,
    p,
    a,
    strong,
    small,
    table,
    thead,
    tbody,
    tr,
    th,
    td,
    form,
    label,
    input_,
    button,
    details,
    summary,
    fragment,
    script,
)
from htmpl.forms import BaseForm
from htmpl.fastapi import (
    HTMLForm,
    FormValidationError,
    form_validation_error_handler,
    page,
    use_component,
    PageRenderer,
)
from htmpl.htmx import is_htmx


router = APIRouter()


# Models


class User(BaseModel):
    id: int
    username: str
    avatar_url: str
    points: int = 0
    commits: int = 0
    is_admin: bool = False


@dataclass
class Stats:
    total_commits: int
    participants: int
    days_remaining: int


# Fake async data layer


async def get_current_user() -> User | None:
    return User(id=1, username="bob", avatar_url="/avatar/1", points=420, commits=42)


async def get_leaderboard(q: str = "") -> list[User]:
    users = [
        User(id=2, username="alice", avatar_url="/a/2", points=1200, commits=98),
        User(id=1, username="bob", avatar_url="/a/1", points=420, commits=42),
        User(id=3, username="charlie", avatar_url="/a/3", points=380, commits=35),
    ]
    if q:
        users = [u for u in users if q.lower() in u.username.lower()]
    return users


async def get_stats() -> Stats:
    return Stats(total_commits=12_847, participants=342, days_remaining=18)


async def get_recent_commits(user_id: int):
    return [
        ("Fix OAuth callback handling", "julython/julython", 15, "2 hours ago"),
        ("Add leaderboard caching", "julython/julython", 12, "5 hours ago"),
        ("Update dependencies", "bob/qtip", 5, "yesterday"),
    ]


async def get_user_repos(user_id: int):
    return [
        ("julython/julython", True, 28),
        ("bob/qtip", True, 14),
        ("bob/dotfiles", False, 0),
    ]


# Pure functions - no async needed, just return Elements


def HGroup(title: str, subtitle: str):
    return div(h1(title), p(subtitle), role="group")


def StatCard(lbl: str, value: int | str):
    display = f"{value:,}" if isinstance(value, int) else value
    return article(div(h2(display), p(lbl, class_="text-muted"), class_="text-center"))


def Grid(*children, auto: bool = False):
    cls = "grid grid-auto" if auto else "grid"
    return div(*children, class_=cls)


def LeaderboardRow(user: User, rank: int):
    return tr(
        td(str(rank)),
        td(a(user.username, href=f"/u/{user.username}")),
        td(str(user.commits)),
        td(strong(f"{user.points:,}")),
    )


def LeaderboardTable(users: list[User]):
    return table(
        thead(tr(th("#"), th("User"), th("Commits"), th("Points"))),
        tbody([LeaderboardRow(u, i + 1) for i, u in enumerate(users)], id="leaderboard-body"),
        id="leaderboard"
    )


def CommitCard(message: str, repo: str, points: int, timestamp: str):
    return article(
        p(strong(repo)),
        p(message),
        small(f"{timestamp} · +{points} pts", class_="text-muted"),
    )


def RepoRow(name: str, active: bool, commits: int):
    status = "✓ Active" if active else "Inactive"
    return tr(
        td(a(name, href=f"https://github.com/{name}")),
        td(button(status, class_="outline", hx_post=f"/api/repos/{name}/toggle", hx_swap="outerHTML")),
        td(str(commits)),
    )


def RepoTable(repos: list[tuple[str, bool, int]]):
    return table(
        thead(tr(th("Repository"), th("Tracking"), th("Commits"))),
        tbody([RepoRow(name, active, commits) for name, active, commits in repos]),
    )


def ButtonLink(text: str, href: str, *, variant: str = "primary"):
    cls = "" if variant == "primary" else variant
    return a(text, href=href, role="button", class_=cls)


def SearchInput(name: str, *, src: str, target: str, placeholder: str = "Search..."):
    """Sync search input - just returns an Element."""
    return input_(
        type="search",
        name=name,
        placeholder=placeholder,
        hx_get=src,
        hx_target=target,
        hx_trigger="input changed delay:300ms, search",
        hx_swap="innerHTML",
    )


@component(css={"/static/css/foo.css"})
async def LazyLoad(src: str, *, placeholder=None):
    """Sync lazy load container."""
    inner = placeholder or article("Loading...", aria_busy="true")
    return div(inner, hx_get=src, hx_trigger="load", hx_swap="outerHTML")


# Layout Components


@component()
async def AppNav():
    user = await get_current_user()
    items = [("Leaderboard", "/board"), ("Projects", "/projects"), ("About", "/about")]

    if user:
        end = li(
            details(
                summary(user.username),
                ul(
                    li(a("Dashboard", href="/dashboard")),
                    li(a("Settings", href="/settings")),
                    li(a("Logout", href="/logout")),
                    dir="rtl",
                ),
                class_="dropdown",
            ),
        )
    else:
        end = li(a("Sign in with GitHub", href="/login", role="button"))

    return nav(
        ul(li(a(strong("Julython"), href="/"))),
        ul([li(a(lbl, href=href)) for lbl, href in items], end),
        class_="container",
    )


@layout(css={"/static/css/app.css"})
async def AppPage(navbar: Annotated[SafeHTML, use_component(AppNav)]):
    async def render(content: SafeHTML, title: str, bundles: Bundles) -> SafeHTML:
        return await html(t'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{title}</title>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@picocss/pico@2/css/pico.min.css">
    {raw(bundles.head())}
</head>
<body>
    {navbar}
    <main class="container">{content}</main>
    <script src="https://unpkg.com/htmx.org@2.0.4"></script>
</body>
</html>''')
    return render


# Routes


@router.get("/")
async def home(page_render: Annotated[PageRenderer, page("home", title="Julython", layout=AppPage)]):
    stats = await get_stats()
    leaderboard = await get_leaderboard()

    return await page_render.render(fragment(
        section(
            HGroup("Julython", "A month-long celebration of coding in July"),
            Grid(
                StatCard("Commits", stats.total_commits),
                StatCard("Participants", stats.participants),
                StatCard("Days Left", stats.days_remaining),
                auto=True,
            ),
        ),
        section(
            h2("Leaderboard"),
            LeaderboardTable(leaderboard[:10]),
            ButtonLink("View Full Leaderboard", "/board", variant="secondary"),
            class_="mt-1",
        ),
    ))


@router.get("/board")
async def leaderboard(
    p: Annotated[PageRenderer, page("board", title="Leaderboard", layout=AppPage, uses={LazyLoad})],
    lazy: Annotated[SafeHTML, use_component(LazyLoad, src="/lskj")],
    request: Request, q: str = ""):
    users = await get_leaderboard(q)

    # HTMX partial - just the rows
    if is_htmx(request):
        logger.info('Just swap the table')
        return await p.render(fragment(LeaderboardTable(users)))

    return await p.render(fragment(
        h1("Leaderboard"),
        SearchInput("q", src="/board", target="#leaderboard", placeholder="Search users..."),
        LeaderboardTable(users),
    ))


@router.get("/dashboard", dependencies=[page("dashboard", title="Dashboard", layout=AppPage)])
async def dashboard(p: Annotated[PageRenderer, page("dashboard", title="Dashboard", layout=AppPage)]):
    user = await get_current_user()
    if not user:
        return await p.render(html(t'<meta http-equiv="refresh" content="0;url=/login">'))

    repos = await get_user_repos(user.id)

    return await p.render(fragment(
        h1(f"Welcome back, {user.username}"),
        Grid(
            StatCard("Your Points", user.points),
            StatCard("Your Commits", user.commits),
            StatCard("Rank", "#2"),
            auto=True,
        ),
        section(
            h2("Recent Commits"),
            LazyLoad("/api/commits/recent"),
            class_="mt-1",
        ),
        section(
            h2("Your Repos"),
            RepoTable(repos),
            class_="mt-1",
        ),
    ))


# API routes - fragments only, no layout
@router.get("/api/commits/recent")
async def recent_commits(p: Annotated[PageRenderer, page("recent_commits")]):
    await asyncio.sleep(3)
    user = await get_current_user()
    commits = await get_recent_commits(user.id) if user else []
    return p.render(fragment(*[CommitCard(msg, repo, pts, ts) for msg, repo, pts, ts in commits]))


# Forms


class SettingsForm(BaseForm):
    username: str = Field(description="Your display name")
    email: EmailStr
    email_digest: bool = Field(default=False, json_schema_extra={"form_widget": "checkbox", "role": "switch"})
    notify_mentions: bool = Field(default=True, json_schema_extra={"form_widget": "checkbox"})
    color: str | None = None


async def settings_page(renderer: type[SettingsForm], values: dict, errors: dict):
    return fragment(
        h1("Settings"),
        renderer.render(action="/settings", values=values, errors=errors, submit_text="Save"),
    )


@router.get("/settings")
async def settings_get(p: Annotated[PageRenderer, page("settings", title="Settings", layout=AppPage)]):
    user = await get_current_user()
    values = {"username": user.username} if user else {}
    return await p.render(settings_page(SettingsForm, values, {}))


@router.post("/settings")
async def settings_post(
    data: Annotated[SettingsForm, Depends(HTMLForm(SettingsForm, settings_page))],
    pr: Annotated[PageRenderer, page("settings_post", title="Settings", layout=AppPage)]
):
    return await pr.render(fragment(
        h1("Settings"),
        article(p("Settings saved successfully!")),
    ))


# App setup

app = FastAPI(debug=True)
app.include_router(router)
app.add_exception_handler(FormValidationError, form_validation_error_handler)  # type: ignore
app.mount("/static", StaticFiles(directory=Path("static"), check_dir=False), name="static")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger()

logger.info(f"{pprint(registry.pages)}")
save_manifest()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
