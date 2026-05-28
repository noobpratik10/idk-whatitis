"""
schemas/actions.py
==================
Pydantic models that define the contract between the Intent Parser (LLM) and
the Execution Engine.  The LLM always outputs a GitActionPlan — never raw text.

This module is intentionally kept free of business logic so it can be imported
by both the parser and the engine without any risk of circular imports.
"""

from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Action type literal — every supported git action in Phase 1
# ---------------------------------------------------------------------------

ActionType = Literal[
    # ── Inspection (safe / green) ──────────────────────────────────────────
    "git_status",
    "git_diff",
    "git_log",
    "list_branches",
    "git_remote",
    # ── Branching (yellow — pre-checks required) ───────────────────────────
    "create_branch",
    "checkout_branch",
    "delete_branch",
    # ── Staging & Committing (yellow) ──────────────────────────────────────
    "git_add",
    "git_commit",
    "git_stash",
    "git_stash_pop",
    # ── Remote (yellow) ───────────────────────────────────────────────────
    "git_fetch",
    "git_pull",
    "git_push",
    "git_clone",
    # ── Destructive (red — ALWAYS require explicit confirmation) ───────────
    "git_reset",
    "git_restore",
    "git_merge",
    "git_rebase",
    "git_cherry_pick",
    # ── Compound / multi-step (Layer 2 planner) ────────────────────────────
    "create_branch_workflow",   # fetch + create + checkout in one go
    "commit_and_push_workflow", # add + commit + push in one go
    # ── Fallback ──────────────────────────────────────────────────────────
    "unknown",
]


# ---------------------------------------------------------------------------
# Risk level — drives confirmation and pre-check behaviour
# ---------------------------------------------------------------------------

RiskLevel = Literal["green", "yellow", "red"]

ACTION_RISK_MAP: dict[str, RiskLevel] = {
    "git_status": "green",
    "git_diff": "green",
    "git_log": "green",
    "list_branches": "green",
    "git_remote": "green",
    "create_branch": "yellow",
    "checkout_branch": "yellow",
    "delete_branch": "red",
    "git_add": "yellow",
    "git_commit": "yellow",
    "git_stash": "yellow",
    "git_stash_pop": "yellow",
    "git_fetch": "yellow",
    "git_pull": "yellow",
    "git_push": "yellow",
    "git_clone": "yellow",
    "git_reset": "red",
    "git_restore": "red",
    "git_merge": "red",
    "git_rebase": "red",
    "git_cherry_pick": "red",
    "create_branch_workflow": "yellow",
    "commit_and_push_workflow": "yellow",
    "unknown": "green",
}


# ---------------------------------------------------------------------------
# The main contract model
# ---------------------------------------------------------------------------

class GitActionPlan(BaseModel):
    """
    The structured output the LLM always produces.

    The Intent Parser instructs Gemini to always return JSON matching this
    schema.  Pydantic validates the response before it reaches the engine.
    """

    # Core ─────────────────────────────────────────────────────────────────
    action: ActionType = Field(..., description="The git action to execute")

    # Branch parameters ────────────────────────────────────────────────────
    branch_name: Optional[str] = Field(
        None, description="Target or new branch name"
    )
    base_branch: Optional[str] = Field(
        None, description="Base branch to branch off from (e.g. 'main', 'develop')"
    )

    # Commit / staging parameters ──────────────────────────────────────────
    commit_message: Optional[str] = Field(
        None, description="Commit message, if explicitly provided by the user"
    )
    files_to_add: Optional[List[str]] = Field(
        None,
        description=(
            "Specific files to stage. If None or empty, defaults to 'git add .' "
            "(all tracked changes)."
        ),
    )

    # Stash parameters ─────────────────────────────────────────────────────
    stash_message: Optional[str] = Field(
        None, description="Optional message to attach to a stash"
    )

    # Remote parameters ────────────────────────────────────────────────────
    remote_url: Optional[str] = Field(
        None, description="Remote URL for clone operations"
    )
    remote_name: Optional[str] = Field(
        None,
        description="Remote name (defaults to 'origin' if not specified)",
    )
    target_directory: Optional[str] = Field(
        None, description="Local directory name for clone target"
    )

    # Reset / restore parameters ───────────────────────────────────────────
    reset_mode: Optional[Literal["soft", "mixed", "hard"]] = Field(
        None,
        description="Mode for git reset: soft, mixed, or hard",
    )
    reset_target: Optional[str] = Field(
        None,
        description="Commit ref for reset (e.g. 'HEAD~1', a SHA, a tag)",
    )

    # Log parameters ───────────────────────────────────────────────────────
    log_count: Optional[int] = Field(
        None, description="Number of commits to show in git log"
    )

    # Diff parameters ──────────────────────────────────────────────────────
    diff_target: Optional[str] = Field(
        None,
        description=(
            "Compare against this ref/file (e.g. 'main', 'HEAD~1', or a file path)"
        ),
    )
    diff_staged: bool = Field(
        False,
        description="If True, show diff of staged (cached) changes only",
    )

    # Intent flags ─────────────────────────────────────────────────────────
    auto_fetch: bool = Field(
        True,
        description=(
            "Should we automatically fetch from remote before branching? "
            "Set False if user says 'from my local ...' or 'don't fetch'."
        ),
    )
    needs_confirmation: bool = Field(
        False,
        description=(
            "Set True if the LLM believes the action is risky and explicit "
            "user confirmation is required beyond the standard risk-level check."
        ),
    )
    force: bool = Field(
        False,
        description="If True, use --force flags where applicable (e.g. force push)",
    )

    # Unknown intent ───────────────────────────────────────────────────────
    user_message: Optional[str] = Field(
        None,
        description=(
            "LLM-generated natural language message. Used when action='unknown' "
            "to explain what swij couldn't understand and suggest alternatives. "
            "Also used when needs_confirmation=True to frame the confirmation question."
        ),
    )

    # Confidence ───────────────────────────────────────────────────────────
    confidence: float = Field(
        1.0,
        ge=0.0,
        le=1.0,
        description=(
            "LLM's confidence in this interpretation (0.0–1.0). "
            "Below the configured threshold, swij asks for clarification."
        ),
    )

    # ── Helpers ───────────────────────────────────────────────────────────

    @property
    def risk_level(self) -> RiskLevel:
        return ACTION_RISK_MAP.get(self.action, "yellow")

    @property
    def is_destructive(self) -> bool:
        return self.risk_level == "red"

    @property
    def is_safe(self) -> bool:
        return self.risk_level == "green"
