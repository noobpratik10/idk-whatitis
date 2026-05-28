"""
tools/remote_tools.py
=====================
Remote operations: git_fetch, git_pull, git_push, git_clone
"""

from __future__ import annotations

from swij.core.observation import Observation
from swij.schemas.actions import GitActionPlan
from swij.tools.base import TOOL_REGISTRY, GitTool


@TOOL_REGISTRY.register
class GitFetchTool(GitTool):
    action_name = "git_fetch"
    risk_level = "yellow"
    description = "Fetch updates from a remote repository"
    pre_checks = []

    def execute(self, plan: GitActionPlan, cwd: str) -> Observation:
        remote = plan.remote_name or "origin"
        args = ["git", "fetch", remote]
        if plan.branch_name:
            args.append(plan.branch_name)
        return self.run(args, cwd=cwd)


@TOOL_REGISTRY.register
class GitPullTool(GitTool):
    action_name = "git_pull"
    risk_level = "yellow"
    description = "Fetch and integrate changes from a remote branch"
    pre_checks = []

    def execute(self, plan: GitActionPlan, cwd: str) -> Observation:
        args = ["git", "pull"]
        if plan.remote_name:
            args.append(plan.remote_name)
            if plan.branch_name:
                args.append(plan.branch_name)
        return self.run(args, cwd=cwd)


@TOOL_REGISTRY.register
class GitPushTool(GitTool):
    action_name = "git_push"
    risk_level = "yellow"
    description = "Push commits to a remote branch"
    pre_checks = []

    def execute(self, plan: GitActionPlan, cwd: str) -> Observation:
        remote = plan.remote_name or "origin"
        args = ["git", "push"]
        if plan.force:
            args.append("--force-with-lease")  # safer than --force
        args.append(remote)
        if plan.branch_name:
            # Push to same remote branch name by default
            args.append(f"HEAD:{plan.branch_name}")
        else:
            # Push current branch tracking its upstream
            args += ["--set-upstream", remote, "HEAD"]
        return self.run(args, cwd=cwd)


@TOOL_REGISTRY.register
class GitCloneTool(GitTool):
    action_name = "git_clone"
    risk_level = "yellow"
    description = "Clone a remote repository to a local directory"
    pre_checks = []

    def execute(self, plan: GitActionPlan, cwd: str) -> Observation:
        if not plan.remote_url:
            return Observation.pre_check_failure(
                "No remote URL provided for clone."
            )
        args = ["git", "clone", plan.remote_url]
        if plan.target_directory:
            args.append(plan.target_directory)
        return self.run(args, cwd=cwd, timeout=120)  # clones can take longer
