"""
core/pre_check_engine.py
========================
Runs a set of pre-flight checks before the Execution Engine is called.

Philosophy
----------
- LOW risk checks: run silently, automatically.
- MEDIUM risk findings: shown to the user as info/warnings, execution continues.
- HIGH risk findings: agent STOPS and presents options to the user.

Each check is a standalone function: (plan, cwd) -> Observation | None
  - Returns None     → check passed, nothing to report
  - Returns Observation (success=True)  → advisory (show warning but continue)
  - Returns Observation (success=False) → blocking failure (stop execution)
"""

from __future__ import annotations

import os
import subprocess
from typing import TYPE_CHECKING, Optional

from swij.core.observation import Observation

if TYPE_CHECKING:
    from swij.schemas.actions import GitActionPlan


# ---------------------------------------------------------------------------
# Helper: run a quick git query (used only inside pre-checks)
# ---------------------------------------------------------------------------

def _git_query(args: list[str], cwd: str) -> tuple[int, str, str]:
    """Run a git command and return (returncode, stdout, stderr)."""
    try:
        result = subprocess.run(
            args,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=10,
            env=os.environ.copy(),
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", "timed out"
    except FileNotFoundError:
        return 127, "", "git not found in PATH"


# ---------------------------------------------------------------------------
# Individual pre-check functions
# ---------------------------------------------------------------------------

def check_git_installed(plan: "GitActionPlan", cwd: str) -> Optional[Observation]:
    """Verify git is available in PATH."""
    rc, _, stderr = _git_query(["git", "--version"], cwd)
    if rc != 0:
        return Observation.pre_check_failure(
            "git is not installed or not in your PATH. "
            "Install git and try again."
        )
    return None


def check_is_git_repo(plan: "GitActionPlan", cwd: str) -> Optional[Observation]:
    """Verify the current directory is inside a git repository."""
    rc, _, _ = _git_query(["git", "rev-parse", "--git-dir"], cwd)
    if rc != 0:
        return Observation.pre_check_failure(
            f"'{cwd}' is not a git repository. "
            "Navigate to a git repo and try again."
        )
    return None


def check_uncommitted_changes(plan: "GitActionPlan", cwd: str) -> Optional[Observation]:
    """
    Warn if the working tree is dirty before a checkout/switch.
    This is a BLOCKING check — git checkout will fail if the tree is dirty.
    """
    rc, stdout, _ = _git_query(["git", "status", "--porcelain"], cwd)
    if rc == 0 and stdout:
        # There are uncommitted changes — this is a blocking finding
        return Observation(
            command=["git", "status", "--porcelain"],
            returncode=1,
            stdout=stdout,
            stderr=(
                "You have uncommitted changes in your working tree. "
                "Checking out another branch may fail or overwrite your work."
            ),
        )
    return None


def check_branch_exists_locally(plan: "GitActionPlan", cwd: str) -> Optional[Observation]:
    """Check if the branch name to be created already exists locally."""
    if not plan.branch_name:
        return None
    rc, stdout, _ = _git_query(
        ["git", "branch", "--list", plan.branch_name], cwd
    )
    if rc == 0 and plan.branch_name in stdout:
        return Observation.pre_check_failure(
            f"Branch '{plan.branch_name}' already exists locally. "
            "Choose a different name, or check it out with 'swij checkout'."
        )
    return None


def check_nothing_staged(plan: "GitActionPlan", cwd: str) -> Optional[Observation]:
    """Fail if no files are staged before a commit."""
    rc, stdout, _ = _git_query(["git", "diff", "--cached", "--name-only"], cwd)
    if rc == 0 and not stdout:
        return Observation.pre_check_failure(
            "Nothing is staged for commit. "
            "Stage your changes first with 'swij add' or 'swij stage all'."
        )
    return None


def check_no_active_merge(plan: "GitActionPlan", cwd: str) -> Optional[Observation]:
    """Fail if there is already an in-progress merge."""
    rc, stdout, _ = _git_query(["git", "rev-parse", "--git-dir"], cwd)
    if rc == 0 and stdout:
        merge_head = os.path.join(stdout, "MERGE_HEAD")
        if os.path.exists(merge_head):
            return Observation.pre_check_failure(
                "There is already a merge in progress. "
                "Resolve the conflicts first, then commit."
            )
    return None


def check_remote_exists(plan: "GitActionPlan", cwd: str) -> Optional[Observation]:
    """Warn if no remote is configured (relevant for push/pull)."""
    rc, stdout, _ = _git_query(["git", "remote"], cwd)
    if rc == 0 and not stdout:
        return Observation.pre_check_failure(
            "No remote repository is configured. "
            "Add a remote with: git remote add origin <url>"
        )
    return None


def check_stash_exists(plan: "GitActionPlan", cwd: str) -> Optional[Observation]:
    """Fail if stash pop is requested but the stash is empty."""
    rc, stdout, _ = _git_query(["git", "stash", "list"], cwd)
    if rc == 0 and not stdout:
        return Observation.pre_check_failure(
            "There are no stashed changes to pop."
        )
    return None


def check_local_behind_remote(plan: "GitActionPlan", cwd: str) -> Optional[Observation]:
    """
    Advisory check: warn if the local base branch is behind its remote.
    This is informational (returns a success Observation with a warning message)
    so the agent can present it to the user before asking if they want to pull.
    """
    base = plan.base_branch
    if not base:
        return None

    remote = plan.remote_name or "origin"
    rc, stdout, _ = _git_query(
        ["git", "rev-list", "--count", f"{base}..{remote}/{base}"],
        cwd,
    )
    if rc == 0 and stdout and stdout != "0":
        return Observation(
            command=["git", "rev-list", "--count", f"{base}..{remote}/{base}"],
            returncode=0,  # success=True — this is advisory, not blocking
            stdout=stdout,
            stderr=(
                f"⚠ Your local '{base}' is {stdout} commit(s) behind "
                f"'{remote}/{base}'. Consider pulling first."
            ),
        )
    return None


# ---------------------------------------------------------------------------
# Pre-check sets per action
# ---------------------------------------------------------------------------

# Every action gets at minimum these two checks
BASE_CHECKS = [check_git_installed, check_is_git_repo]

ACTION_PRE_CHECKS: dict[str, list] = {
    "git_status":        BASE_CHECKS,
    "git_diff":          BASE_CHECKS,
    "git_log":           BASE_CHECKS,
    "list_branches":     BASE_CHECKS,
    "git_remote":        BASE_CHECKS,
    "create_branch":     BASE_CHECKS + [check_branch_exists_locally, check_local_behind_remote],
    "checkout_branch":   BASE_CHECKS + [check_uncommitted_changes],
    "delete_branch":     BASE_CHECKS,
    "git_add":           BASE_CHECKS,
    "git_commit":        BASE_CHECKS + [check_nothing_staged],
    "git_stash":         BASE_CHECKS,
    "git_stash_pop":     BASE_CHECKS + [check_stash_exists],
    "git_fetch":         BASE_CHECKS + [check_remote_exists],
    "git_pull":          BASE_CHECKS + [check_uncommitted_changes, check_remote_exists],
    "git_push":          BASE_CHECKS + [check_remote_exists],
    "git_clone":         BASE_CHECKS,
    "git_reset":         BASE_CHECKS,
    "git_restore":       BASE_CHECKS,
    "git_merge":         BASE_CHECKS + [check_no_active_merge, check_uncommitted_changes],
    "git_rebase":        BASE_CHECKS + [check_uncommitted_changes],
    "git_cherry_pick":   BASE_CHECKS,
    "create_branch_workflow":    BASE_CHECKS + [check_branch_exists_locally],
    "commit_and_push_workflow":  BASE_CHECKS + [check_nothing_staged, check_remote_exists],
    "unknown":           [],
}


# ---------------------------------------------------------------------------
# Engine class
# ---------------------------------------------------------------------------

class PreCheckResult:
    """Result of running all pre-checks for an action."""

    def __init__(
        self,
        passed: bool,
        blocking_observation: Optional[Observation] = None,
        advisories: Optional[list[Observation]] = None,
    ) -> None:
        self.passed = passed
        self.blocking_observation = blocking_observation
        self.advisories: list[Observation] = advisories or []

    @property
    def has_advisories(self) -> bool:
        return len(self.advisories) > 0


class PreCheckEngine:
    """
    Runs the appropriate pre-flight checks for a given GitActionPlan.

    Returns a PreCheckResult indicating:
      - Whether the action can proceed (passed=True)
      - Any blocking failure and its observation
      - Any advisory warnings that should be shown to the user
    """

    def run(self, plan: "GitActionPlan", cwd: str) -> PreCheckResult:
        checks = ACTION_PRE_CHECKS.get(plan.action, BASE_CHECKS)
        advisories: list[Observation] = []

        for check_fn in checks:
            result = check_fn(plan, cwd)

            if result is None:
                # Check passed cleanly
                continue

            if result.success:
                # Advisory — show to user but don't block
                advisories.append(result)
            else:
                # Blocking failure — stop here
                return PreCheckResult(
                    passed=False,
                    blocking_observation=result,
                    advisories=advisories,
                )

        return PreCheckResult(passed=True, advisories=advisories)
