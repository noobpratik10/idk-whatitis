"""
tools/inspection_tools.py
=========================
Safe (green) read-only git operations:
  git_status, git_diff, git_log, list_branches, git_remote

These execute immediately with no confirmation required.
"""

from __future__ import annotations

from swij.core.observation import Observation
from swij.schemas.actions import GitActionPlan
from swij.tools.base import TOOL_REGISTRY, GitTool


@TOOL_REGISTRY.register
class GitStatusTool(GitTool):
    action_name = "git_status"
    risk_level = "green"
    description = "Show the working tree status (staged, unstaged, untracked files)"
    pre_checks = []

    def execute(self, plan: GitActionPlan, cwd: str) -> Observation:
        return self.run(["git", "status", "--short", "--branch"], cwd=cwd)


@TOOL_REGISTRY.register
class GitDiffTool(GitTool):
    action_name = "git_diff"
    risk_level = "green"
    description = "Show changes between commits, working tree, or a specific file/ref"
    pre_checks = []

    def execute(self, plan: GitActionPlan, cwd: str) -> Observation:
        args = ["git", "diff"]
        if plan.diff_staged:
            args.append("--cached")
        if plan.diff_target:
            args.append(plan.diff_target)
        # Use --stat for a compact summary if there's no specific target
        if not plan.diff_staged and not plan.diff_target:
            args.append("--stat")
        return self.run(args, cwd=cwd)


@TOOL_REGISTRY.register
class GitLogTool(GitTool):
    action_name = "git_log"
    risk_level = "green"
    description = "Show commit history with author, date, and message"
    pre_checks = []

    def execute(self, plan: GitActionPlan, cwd: str) -> Observation:
        count = plan.log_count or 10
        args = [
            "git", "log",
            f"-{count}",
            "--oneline",
            "--decorate",
            "--graph",
        ]
        return self.run(args, cwd=cwd)


@TOOL_REGISTRY.register
class ListBranchesTool(GitTool):
    action_name = "list_branches"
    risk_level = "green"
    description = "List all local and remote branches"
    pre_checks = []

    def execute(self, plan: GitActionPlan, cwd: str) -> Observation:
        return self.run(["git", "branch", "-a", "--color=never"], cwd=cwd)


@TOOL_REGISTRY.register
class GitRemoteTool(GitTool):
    action_name = "git_remote"
    risk_level = "green"
    description = "Show configured remote repositories and their URLs"
    pre_checks = []

    def execute(self, plan: GitActionPlan, cwd: str) -> Observation:
        return self.run(["git", "remote", "-v"], cwd=cwd)
