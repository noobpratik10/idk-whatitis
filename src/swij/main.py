"""
main.py
=======
CLI entrypoint for swij.

Usage:
  swij "create a branch from develop called fix-login"
  swij "what did I change?"
  swij --version
  swij --help
"""

from __future__ import annotations

from typing import Optional

import typer
from rich.console import Console

from swij import __version__

app = typer.Typer(
    name="swij",
    help="Your AI-native Git & Bitbucket terminal teammate.",
    add_completion=False,
    no_args_is_help=False,  # we handle the no-args case ourselves
)

console = Console()


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"[bold cyan]swij[/bold cyan] v{__version__}")
        raise typer.Exit()


@app.command()
def main(
    request: Optional[str] = typer.Argument(
        None,
        help="Your natural language git request. Example: 'create a branch from main'",
        metavar="REQUEST",
    ),
    version: Optional[bool] = typer.Option(
        None,
        "--version", "-v",
        help="Show swij version and exit.",
        callback=_version_callback,
        is_eager=True,
    ),
) -> None:
    """
    swij — your AI-native Git & Bitbucket terminal teammate.

    Just describe what you want to do in plain English:

    \b
      swij "create a branch from develop called fix-payment-retry"
      swij "what did I change?"
      swij "commit only src/auth.py with message 'fix token validation'"
      swij "push my changes"
      swij "show me the last 5 commits"
      swij "stash my changes"
    """
    # ── Load config (validates GEMINI_API_KEY, exits cleanly if missing) ──
    from swij.config.settings import load_settings
    load_settings()

    # ── Startup git check ──────────────────────────────────────────────────
    _check_git_available()

    # ── No request provided → show interactive help ────────────────────────
    if not request:
        _show_interactive_help()
        return

    # ── Run the agent ──────────────────────────────────────────────────────
    from swij.core.agent import Agent
    from swij.ui.renderer import print_brand

    print_brand()

    agent = Agent()
    agent.run(request.strip())


def _check_git_available() -> None:
    """Check git is installed. Exit with a helpful message if not."""
    import subprocess
    try:
        result = subprocess.run(
            ["git", "--version"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            raise FileNotFoundError
    except (FileNotFoundError, subprocess.TimeoutExpired):
        console.print(
            "\n[bold red]✗ git is not installed or not in your PATH.[/bold red]\n\n"
            "Install git from [link=https://git-scm.com/]https://git-scm.com/[/link] "
            "and try again.\n"
        )
        raise typer.Exit(1)


def _show_interactive_help() -> None:
    """Show a friendly help panel when no request is provided."""
    from rich.markdown import Markdown
    from rich.panel import Panel

    help_text = (
        "# swij — your AI git teammate\n\n"
        "Just describe what you want in plain English:\n\n"
        "```\n"
        'swij "create a branch from develop called fix-login"\n'
        'swij "show me what changed"\n'
        'swij "commit only src/auth.py with message \'fix token\'"\n'
        'swij "push my changes"\n'
        'swij "show me the last 10 commits"\n'
        'swij "stash my changes"\n'
        'swij "switch to main"\n'
        "```\n\n"
        "Run `swij --help` for full usage information."
    )

    console.print(
        Panel(
            Markdown(help_text),
            border_style="cyan",
            title="[bold cyan]swij[/bold cyan]",
            padding=(0, 1),
        )
    )


if __name__ == "__main__":
    app()
