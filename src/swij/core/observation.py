"""
core/observation.py
===================
Captures raw subprocess results and structures them for downstream consumption
by the Response Synthesizer and the Execution Engine.

The golden rule: raw stderr is NEVER surfaced to the user directly.
Everything goes through the Observation → Synthesizer pipeline.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Observation:
    """
    Structured capture of a single subprocess git command result.

    Attributes
    ----------
    command:        The exact command list that was run (e.g. ['git', 'status'])
    returncode:     Process exit code (0 = success, non-zero = failure)
    stdout:         Standard output as a string (stripped of leading/trailing whitespace)
    stderr:         Standard error as a string (stripped)
    success:        Convenience flag — True when returncode == 0
    timed_out:      True if the process was killed because it exceeded the timeout
    partial_steps:  Steps that completed BEFORE an interruption (for Ctrl+C reporting)
    """

    command: list[str]
    returncode: int
    stdout: str
    stderr: str
    success: bool = field(init=False)
    timed_out: bool = False
    partial_steps: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.success = self.returncode == 0

    # ── Factories ─────────────────────────────────────────────────────────

    @classmethod
    def from_completed_process(
        cls,
        result: subprocess.CompletedProcess,  # type: ignore[type-arg]
        command: list[str],
    ) -> "Observation":
        return cls(
            command=command,
            returncode=result.returncode,
            stdout=(result.stdout or "").strip(),
            stderr=(result.stderr or "").strip(),
        )

    @classmethod
    def timeout(cls, command: list[str]) -> "Observation":
        """Create an Observation representing a timed-out process."""
        return cls(
            command=command,
            returncode=-1,
            stdout="",
            stderr="Process timed out.",
            timed_out=True,
        )

    @classmethod
    def pre_check_failure(cls, message: str) -> "Observation":
        """Create a synthetic Observation for a pre-check validation failure."""
        return cls(
            command=[],
            returncode=1,
            stdout="",
            stderr=message,
        )

    @classmethod
    def interrupted(
        cls, command: list[str], partial_steps: list[str]
    ) -> "Observation":
        """Create an Observation for a user-interrupted (Ctrl+C) execution."""
        return cls(
            command=command,
            returncode=-2,
            stdout="",
            stderr="Interrupted by user.",
            partial_steps=partial_steps,
        )

    # ── Serialisation for LLM context ────────────────────────────────────

    def to_llm_context(self) -> str:
        """
        Serialize this observation into a natural-language context string
        that gets injected into the Gemini prompt for response synthesis.
        """
        cmd_str = " ".join(self.command) if self.command else "(pre-check)"
        lines = [f"Command: `{cmd_str}`"]

        if self.timed_out:
            lines.append("Result: TIMED OUT — the process exceeded the allowed time limit.")
        elif self.returncode == -2:
            lines.append("Result: INTERRUPTED by user (Ctrl+C).")
            if self.partial_steps:
                lines.append("Completed steps before interruption:")
                for step in self.partial_steps:
                    lines.append(f"  ✓ {step}")
        elif self.success:
            lines.append("Result: SUCCESS (exit code 0)")
            if self.stdout:
                lines.append(f"Output:\n{self.stdout}")
        else:
            lines.append(f"Result: FAILED (exit code {self.returncode})")
            if self.stderr:
                lines.append(f"Error output:\n{self.stderr}")
            if self.stdout:
                lines.append(f"Standard output:\n{self.stdout}")

        return "\n".join(lines)

    def __repr__(self) -> str:
        status = "OK" if self.success else f"ERR({self.returncode})"
        cmd = " ".join(self.command) if self.command else "(pre-check)"
        return f"<Observation [{status}] cmd='{cmd}'>"


@dataclass
class MultiObservation:
    """
    Aggregated result from a compound (multi-step) workflow.
    Each step produces one Observation; this bundles them with summary metadata.
    """

    steps: list[Observation] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return all(obs.success for obs in self.steps)

    @property
    def failed_step(self) -> Optional[Observation]:
        for obs in self.steps:
            if not obs.success:
                return obs
        return None

    def to_llm_context(self) -> str:
        parts = [f"Multi-step workflow — {len(self.steps)} step(s):"]
        for i, obs in enumerate(self.steps, 1):
            parts.append(f"\nStep {i}: {obs.to_llm_context()}")
        return "\n".join(parts)
