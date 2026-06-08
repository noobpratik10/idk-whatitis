"""
tools/destructive_tools.py
==========================
Red-level git operations that ALWAYS require explicit user confirmation:
  git_reset, git_restore, git_merge, git_rebase, git_cherry_pick

The confirmation is enforced by the agent loop / pre-check engine.
These tools assume confirmation has already been received before execute() is called.
"""

from __future__ import annotations

from swij.core.observation import Observation
from swij.schemas.actions import GitActionPlan
from swij.tools.base import TOOL_REGISTRY, GitTool


@TOOL_REGISTRY.register
class GitResetTool(GitTool):
    action_name = "git_reset"
    risk_level = "red"
    description = "Reset HEAD to a previous commit (soft/mixed/hard — requires confirmation)"
    pre_checks = []
    llm_description = (
        "Reset HEAD to a previous commit. DESTRUCTIVE — ALWAYS requires explicit user confirmation. "
        "Mode: soft (keep staged), mixed (unstage), hard (discard all changes)."
    )
    llm_parameters = {
        "mode": {"type": "string", "description": "Reset mode: 'soft', 'mixed', or 'hard'."},
        "target": {"type": "string", "description": "Commit ref to reset to, e.g. 'HEAD~1' or a SHA."},
    }

    def execute(self, plan: GitActionPlan, cwd: str) -> Observation:
        mode = plan.reset_mode or "mixed"
        target = plan.reset_target or "HEAD~1"
        return self.run(["git", "reset", f"--{mode}", target], cwd=cwd)


@TOOL_REGISTRY.register
class GitRestoreTool(GitTool):
    action_name = "git_restore"
    risk_level = "red"
    description = "Restore working tree files (discard changes — requires confirmation)"
    pre_checks = []
    llm_description = (
        "Discard local file changes, restoring them to the last committed state. "
        "DESTRUCTIVE — ALWAYS requires explicit user confirmation."
    )
    llm_parameters = {
        "files": {"type": "string", "description": "Comma-separated file paths to restore. Leave empty to restore all."},
    }

    def execute(self, plan: GitActionPlan, cwd: str) -> Observation:
        if plan.files_to_add:
            # Restore specific files
            args = ["git", "restore", "--"] + plan.files_to_add
        else:
            # Restore all tracked files
            args = ["git", "restore", "."]
        return self.run(args, cwd=cwd)


@TOOL_REGISTRY.register
class GitMergeTool(GitTool):
    action_name = "git_merge"
    risk_level = "red"
    description = "Merge a branch into the current branch (requires confirmation)"
    pre_checks = []
    llm_description = (
        "Merge a branch into the current branch. "
        "DESTRUCTIVE — ALWAYS requires explicit user confirmation."
    )
    llm_parameters = {
        "branch_name": {"type": "string", "description": "Name of the branch to merge in."},
    }

    def execute(self, plan: GitActionPlan, cwd: str) -> Observation:
        branch_name = plan.branch_name
        if not branch_name:
            return Observation.pre_check_failure("No branch name provided for merge.")
        return self.run(["git", "merge", branch_name], cwd=cwd)


@TOOL_REGISTRY.register
class GitRebaseTool(GitTool):
    action_name = "git_rebase"
    risk_level = "red"
    description = "Rebase current branch onto another (requires confirmation)"
    pre_checks = []
    llm_description = (
        "Rebase the current branch onto another branch. "
        "DESTRUCTIVE — ALWAYS requires explicit user confirmation."
    )
    llm_parameters = {
        "branch_name": {"type": "string", "description": "Branch to rebase onto."},
    }

    def execute(self, plan: GitActionPlan, cwd: str) -> Observation:
        branch_name = plan.base_branch or plan.branch_name
        if not branch_name:
            return Observation.pre_check_failure("No target branch provided for rebase.")
        return self.run(["git", "rebase", branch_name], cwd=cwd)


@TOOL_REGISTRY.register
class GitCherryPickTool(GitTool):
    action_name = "git_cherry_pick"
    risk_level = "red"
    description = "Apply a specific commit onto the current branch (requires confirmation)"
    pre_checks = []
    llm_description = (
        "Apply a specific commit from another branch onto the current branch. "
        "DESTRUCTIVE — ALWAYS requires explicit user confirmation."
    )
    llm_parameters = {
        "commit": {"type": "string", "description": "Commit SHA or ref to cherry-pick."},
    }

    def execute(self, plan: GitActionPlan, cwd: str) -> Observation:
        target = plan.reset_target  # reuse the ref field
        if not target:
            return Observation.pre_check_failure("No commit SHA/ref provided for cherry-pick.")
        return self.run(["git", "cherry-pick", target], cwd=cwd)
