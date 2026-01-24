"""
htmpl CLI - thin wrapper around copier.

Usage:
    htmpl new [DEST] [--version TAG]
    htmpl update [--version TAG]
    htmpl versions
"""

from __future__ import annotations

import subprocess

import click
import copier

TEMPLATE_REPO = "gh:rmyers/htmpl-template.git"


@click.group()
@click.version_option()
def cli():
    """htmpl - create and manage htmpl projects."""
    pass


@cli.command()
@click.argument("dest")
@click.option("--version", "-v", help="Template version (git tag)")
def init(dest: str, version: str | None):
    """Create a new htmpl project."""

    copier.run_copy(TEMPLATE_REPO, dest, vcs_ref=version)
    click.echo(f"\n✓ Created htmpl project in {dest}")
    click.echo("  Run 'uvicorn app:app --reload' to start")
    click.echo("  Admin UI available at /_admin")


@cli.command()
@click.option("--version", "-v", help="Update to specific version (default: latest)")
def update(version: str | None):
    """Update project from upstream template."""
    copier.run_update(".", vcs_ref=version)
    click.echo("\n✓ Project updated")


@cli.command()
def versions():
    """List available template versions."""
    result = subprocess.run(
        ["git", "ls-remote", "--tags", TEMPLATE_REPO],
        capture_output=True,
        text=True,
    )
    tags = [
        line.split("refs/tags/")[-1]
        for line in result.stdout.strip().split("\n")
        if "refs/tags/" in line and "^{}" not in line
    ]
    for tag in sorted(tags, reverse=True):
        click.echo(tag)


def main():
    cli()


if __name__ == "__main__":
    main()
