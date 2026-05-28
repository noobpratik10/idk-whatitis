"""
tests/unit/test_pre_check_engine.py
====================================
Unit tests for the PreCheckEngine and individual pre-check functions.

These tests use a temporary git repository (via tmp_path fixture) so they
run real git commands without touching any actual repository.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from swij.core.pre_check_engine import (
    PreCheckEngine,
    check_branch_exists_locally,
    check_git_installed,
    check_is_git_repo,
    check_nothing_staged,
    check_remote_exists,
    check_stash_exists,
    check_uncommitted_changes,
)
from swij.schemas.actions import GitActionPlan


# ---------------------------------------------------------------------------
# Fixtures: temporary git repos
# ---------------------------------------------------------------------------

@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """Create a minimal initialized git repo with one commit."""
    subprocess.run(["git", "init", "--initial-branch=main"], cwd=tmp_path, check=True,
                   capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp_path,
                   capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path,
                   capture_output=True)

    # Create an initial commit so HEAD exists
    (tmp_path / "README.md").write_text("# Test repo")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "initial commit"],
        cwd=tmp_path, check=True, capture_output=True,
    )
    return tmp_path


@pytest.fixture
def dirty_repo(git_repo: Path) -> Path:
    """A repo with an uncommitted change to a tracked file."""
    # Modify an already-tracked file so git stash captures it
    (git_repo / "README.md").write_text("# Test repo — dirty")
    return git_repo


@pytest.fixture
def staged_repo(git_repo: Path) -> Path:
    """A repo with a staged (but not committed) file."""
    (git_repo / "staged.txt").write_text("staged content")
    subprocess.run(["git", "add", "staged.txt"], cwd=git_repo, check=True,
                   capture_output=True)
    return git_repo


# ---------------------------------------------------------------------------
# Tests: check_git_installed
# ---------------------------------------------------------------------------

def test_check_git_installed_passes(git_repo):
    plan = GitActionPlan(action="git_status")
    result = check_git_installed(plan, str(git_repo))
    assert result is None  # None = check passed


# ---------------------------------------------------------------------------
# Tests: check_is_git_repo
# ---------------------------------------------------------------------------

def test_check_is_git_repo_passes(git_repo):
    plan = GitActionPlan(action="git_status")
    result = check_is_git_repo(plan, str(git_repo))
    assert result is None


def test_check_is_git_repo_fails_outside_repo(tmp_path):
    plan = GitActionPlan(action="git_status")
    result = check_is_git_repo(plan, str(tmp_path))
    assert result is not None
    assert result.success is False


# ---------------------------------------------------------------------------
# Tests: check_uncommitted_changes
# ---------------------------------------------------------------------------

def test_check_uncommitted_changes_clean_repo(git_repo):
    plan = GitActionPlan(action="checkout_branch")
    result = check_uncommitted_changes(plan, str(git_repo))
    assert result is None  # clean repo passes


def test_check_uncommitted_changes_dirty_repo(dirty_repo):
    plan = GitActionPlan(action="checkout_branch")
    result = check_uncommitted_changes(plan, str(dirty_repo))
    assert result is not None
    assert result.success is False
    assert "uncommitted" in result.stderr.lower()


# ---------------------------------------------------------------------------
# Tests: check_branch_exists_locally
# ---------------------------------------------------------------------------

def test_check_branch_exists_fails_when_duplicate(git_repo):
    # main already exists
    plan = GitActionPlan(action="create_branch", branch_name="main")
    result = check_branch_exists_locally(plan, str(git_repo))
    assert result is not None
    assert result.success is False
    assert "already exists" in result.stderr


def test_check_branch_exists_passes_for_new_branch(git_repo):
    plan = GitActionPlan(action="create_branch", branch_name="feature-new")
    result = check_branch_exists_locally(plan, str(git_repo))
    assert result is None  # branch doesn't exist yet


def test_check_branch_exists_skips_when_no_name(git_repo):
    plan = GitActionPlan(action="create_branch")  # no branch_name
    result = check_branch_exists_locally(plan, str(git_repo))
    assert result is None  # no name to check


# ---------------------------------------------------------------------------
# Tests: check_nothing_staged
# ---------------------------------------------------------------------------

def test_check_nothing_staged_fails_when_clean(git_repo):
    plan = GitActionPlan(action="git_commit")
    result = check_nothing_staged(plan, str(git_repo))
    assert result is not None
    assert result.success is False
    assert "staged" in result.stderr.lower()


def test_check_nothing_staged_passes_when_staged(staged_repo):
    plan = GitActionPlan(action="git_commit")
    result = check_nothing_staged(plan, str(staged_repo))
    assert result is None  # something is staged


# ---------------------------------------------------------------------------
# Tests: check_stash_exists
# ---------------------------------------------------------------------------

def test_check_stash_exists_fails_when_empty(git_repo):
    plan = GitActionPlan(action="git_stash_pop")
    result = check_stash_exists(plan, str(git_repo))
    assert result is not None
    assert result.success is False


def test_check_stash_exists_passes_when_stash_present(dirty_repo):
    # First stash the dirty changes
    subprocess.run(["git", "stash", "push"], cwd=dirty_repo, check=True,
                   capture_output=True)
    plan = GitActionPlan(action="git_stash_pop")
    result = check_stash_exists(plan, str(dirty_repo))
    assert result is None  # stash exists


# ---------------------------------------------------------------------------
# Tests: check_remote_exists
# ---------------------------------------------------------------------------

def test_check_remote_exists_fails_when_no_remote(git_repo):
    plan = GitActionPlan(action="git_push")
    result = check_remote_exists(plan, str(git_repo))
    assert result is not None
    assert result.success is False


# ---------------------------------------------------------------------------
# Tests: PreCheckEngine
# ---------------------------------------------------------------------------

def test_engine_passes_for_git_status(git_repo):
    engine = PreCheckEngine()
    plan = GitActionPlan(action="git_status")
    result = engine.run(plan, str(git_repo))
    assert result.passed is True
    assert result.blocking_observation is None


def test_engine_blocks_commit_with_nothing_staged(git_repo):
    engine = PreCheckEngine()
    plan = GitActionPlan(action="git_commit", commit_message="my commit")
    result = engine.run(plan, str(git_repo))
    assert result.passed is False
    assert result.blocking_observation is not None


def test_engine_passes_commit_with_staged_files(staged_repo):
    engine = PreCheckEngine()
    plan = GitActionPlan(action="git_commit", commit_message="add staged")
    result = engine.run(plan, str(staged_repo))
    assert result.passed is True


def test_engine_blocks_checkout_with_dirty_tree(dirty_repo):
    engine = PreCheckEngine()
    plan = GitActionPlan(action="checkout_branch", branch_name="main")
    result = engine.run(plan, str(dirty_repo))
    assert result.passed is False
