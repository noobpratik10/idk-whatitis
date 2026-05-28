"""
ui/renderer.py
==============
Rich-powered terminal rendering: spinners, panels, confirmation dialogs,
progress steps, and advisory banners.

All user-facing output is funnelled through this module so the visual
language is consistent across the entire tool.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Generator, Optional

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Confirm
from rich.rule import Rule
from rich.spinner import Spinner
from rich.status import Status
from rich.style import Style
from rich.text import Text
from rich.theme import Theme

# ---------------------------------------------------------------------------
# Theme
# ---------------------------------------------------------------------------

SWIJ_THEME = Theme(
    {
        "swij.brand":    "bold cyan",
        "swij.success":  "bold green",
        "swij.warning":  "bold yellow",
        "swij.error":    "bold red",
        "swij.info":     "dim cyan",
        "swij.advisory": "yellow",
        "swij.muted":    "dim",
        "swij.code":     "bold white on grey15",
    }
)

console = Console(theme=SWIJ_THEME, highlight=True)
err_console = Console(stderr=True, theme=SWIJ_THEME)


# ---------------------------------------------------------------------------
# Brand header
# ---------------------------------------------------------------------------

def print_brand() -> None:
    """Print the swij brand header."""
    console.print(
        "\n[swij.brand]swij[/swij.brand] [swij.muted]— your AI git teammate[/swij.muted]",
        justify="left",
    )


# ---------------------------------------------------------------------------
# Spinner context manager
# ---------------------------------------------------------------------------

@contextmanager
def thinking(message: str = "Thinking…") -> Generator[Status, None, None]:
    """Show a spinner while the LLM is processing."""
    with console.status(
        f"[swij.info]{message}[/swij.info]",
        spinner="dots",
        spinner_style="cyan",
    ) as status:
        yield status


# ---------------------------------------------------------------------------
# Output panels
# ---------------------------------------------------------------------------

def print_response(text: str, action: Optional[str] = None) -> None:
    """
    Render the synthesized natural language response in a styled panel.
    Uses Markdown rendering so bold/code/bullets from the LLM look great.
    """
    subtitle = f"[swij.muted]{action}[/swij.muted]" if action else ""
    console.print(
        Panel(
            Markdown(text),
            border_style="cyan",
            subtitle=subtitle,
            subtitle_align="right",
            padding=(0, 1),
        )
    )


def print_success(message: str) -> None:
    """Print a brief inline success message (for very simple outputs)."""
    console.print(f"[swij.success]✓[/swij.success] {message}")


def print_error(message: str) -> None:
    """Print an error message in a red panel."""
    console.print(
        Panel(
            Markdown(message),
            border_style="red",
            title="[swij.error]Error[/swij.error]",
            padding=(0, 1),
        )
    )


def print_warning(message: str) -> None:
    """Print an advisory warning in a yellow panel."""
    console.print(
        Panel(
            Markdown(message),
            border_style="yellow",
            title="[swij.warning]⚠ Advisory[/swij.warning]",
            padding=(0, 1),
        )
    )


def print_interrupted(completed_steps: list[str]) -> None:
    """Print a clean interruption summary on Ctrl+C."""
    console.print()
    console.print(
        Panel(
            _build_interruption_text(completed_steps),
            border_style="yellow",
            title="[swij.warning]⚠ Interrupted[/swij.warning]",
            padding=(0, 1),
        )
    )


def _build_interruption_text(completed_steps: list[str]) -> Text:
    text = Text()
    text.append("Stopped by user.\n", style="bold yellow")
    if completed_steps:
        text.append("\nCompleted before interruption:\n", style="dim")
        for step in completed_steps:
            text.append(f"  ✓ {step}\n", style="green")
    else:
        text.append("\nNo changes were made.", style="dim")
    return text


# ---------------------------------------------------------------------------
# Confirmation prompts
# ---------------------------------------------------------------------------

def confirm_destructive(action: str, details: str) -> bool:
    """
    Show a mandatory confirmation dialog for destructive (red) operations.
    Returns True if the user confirmed, False otherwise.
    """
    console.print()
    console.print(
        Panel(
            Markdown(
                f"**⚠ This action is destructive and cannot be undone.**\n\n"
                f"**Action:** `{action}`\n\n"
                f"{details}"
            ),
            border_style="red",
            title="[swij.error]Confirmation Required[/swij.error]",
            padding=(0, 1),
        )
    )
    return Confirm.ask(
        "[bold red]Are you sure you want to proceed?[/bold red]",
        default=False,
        console=console,
    )


def confirm_advisory(message: str) -> bool:
    """
    Ask the user whether to proceed after an advisory warning.
    Returns True if the user wants to continue.
    """
    console.print()
    print_warning(message)
    return Confirm.ask(
        "[bold yellow]Do you want to proceed?[/bold yellow]",
        default=True,
        console=console,
    )


def confirm_stale_branch(base_branch: str, commits_behind: str, remote: str) -> bool:
    """
    Ask the user if they want to pull before branching from a stale base.
    Default is Y (yes, pull) per the design spec.
    """
    console.print()
    console.print(
        Panel(
            Markdown(
                f"Your local `{base_branch}` is **{commits_behind} commit(s) behind** "
                f"`{remote}/{base_branch}`.\n\n"
                "**Recommended:** Pull latest `{base_branch}` before branching "
                "to avoid a stale base.".replace("{base_branch}", base_branch)
            ),
            border_style="yellow",
            title="[swij.warning]⚠ Stale Base Branch[/swij.warning]",
            padding=(0, 1),
        )
    )
    return Confirm.ask(
        f"[bold]Pull `{base_branch}` first, then branch?[/bold]",
        default=True,
        console=console,
    )


# ---------------------------------------------------------------------------
# Progress steps (for multi-step workflows)
# ---------------------------------------------------------------------------

def print_step(step_number: int, description: str) -> None:
    """Print a numbered step indicator for multi-step workflows."""
    console.print(
        f"  [swij.muted]Step {step_number}:[/swij.muted] "
        f"[bold]{description}[/bold]"
    )


def print_step_done(step_number: int, description: str) -> None:
    """Mark a step as completed."""
    console.print(
        f"  [swij.success]✓[/swij.success] [swij.muted]Step {step_number}:[/swij.muted] "
        f"{description}"
    )


def print_step_failed(step_number: int, description: str) -> None:
    """Mark a step as failed."""
    console.print(
        f"  [swij.error]✗[/swij.error] [swij.muted]Step {step_number}:[/swij.muted] "
        f"{description}"
    )


def print_divider() -> None:
    """Print a subtle horizontal divider."""
    console.print(Rule(style="dim"))


# ---------------------------------------------------------------------------
# Clarification prompt
# ---------------------------------------------------------------------------

def print_clarification_request(message: str) -> None:
    """Show a clarification request when LLM confidence is low."""
    console.print()
    console.print(
        Panel(
            Markdown(
                f"**I'm not sure I understood that correctly.**\n\n{message}\n\n"
                "*Could you rephrase or be more specific?*"
            ),
            border_style="cyan",
            title="[swij.info]Clarification Needed[/swij.info]",
            padding=(0, 1),
        )
    )
