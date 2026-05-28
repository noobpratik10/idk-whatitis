"""
tools/branch_tools.py
=====================
Branch management operations: create_branch, checkout_branch, delete_branch
"""

from __future__ import annotations

from swij.core.observation import Observation
from swij.schemas.actions import GitActionPlan
from swij.tools.base import TOOL_REGISTRY, GitTool


@TOOL_REGISTRY.register
class CreateBranchTool(GitTool):
    action_name = "create_branch"
    risk_level = "yellow"
    description = "Create a new branch, optionally from a base branch"
    pre_checks = []  # Pre-checks are handled by PreCheckEngine

    def execute(self, plan: GitActionPlan, cwd: str) -> Observation:
        branch_name = plan.branch_name
        if not branch_name:
            return Observation.pre_check_failure("No branch name provided.")

        # Step 1: Fetch the base branch first (if requested)
        if plan.auto_fetch:
            remote = plan.remote_name or "origin"
            base = plan.base_branch or "HEAD"
            fetch_obs = self.run(
                ["git", "fetch", remote, base],
                cwd=cwd,
            )
            if not fetch_obs.success:
                # Non-fatal — continue without fetching (remote may not exist yet)
                pass

        # Step 2: Create branch
        args = ["git", "checkout", "-b", branch_name]
        if plan.base_branch:
            remote = plan.remote_name or "origin"
            # Branch from the remote-tracking ref if it exists
            remote_ref = f"{remote}/{plan.base_branch}"
            args.append(remote_ref)

        obs = self.run(args, cwd=cwd)

        # Fallback: if remote ref doesn't exist, try local base branch
        if not obs.success and plan.base_branch:
            args_local = ["git", "checkout", "-b", branch_name, plan.base_branch]
            obs = self.run(args_local, cwd=cwd)

        return obs


@TOOL_REGISTRY.register
class CheckoutBranchTool(GitTool):
    action_name = "checkout_branch"
    risk_level = "yellow"
    description = "Switch to an existing branch"
    pre_checks = []

    def execute(self, plan: GitActionPlan, cwd: str) -> Observation:
        branch_name = plan.branch_name
        if not branch_name:
            return Observation.pre_check_failure("No branch name provided.")

        return self.run(["git", "checkout", branch_name], cwd=cwd)


@TOOL_REGISTRY.register
class DeleteBranchTool(GitTool):
    action_name = "delete_branch"
    risk_level = "red"
    description = "Delete a local branch (requires explicit confirmation)"
    pre_checks = []

    def execute(self, plan: GitActionPlan, cwd: str) -> Observation:
        branch_name = plan.branch_name
        if not branch_name:
            return Observation.pre_check_failure("No branch name provided.")

        flag = "-D" if plan.force else "-d"
        return self.run(["git", "branch", flag, branch_name], cwd=cwd)
