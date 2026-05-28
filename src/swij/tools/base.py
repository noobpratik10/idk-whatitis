"""
tools/base.py
=============
Defines the GitTool base class and the TOOL_REGISTRY.

Design goals
------------
- Each git action is a self-contained class (Single Responsibility).
- Adding a new action = write one class + register it. Zero changes to existing code.
- Risk level is declared on the class, not scattered through if/elif chains.
- Pre-checks are declared on the class as a list of callables.
- The registry can generate a help page automatically.
"""

from __future__ import annotations

import os
import subprocess
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Callable

from swij.config.settings import get_subprocess_timeout
from swij.core.observation import Observation

if TYPE_CHECKING:
    from swij.schemas.actions import GitActionPlan, RiskLevel


# ---------------------------------------------------------------------------
# Pre-check callable type alias
# ---------------------------------------------------------------------------

PreCheckFn = Callable[["GitActionPlan", str], "Observation | None"]
"""
A pre-check function receives:
  - plan: GitActionPlan — the parsed intent
  - cwd:  str           — the repo directory

It returns None if the check passes, or an Observation (failure) if it fails.
"""


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------

class GitTool(ABC):
    """
    Abstract base class for every git operation swij can perform.

    Subclasses must define:
      - action_name (str)          : must match an ActionType literal
      - risk_level  (RiskLevel)    : "green" | "yellow" | "red"
      - description (str)          : one-line human-readable description
      - pre_checks  (list)         : ordered list of PreCheckFn callables

    And implement:
      - execute(plan, cwd) -> Observation
    """

    action_name: str
    risk_level: "RiskLevel"
    description: str
    pre_checks: list[PreCheckFn] = []

    # ── Subprocess helper ─────────────────────────────────────────────────

    @staticmethod
    def run(
        args: list[str],
        cwd: str,
        timeout: int | None = None,
        input_text: str | None = None,
    ) -> Observation:
        """
        Run a git command via subprocess and return a structured Observation.

        Always uses the caller's shell environment (including PATH and
        git credential helpers) via env=os.environ.copy().
        """
        if timeout is None:
            timeout = get_subprocess_timeout()

        try:
            result = subprocess.run(
                args,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=os.environ.copy(),
                input=input_text,
            )
            return Observation.from_completed_process(result, command=args)
        except subprocess.TimeoutExpired:
            return Observation.timeout(command=args)
        except FileNotFoundError:
            # git binary not found at all
            return Observation(
                command=args,
                returncode=127,
                stdout="",
                stderr=(
                    f"Command not found: '{args[0]}'. "
                    "Make sure git is installed and available in your PATH."
                ),
            )

    # ── Abstract interface ─────────────────────────────────────────────────

    @abstractmethod
    def execute(self, plan: "GitActionPlan", cwd: str) -> Observation:
        """
        Execute this git operation.

        Parameters
        ----------
        plan : GitActionPlan   — the parsed, validated intent from the LLM
        cwd  : str             — the working directory (git repo root)

        Returns
        -------
        Observation capturing the result of the subprocess.
        """
        ...


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

class _ToolRegistry:
    """
    Central catalog of all registered GitTool classes.
    Tools register themselves via `register()`.
    The Execution Engine looks up tools from here.
    """

    def __init__(self) -> None:
        self._tools: dict[str, type[GitTool]] = {}

    def register(self, tool_cls: type[GitTool]) -> type[GitTool]:
        """Register a tool class. Can be used as a class decorator."""
        name = tool_cls.action_name
        if name in self._tools:
            raise ValueError(
                f"Duplicate tool registration: '{name}' is already registered by "
                f"{self._tools[name].__name__}."
            )
        self._tools[name] = tool_cls
        return tool_cls

    def get(self, action_name: str) -> type[GitTool] | None:
        return self._tools.get(action_name)

    def all_tools(self) -> dict[str, type[GitTool]]:
        return dict(self._tools)

    def help_table(self) -> list[dict[str, str]]:
        """Return a list of dicts suitable for rendering a help table."""
        rows = []
        for name, cls in sorted(self._tools.items()):
            rows.append(
                {
                    "action": name,
                    "risk": cls.risk_level,
                    "description": cls.description,
                }
            )
        return rows


TOOL_REGISTRY = _ToolRegistry()
