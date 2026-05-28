"""
core/agent.py
=============
The main agentic loop that orchestrates all layers of swij.

Data flow (happy path):
  User input
    → IntentParser    (English → GitActionPlan)
    → PreCheckEngine  (pre-flight validation)
    → Confirmation    (if red-level or advisory)
    → ExecutionEngine (GitActionPlan → subprocess)
    → ResponseSynthesizer (raw output → natural language)
    → Renderer        (display to user)

Ctrl+C handling:
  - Caught cleanly at the top level
  - Displays what completed vs. what didn't
  - Repository is never left in an unknown state without the user knowing
"""

from __future__ import annotations

import os
import subprocess
from typing import Optional

from swij.config.settings import get_confidence_threshold
from swij.core.execution_engine import ExecutionEngine
from swij.core.intent_parser import IntentParser
from swij.core.observation import MultiObservation, Observation
from swij.core.pre_check_engine import PreCheckEngine
from swij.core.response_synthesizer import ResponseSynthesizer
from swij.schemas.actions import GitActionPlan
from swij.ui import renderer


class Agent:
    """
    The main swij agent. Instantiate once per invocation.

    Usage
    -----
    agent = Agent()
    agent.run("create a branch from develop called fix-login")
    """

    def __init__(self) -> None:
        self._parser = IntentParser()
        self._pre_check = PreCheckEngine()
        self._engine = ExecutionEngine()
        self._synthesizer = ResponseSynthesizer()
        self._confidence_threshold = get_confidence_threshold()

    def run(self, user_input: str) -> None:
        """
        Process a single user request end-to-end.
        This is the top-level entry point called from main.py.
        """
        cwd = os.getcwd()

        try:
            self._process(user_input, cwd)
        except KeyboardInterrupt:
            renderer.print_interrupted(completed_steps=[])
        except RuntimeError as exc:
            renderer.print_error(str(exc))

    # ── Core pipeline ─────────────────────────────────────────────────────

    def _process(self, user_input: str, cwd: str) -> None:
        """Inner pipeline — can raise KeyboardInterrupt and RuntimeError."""

        # ── Step 1: Parse intent ──────────────────────────────────────────
        with renderer.thinking("Parsing your request…"):
            repo_context = self._get_repo_context(cwd)
            plan = self._parser.parse(user_input, context=repo_context)

        # ── Step 2: Handle unknown intent ─────────────────────────────────
        if plan.action == "unknown":
            message = plan.user_message or (
                "I couldn't understand that request. "
                "Try something like 'show git status' or 'create a branch'."
            )
            renderer.print_clarification_request(message)
            return

        # ── Step 3: Handle low confidence ─────────────────────────────────
        if plan.confidence < self._confidence_threshold:
            message = plan.user_message or (
                f"I interpreted your request as **{plan.action}** but I'm not confident "
                f"(confidence: {plan.confidence:.0%}). Could you be more specific?"
            )
            renderer.print_clarification_request(message)
            return

        # ── Step 4: Run pre-checks ────────────────────────────────────────
        with renderer.thinking("Running pre-flight checks…"):
            check_result = self._pre_check.run(plan, cwd)

        # ── Step 5: Handle blocking pre-check failure ─────────────────────
        if not check_result.passed:
            with renderer.thinking("Analyzing the issue…"):
                message = self._synthesizer.synthesize_pre_check_failure(
                    plan,
                    check_result.blocking_observation,  # type: ignore[arg-type]
                    user_input,
                )
            renderer.print_error(message)
            return

        # ── Step 6: Handle advisories (stale branch, dirty tree warnings) ─
        for advisory in check_result.advisories:
            # Special case: stale branch advisory → ask if user wants to pull
            if "behind" in advisory.stderr and plan.base_branch:
                commits_behind = advisory.stdout or "some"
                remote = plan.remote_name or "origin"
                should_pull = renderer.confirm_stale_branch(
                    plan.base_branch, commits_behind, remote
                )
                if should_pull:
                    self._pull_base_branch(plan, cwd)
            else:
                # Generic advisory — synthesize and ask to confirm
                with renderer.thinking("Preparing advisory…"):
                    advisory_message = self._synthesizer.synthesize_advisory(
                        plan, advisory, user_input
                    )
                should_proceed = renderer.confirm_advisory(advisory_message)
                if not should_proceed:
                    renderer.print_success("Cancelled. No changes were made.")
                    return

        # ── Step 7: Confirm destructive operations ────────────────────────
        if plan.is_destructive or plan.needs_confirmation:
            details = self._build_confirmation_details(plan)
            confirmed = renderer.confirm_destructive(plan.action, details)
            if not confirmed:
                renderer.print_success("Cancelled. No changes were made.")
                return

        # ── Step 8: Execute ───────────────────────────────────────────────
        completed_steps: list[str] = []
        try:
            with renderer.thinking(f"Running {plan.action}…"):
                observation = self._engine.execute(plan, cwd)

            if isinstance(observation, MultiObservation):
                for step_obs in observation.steps:
                    if step_obs.success:
                        completed_steps.append(" ".join(step_obs.command))

        except KeyboardInterrupt:
            renderer.print_interrupted(completed_steps=completed_steps)
            return

        # ── Step 9: Synthesize response ───────────────────────────────────
        with renderer.thinking("Preparing response…"):
            response = self._synthesizer.synthesize(plan, observation, user_input)

        renderer.print_response(response, action=plan.action)

    # ── Helpers ───────────────────────────────────────────────────────────

    def _get_repo_context(self, cwd: str) -> Optional[str]:
        """
        Gather current repo state to give the LLM better context.
        Runs silently — failures are non-fatal.
        """
        parts = []
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=cwd, capture_output=True, text=True, timeout=5,
                env=os.environ.copy(),
            )
            if result.returncode == 0:
                parts.append(f"current branch: {result.stdout.strip()}")

            result2 = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=cwd, capture_output=True, text=True, timeout=5,
                env=os.environ.copy(),
            )
            if result2.returncode == 0 and result2.stdout.strip():
                parts.append("working tree has uncommitted changes")

        except Exception:
            pass  # context is optional

        return "; ".join(parts) if parts else None

    def _pull_base_branch(self, plan: GitActionPlan, cwd: str) -> None:
        """Pull the base branch before branching."""
        base = plan.base_branch
        remote = plan.remote_name or "origin"
        with renderer.thinking(f"Pulling {remote}/{base}…"):
            result = subprocess.run(
                ["git", "pull", remote, base],
                cwd=cwd, capture_output=True, text=True, timeout=30,
                env=os.environ.copy(),
            )
        if result.returncode == 0:
            renderer.print_success(f"Pulled latest `{base}` from `{remote}`.")
        else:
            renderer.print_warning(
                f"Pull of `{base}` failed. Continuing with your current local state."
            )

    def _build_confirmation_details(self, plan: GitActionPlan) -> str:
        """Build a human-readable detail string for the confirmation dialog."""
        parts = []
        if plan.action == "git_reset":
            mode = plan.reset_mode or "mixed"
            target = plan.reset_target or "HEAD~1"
            parts.append(f"Reset mode: **{mode}**")
            parts.append(f"Reset target: `{target}`")
            if mode == "hard":
                parts.append("\n⚠ **Hard reset will permanently discard uncommitted changes.**")
        elif plan.action == "delete_branch":
            parts.append(f"Branch to delete: `{plan.branch_name}`")
        elif plan.action == "git_merge":
            parts.append(f"Merging `{plan.branch_name}` into current branch.")
        elif plan.action == "git_rebase":
            parts.append(f"Rebasing current branch onto `{plan.base_branch or plan.branch_name}`.")
        elif plan.action == "git_restore":
            if plan.files_to_add:
                parts.append(f"Files to restore: `{'`, `'.join(plan.files_to_add)}`")
            else:
                parts.append("All tracked files will be restored (all local changes discarded).")
        elif plan.action == "git_cherry_pick":
            parts.append(f"Commit to cherry-pick: `{plan.reset_target}`")

        return "\n".join(parts) if parts else f"Action: `{plan.action}`"
