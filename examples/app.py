"""
Example Julython-style app using htmpl with Elements.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from fastapi import Depends, FastAPI, Request
from pydantic import BaseModel, Field, EmailStr

from htmpl import html, SafeHTML, Fragment, fragment
from htmpl.assets import component
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
)
from htmpl.forms import BaseForm
from htmpl.fastapi import (
    HTMLRouter,
    HTMLForm,
    FormValidationError,
    form_validation_error_handler,
    is_htmx,
    mount_bundles,
    page,
    CurrentPage,
)
from htmpl.htmx import HX, HtmxScripts, SearchInput, LazyLoad
from htmpl.components import LucideScripts


router = HTMLRouter()

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


# Layout Components


@component(css={"/static/css/app.css"})
async def AppPage(title: str, children, user: User | None = None, scripts=None) -> SafeHTML:
    return div(
        await AppMain(user, children),
        await html(t"{HtmxScripts()}{LucideScripts()}{scripts}"),
    )


async def AppMain(user: User | None, children):
    return fragment(t"{AppNav(user)}{main(children, class_='container')}")


async def AppNav(user: User | None):
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
        ul(
            [li(a(lbl, href=href)) for lbl, href in items],
            end,
        ),
        class_="container",
    )


def HGroup(title: str, subtitle: str):
    return div(
        h1(title),
        p(subtitle),
        role="group",
    )


# UI Components


def StatCard(lbl: str, value: int | str):
    display = f"{value:,}" if isinstance(value, int) else value
    return article(
        div(
            h2(display),
            p(lbl, class_="text-muted"),
            class_="text-center",
        ),
    )


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
        tbody(
            [LeaderboardRow(u, i + 1) for i, u in enumerate(users)],
            id="leaderboard-body",
        ),
    )


def CommitCard(message: str, repo: str, points: int, timestamp: str):
    return article(
        p(strong(repo)),
        p(message),
        small(f"{timestamp} · +{points} pts", class_="text-muted"),
    )


def RepoRow(name: str, active: bool, commits: int):
    hx = HX(post=f"/api/repos/{name}/toggle", swap="outerHTML")
    status = "✓ Active" if active else "Inactive"
    return tr(
        td(a(name, href=f"https://github.com/{name}")),
        td(button(status, class_="outline", **{"_": str(hx)})),
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


# Cached components


@cached_ttl(seconds=60)
async def GlobalStatsBar() -> SafeHTML:
    """Cached for 60 seconds since stats don't change often."""
    stats = await get_stats()
    return SafeHTML(
        await Grid(
            StatCard("Commits", stats.total_commits),
            StatCard("Participants", stats.participants),
            StatCard("Days Left", stats.days_remaining),
            auto=True,
        ).__html__()
    )


# Routes


@router.get("/", dependencies=[page("home", title="Julython", uses={AppPage})])
async def home() -> SafeHTML:
    user = await get_current_user()
    leaderboard = await get_leaderboard()

    return await AppPage(
        "Home",
        user=user,
        children=fragment(
            section(
                HGroup("Julython", "A month-long celebration of coding in July"),
                GlobalStatsBar(),
            ),
            section(
                h2("Leaderboard"),
                LeaderboardTable(leaderboard[:10]),
                ButtonLink("View Full Leaderboard", "/board", variant="secondary"),
                class_="mt-1",
            ),
        ),
    )


@router.get(
    "/board",
    dependencies=[page("board", title="Leaderboard", uses={AppPage})],
    response_model=None,
)
async def leaderboard(request: Request, q: str = "") -> SafeHTML:
    users = await get_leaderboard(q)

    # HTMX partial - no layout needed
    if is_htmx(request):
        rows = fragment(*[LeaderboardRow(u, i + 1) for i, u in enumerate(users)])
        return SafeHTML(await rows.__html__())

    user = await get_current_user()
    return await AppPage(
        "Leaderboard",
        user=user,
        children=fragment(
            h1("Leaderboard"),
            SearchInput(
                "q", src="/board", target="#leaderboard-body", placeholder="Search users..."
            ),
            LeaderboardTable(users),
        ),
    )


@router.get(
    "/dashboard",
    dependencies=[page("dashboard", title="Dashboard", uses={AppPage})],
)
async def dashboard(ctx: CurrentPage) -> SafeHTML:
    user = await get_current_user()
    if not user:
        return await html(t'<meta http-equiv="refresh" content="0;url=/login">')

    repos = await get_user_repos(user.id)

    # Example: using ctx.title from the page context
    return await AppPage(
        ctx.title,
        user=user,
        children=fragment(
            h1(f"Welcome back, {user.username}"),
            Grid(
                StatCard("Your Points", user.points),
                StatCard("Your Commits", user.commits),
                StatCard("Rank", "#2"),
                auto=True,
            ),
            section(
                h2("Recent Commits"),
                LazyLoad(
                    "/api/commits/recent", placeholder=article("Loading...", aria_busy="true")
                ),
                class_="mt-1",
            ),
            section(
                h2("Your Repos"),
                RepoTable(repos),
                class_="mt-1",
            ),
        ),
    )


# API routes - no page() dependency, just returns fragments
@router.get("/api/commits/recent", response_model=None)
async def recent_commits() -> Fragment:
    user = await get_current_user()
    commits = await get_recent_commits(user.id) if user else []
    return fragment(*[CommitCard(msg, repo, pts, ts) for msg, repo, pts, ts in commits])


# Forms with page dependency


class SettingsForm(BaseForm):
    username: str = Field(description="fancy name for a user")
    email: EmailStr
    email_digest: bool = Field(json_schema_extra={"role": "switch"})
    notify_mentions: bool


async def settings_form(renderer: type[SettingsForm], values, errors):
    user = await get_current_user()
    return await AppPage(
        "Edit Settings",
        user=user,
        children=renderer.render(values=values, errors=errors, submit_text="Edit Account"),
    )


@router.get(
    "/settings",
    dependencies=[page("settings", title="Settings", uses={AppPage})],
)
async def settings_get():
    user = await get_current_user()
    values = user.model_dump() if user else {}
    return await settings_form(SettingsForm, values, {})


@router.post(
    "/settings",
    dependencies=[page("settings", title="Settings", uses={AppPage})],
)
async def settings_post(data: SettingsForm = Depends(HTMLForm(SettingsForm, settings_form))):
    user = await get_current_user()
    return div("congrats")


mount_bundles(router)

app = FastAPI(debug=True)
app.include_router(router)
app.add_exception_handler(FormValidationError, form_validation_error_handler)  # type: ignore

logging.basicConfig(level=logging.INFO)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
