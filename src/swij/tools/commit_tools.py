"""
tools/commit_tools.py
=====================
Staging and committing operations: git_add, git_commit, git_stash, git_stash_pop
"""

from __future__ import annotations

from swij.core.observation import Observation
from swij.schemas.actions import GitActionPlan
from swij.tools.base import TOOL_REGISTRY, GitTool


@TOOL_REGISTRY.register
class GitAddTool(GitTool):
    action_name = "git_add"
    risk_level = "yellow"
    description = "Stage files for commit (specific files or all changes)"
    pre_checks = []

    def execute(self, plan: GitActionPlan, cwd: str) -> Observation:
        if plan.files_to_add:
            args = ["git", "add", "--"] + plan.files_to_add
        else:
            args = ["git", "add", "."]
        return self.run(args, cwd=cwd)


@TOOL_REGISTRY.register
class GitCommitTool(GitTool):
    action_name = "git_commit"
    risk_level = "yellow"
    description = "Commit staged changes with a message"
    pre_checks = []

    def execute(self, plan: GitActionPlan, cwd: str) -> Observation:
        message = plan.commit_message
        if not message:
            return Observation.pre_check_failure(
                "No commit message provided. Please specify a message."
            )
        return self.run(["git", "commit", "-m", message], cwd=cwd)


@TOOL_REGISTRY.register
class GitStashTool(GitTool):
    action_name = "git_stash"
    risk_level = "yellow"
    description = "Stash current working tree changes"
    pre_checks = []

    def execute(self, plan: GitActionPlan, cwd: str) -> Observation:
        args = ["git", "stash", "push"]
        if plan.stash_message:
            args += ["-m", plan.stash_message]
        return self.run(args, cwd=cwd)


@TOOL_REGISTRY.register
class GitStashPopTool(GitTool):
    action_name = "git_stash_pop"
    risk_level = "yellow"
    description = "Apply the most recent stash and remove it from the stash list"
    pre_checks = []

    def execute(self, plan: GitActionPlan, cwd: str) -> Observation:
        return self.run(["git", "stash", "pop"], cwd=cwd)
