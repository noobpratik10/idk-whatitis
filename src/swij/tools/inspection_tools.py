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
    llm_description = (
        "Get the current status of the git repository. Shows which files are staged, "
        "unstaged, or untracked. Call this first to understand the repository state."
    )
    llm_parameters = {}

    def execute(self, plan: GitActionPlan, cwd: str) -> Observation:
        return self.run(["git", "status", "--short", "--branch"], cwd=cwd)


@TOOL_REGISTRY.register
class GitDiffTool(GitTool):
    action_name = "git_diff"
    risk_level = "green"
    description = "Show changes between commits, working tree, or a specific file/ref"
    pre_checks = []
    llm_description = (
        "Show the diff of uncommitted changes. Use this to understand what was changed "
        "before writing a commit message or summarizing work. "
        "Set staged=true to see staged (cached) changes, false for unstaged."
    )
    llm_parameters = {
        "staged": {
            "type": "boolean",
            "description": "If true, show staged (cached) changes. If false, show unstaged changes.",
        },
        "file_path": {
            "type": "string",
            "description": "Optional: path to a specific file to diff.",
        },
    }

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
    llm_description = (
        "Show recent commit history. Use this to understand what changed recently, "
        "find commit SHAs, or answer questions about the project history."
    )
    llm_parameters = {
        "count": {
            "type": "integer",
            "description": "Number of recent commits to show. Defaults to 10.",
        },
    }

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
    llm_description = (
        "List all local and remote git branches. Use this to answer questions about "
        "available branches or to verify a branch name before operating on it."
    )
    llm_parameters = {}

    def execute(self, plan: GitActionPlan, cwd: str) -> Observation:
        return self.run(["git", "branch", "-a", "--color=never"], cwd=cwd)


@TOOL_REGISTRY.register
class GitRemoteTool(GitTool):
    action_name = "git_remote"
    risk_level = "green"
    description = "Show configured remote repositories and their URLs"
    pre_checks = []
    llm_description = (
        "Show the configured remote repositories and their URLs. "
        "Use this to check what remote is available before a push or pull."
    )
    llm_parameters = {}

    def execute(self, plan: GitActionPlan, cwd: str) -> Observation:
        return self.run(["git", "remote", "-v"], cwd=cwd)
