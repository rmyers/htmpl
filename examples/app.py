"""
Example Julython-style app using htmpl with tdom.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Annotated, Any, Callable

from fastapi import APIRouter, Depends, FastAPI, Request
from pydantic import BaseModel, Field, EmailStr

from htmpl import html, SafeHTML, render_html
from htmpl.assets import Bundles, component, registry

from htmpl.forms import BaseForm
from htmpl.fastapi import ParsedForm, use_component, use_bundles, add_assets_routes, is_htmx, use_form

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


# Pure functions - no async needed, just return template strings


def HGroup(title: str, subtitle: str):
    return t'<div role="group"><h1>{title}</h1><p>{subtitle}</p></div>'


def StatCard(lbl: str, value: int | str):
    display = f"{value:,}" if isinstance(value, int) else value
    return t'''<article>
        <div class="text-center">
            <h2>{display}</h2>
            <p class="text-muted">{lbl}</p>
        </div>
    </article>'''


def Grid(*children, auto: bool = False):
    cls = "grid grid-auto" if auto else "grid"
    return t'<div class={cls}>{children}</div>'


def LeaderboardRow(user: User, rank: int):
    return t'''<tr>
        <td>{rank}</td>
        <td><a href="/u/{user.username}">{user.username}</a></td>
        <td>{user.commits}</td>
        <td><strong>{user.points:,}</strong></td>
    </tr>'''


@component('leader-board', css={"/static/css/foo.css"})
async def LeaderBoardTable():
    def _lb(users: list[User]):
        rows = [LeaderboardRow(u, i + 1) for i, u in enumerate(users)]
        return t'''<table>
            <thead>
                <tr>
                    <th>#</th>
                    <th>User</th>
                    <th>Commits</th>
                    <th>Points</th>
                </tr>
            </thead>
            <tbody id="leaderboard-body">{rows}</tbody>
        </table>'''

    return _lb


def CommitCard(message: str, repo: str, points: int, timestamp: str):
    return t'''<article>
        <p><strong>{repo}</strong></p>
        <p>{message}</p>
        <small class="text-muted">{timestamp} · +{points} pts</small>
    </article>'''


def RepoRow(name: str, active: bool, commits: int):
    status = "✓ Active" if active else "Inactive"
    return t'''<tr>
        <td><a href="https://github.com/{name}">{name}</a></td>
        <td>
            <button class="outline" hx-post="/api/repos/{name}/toggle" hx-swap="outerHTML">
                {status}
            </button>
        </td>
        <td>{commits}</td>
    </tr>'''


def RepoTable(repos: list[tuple[str, bool, int]]):
    rows = [RepoRow(name, active, commits) for name, active, commits in repos]
    return t'''<table>
        <thead>
            <tr>
                <th>Repository</th>
                <th>Tracking</th>
                <th>Commits</th>
            </tr>
        </thead>
        <tbody>{rows}</tbody>
    </table>'''


def ButtonLink(text: str, href: str, *, variant: str = "primary"):
    attrs = {
        "class": variant,
        "role": "button",
        "href": href,
    }
    return t'<a {attrs}>{text}</a>'


@component('search-input', css={"/static/css/foo.css"})
async def SearchInput() -> Callable:
    def search_inpt(name: str, *, src: str, target: str, placeholder: str = "Search..."):
        return t'''<input
            type="search"
            name={name}
            placeholder={placeholder}
            hx-get={src}
            hx-target={target}
            hx-trigger="input changed delay:300ms, search"
            hx-swap="innerHTML"
        />'''

    return search_inpt


def LazyLoad(src: str, *, placeholder=None):
    inner = placeholder or t'<article aria-busy="true">Loading...</article>'
    return t'<div hx-get={src} hx-trigger="load" hx-swap="outerHTML">{inner}</div>'


# Components


@component('app-nav')
async def AppNav():
    user = await get_current_user()
    items = [("Leaderboard", "/board"), ("Projects", "/projects"), ("About", "/about")]

    nav_items = [t'<li><a href={href}>{lbl}</a></li>' for lbl, href in items]

    end = t'''<li>
            <details class="dropdown">
                <summary>{user.username}</summary>
                <ul dir="rtl">
                    <li><a href="/dashboard">Dashboard</a></li>
                    <li><a href="/settings">Settings</a></li>
                    <li><a href="/logout">Logout</a></li>
                </ul>
            </details>
        </li>''' if user else t'<li><a href="/login" role="button">Sign in with GitHub</a></li>'

    return t'''<nav class="container">
        <ul>
            <li><a href="/"><strong>Julython</strong></a></li>
        </ul>
        <ul>
            {nav_items}
            {end}
        </ul>
    </nav>'''


# Layout - single function, no nesting


@component('app-page', css={"/static/css/app.css"})
async def AppPage(
    bundles: Annotated[Bundles, Depends(use_bundles)],
    navbar: Annotated[SafeHTML, use_component(AppNav)],
):

    def _comp(children, title: str = "Julython"):
        return html(t'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{title}</title>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@picocss/pico@2/css/pico.min.css">
    {bundles.head}
</head>
<body>
    {navbar}
    <main class="container">{children}</main>
    <script src="https://unpkg.com/htmx.org@2.0.4"></script>
</body>
</html>''')

    return _comp


# Routes


@router.get("/")
async def home(
    page: Annotated[Any, use_component(AppPage)],
    lb: Annotated[Callable, use_component(LeaderBoardTable)],
):
    stats = await get_stats()
    leaderboard = await get_leaderboard()

    stat_cards = Grid(
        StatCard("Commits", stats.total_commits),
        StatCard("Participants", stats.participants),
        StatCard("Days Left", stats.days_remaining),
        auto=True,
    )

    return await render_html(
        t'''
        <{page} title="Julython - Code More in July">
        <section>
            {HGroup("Julython", "A month-long celebration of coding in July")}
            {stat_cards}
        </section>
        <section class="mt-1">
            <h2>Leaderboard</h2>
            {lb(leaderboard[:10])}
            {ButtonLink("View Full Leaderboard", "/board", variant="secondary")}
        </section>
        </{page}>
        '''
    )


@router.get("/board")
async def leaderboard(
    request: Request,
    page: Annotated[Any, use_component(AppPage)],
    search_input: Annotated[Callable, use_component(SearchInput)],
    lb: Annotated[Callable, use_component(LeaderBoardTable)],
    q: str = "",
):
    users = await get_leaderboard(q)

    # HTMX partial - just the rows
    if is_htmx(request):
        rows = [LeaderboardRow(u, i + 1) for i, u in enumerate(users)]
        return await render_html(t"{rows}")

    return await render_html(
        t'''<{page} title="Leaderboard">
        <h1>Leaderboard</h1>
        {search_input("q", src="/board", target="#leaderboard-body", placeholder="Search users...")}
        {lb(users)}
        </{page}>
        '''
    )


@router.get("/dashboard")
async def dashboard(page: Annotated[Any, use_component(AppPage)]):
    user = await get_current_user()
    if not user:
        return page.redirect("/login")

    repos = await get_user_repos(user.id)

    stat_cards = Grid(
        StatCard("Your Points", user.points),
        StatCard("Your Commits", user.commits),
        StatCard("Rank", "#2"),
        auto=True,
    )

    return await render_html(
        t'''
        <{page} title="Dashboard">
        <h1>Welcome back, {user.username}</h1>
        {stat_cards}
        <section class="mt-1">
            <h2>Recent Commits</h2>
            {LazyLoad("/api/commits/recent")}
        </section>
        <section class="mt-1">
            <h2>Your Repos</h2>
            {RepoTable(repos)}
        </section>
        </{page}>
        '''
    )


# API routes - fragments only, no layout


@router.get("/api/commits/recent")
async def recent_commits():
    user = await get_current_user()
    commits = await get_recent_commits(user.id) if user else []
    cards = [CommitCard(msg, repo, pts, ts) for msg, repo, pts, ts in commits]
    return await render_html(t"{cards}")


# Forms


class SettingsForm(BaseForm):
    username: str = Field(description="Your display name")
    email: EmailStr
    frank: str
    email_digest: bool = Field(
        default=False, json_schema_extra={"form_widget": "checkbox", "role": "switch"}
    )
    notify_mentions: bool


def settings_template(form_class: type[SettingsForm], values: dict, errors: dict):
    form_html = form_class.render(action="/settings", values=values, errors=errors, submit_text="Save")
    return t'''
    <h1>Settings</h1>
    {form_html}
    '''


@router.get("/settings")
async def settings_get(page: Annotated[Any, use_component(AppPage)]):
    user = await get_current_user()
    values = {"username": user.username, "email": "bob@example.com"} if user else {}
    form = settings_template(SettingsForm, values, {})
    return await render_html(t'<{page} title="Settings">{form}</{page}>')


@router.post("/settings")
async def settings_post(
    page: Annotated[Any, use_component(AppPage)],
    parsed: Annotated[ParsedForm[SettingsForm], use_form(SettingsForm)]
):
    if parsed.errors:
        rendered = SettingsForm.render(values=parsed.values, errors=parsed.errors, submit_text="Update")
        return await render_html(t"<{page}>{rendered}</{page}>")

    assert parsed.data is not None
    return await render_html(t"<{page}><h1>Welcome, {parsed.data.email}!</h1></{page}>")


# App setup

from contextlib import asynccontextmanager


@asynccontextmanager
async def lifespan(app: FastAPI):
    await registry.initialize(watch=True)
    registry.save_manifest()
    yield
    await registry.teardown()


app = FastAPI(debug=True, lifespan=lifespan)
app.include_router(router)
add_assets_routes(app)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
