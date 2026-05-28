"""
config/settings.py
==================
Loads configuration from the .env file and validates required values at startup.
Any missing or invalid config causes a clear, immediate error message before the
agent loop starts — no silent failures deep in the call stack.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console

console = Console(stderr=True)

# ---------------------------------------------------------------------------
# .env loading
# ---------------------------------------------------------------------------

def _find_env_file() -> Path | None:
    """Walk up from CWD looking for a .env file, then fall back to home dir."""
    current = Path.cwd()
    for directory in [current, *current.parents]:
        candidate = directory / ".env"
        if candidate.exists():
            return candidate

    # Also check the home directory
    home_env = Path.home() / ".swij" / ".env"
    if home_env.exists():
        return home_env

    return None


def load_settings() -> None:
    """
    Load .env and validate required environment variables.
    Call this ONCE at startup in main.py before anything else runs.
    Exits with a helpful message if required settings are missing.
    """
    env_file = _find_env_file()
    if env_file:
        load_dotenv(dotenv_path=env_file, override=False)
    else:
        # Try loading from default .env in current directory anyway
        load_dotenv(override=False)

    _validate()


def _validate() -> None:
    """Check that all required env vars are present."""
    api_key = os.getenv("GEMINI_API_KEY")

    if not api_key:
        console.print(
            "\n[bold red]✗ Missing GEMINI_API_KEY[/bold red]\n"
            "\nswij needs a Google Gemini API key to work.\n"
            "\n[bold]How to fix:[/bold]\n"
            "  1. Get a free key at [link=https://aistudio.google.com/]https://aistudio.google.com/[/link]\n"
            "  2. Create a [cyan].env[/cyan] file in your project (or home) directory:\n"
            "     [dim]cp .env.example .env[/dim]\n"
            "  3. Edit [cyan].env[/cyan] and set:\n"
            "     [cyan]GEMINI_API_KEY=your_key_here[/cyan]\n"
        )
        sys.exit(1)


# ---------------------------------------------------------------------------
# Typed accessors — always call load_settings() first
# ---------------------------------------------------------------------------

def get_gemini_api_key() -> str:
    key = os.getenv("GEMINI_API_KEY", "")
    if not key:
        raise RuntimeError("GEMINI_API_KEY not set. Call load_settings() first.")
    return key


def get_gemini_model() -> str:
    """Model used for intent parsing (fast, cheap, structured output)."""
    return os.getenv("SWIJ_MODEL", "gemini-2.0-flash")


def get_subprocess_timeout() -> int:
    """Timeout in seconds for all subprocess git calls."""
    return int(os.getenv("SWIJ_TIMEOUT", "30"))


def get_confidence_threshold() -> float:
    """Intent confidence below this threshold triggers a clarification ask."""
    return float(os.getenv("SWIJ_CONFIDENCE_THRESHOLD", "0.75"))
