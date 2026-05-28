"""
core/execution_engine.py
========================
Routes a GitActionPlan to the correct tool in the TOOL_REGISTRY and
handles compound/multi-step workflows.

Importing all tool modules here triggers their self-registration in TOOL_REGISTRY.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from swij.core.observation import MultiObservation, Observation

# Import all tool modules to trigger @TOOL_REGISTRY.register decorators
import swij.tools.inspection_tools  # noqa: F401
import swij.tools.branch_tools      # noqa: F401
import swij.tools.commit_tools      # noqa: F401
import swij.tools.remote_tools      # noqa: F401
import swij.tools.destructive_tools  # noqa: F401

from swij.tools.base import TOOL_REGISTRY

if TYPE_CHECKING:
    from swij.schemas.actions import GitActionPlan


class ExecutionEngine:
    """
    Routes a validated GitActionPlan to the appropriate GitTool and executes it.
    Handles compound workflows (multi-step actions) internally.

    The engine expects:
    - Pre-checks have already been run and passed
    - Confirmation (for red-level actions) has already been obtained
    - The cwd is a valid git repository

    It never asks for user input — that's the agent loop's responsibility.
    """

    def execute(
        self,
        plan: "GitActionPlan",
        cwd: str,
    ) -> Observation | MultiObservation:
        """
        Execute the action defined in `plan` in the given `cwd`.

        Returns
        -------
        Observation          — for single-step actions
        MultiObservation     — for compound (multi-step) actions
        """
        action = plan.action

        # ── Compound workflows ────────────────────────────────────────────
        if action == "create_branch_workflow":
            return self._create_branch_workflow(plan, cwd)

        if action == "commit_and_push_workflow":
            return self._commit_and_push_workflow(plan, cwd)

        # ── Unknown / no-op ───────────────────────────────────────────────
        if action == "unknown":
            # The agent layer should never call execute() on an unknown action.
            # Return a synthetic observation so the synthesizer can respond.
            return Observation(
                command=[],
                returncode=0,
                stdout=plan.user_message or "",
                stderr="",
            )

        # ── Standard single-step tool lookup ──────────────────────────────
        tool_cls = TOOL_REGISTRY.get(action)
        if tool_cls is None:
            return Observation.pre_check_failure(
                f"No tool registered for action '{action}'. "
                "This is a swij internal error — please file a bug report."
            )

        tool = tool_cls()
        return tool.execute(plan, cwd)

    # ── Compound workflows ─────────────────────────────────────────────────

    def _create_branch_workflow(
        self, plan: "GitActionPlan", cwd: str
    ) -> MultiObservation:
        """
        fetch → create branch → (branch is already checked out by git checkout -b)
        """
        multi = MultiObservation()

        # Step 1: Fetch
        if plan.auto_fetch:
            remote = plan.remote_name or "origin"
            base = plan.base_branch or "HEAD"
            fetch_tool = TOOL_REGISTRY.get("git_fetch")
            if fetch_tool:
                fetch_obs = fetch_tool().execute(plan, cwd)
                fetch_obs.command = ["git", "fetch", remote, base]
                multi.steps.append(fetch_obs)
                if not fetch_obs.success:
                    # Non-blocking — proceed even if fetch fails
                    pass

        # Step 2: Create & checkout branch
        create_tool = TOOL_REGISTRY.get("create_branch")
        if create_tool:
            # Avoid double-fetching in the tool itself
            import copy
            plan_no_fetch = copy.copy(plan)
            plan_no_fetch.auto_fetch = False
            create_obs = create_tool().execute(plan_no_fetch, cwd)
            multi.steps.append(create_obs)

        return multi

    def _commit_and_push_workflow(
        self, plan: "GitActionPlan", cwd: str
    ) -> MultiObservation:
        """
        git add → git commit → git push
        """
        multi = MultiObservation()

        # Step 1: Stage
        add_tool = TOOL_REGISTRY.get("git_add")
        if add_tool:
            add_obs = add_tool().execute(plan, cwd)
            multi.steps.append(add_obs)
            if not add_obs.success:
                return multi  # stop if staging failed

        # Step 2: Commit
        commit_tool = TOOL_REGISTRY.get("git_commit")
        if commit_tool:
            commit_obs = commit_tool().execute(plan, cwd)
            multi.steps.append(commit_obs)
            if not commit_obs.success:
                return multi  # stop if commit failed

        # Step 3: Push
        push_tool = TOOL_REGISTRY.get("git_push")
        if push_tool:
            push_obs = push_tool().execute(plan, cwd)
            multi.steps.append(push_obs)

        return multi

    @staticmethod
    def get_cwd() -> str:
        """Return the current working directory as a string."""
        return os.getcwd()
