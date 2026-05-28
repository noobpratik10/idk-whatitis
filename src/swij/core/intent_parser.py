"""
core/intent_parser.py
=====================
Converts natural language input into a structured GitActionPlan using
Gemini's native Pydantic structured output (google-genai SDK).

Design decisions
----------------
- We use google.genai (the current, supported SDK — NOT google-generativeai which is EOL).
- Pydantic model is passed directly as response_schema → the SDK returns `.parsed`.
- Flash is used: intent parsing is a cheap extraction task, not heavy reasoning.
- Below the configured confidence threshold, we return the plan and let the
  agent layer ask for clarification.
"""

from __future__ import annotations

from typing import Optional

from google import genai
from google.genai import types

from swij.config.settings import get_confidence_threshold, get_gemini_api_key, get_gemini_model
from swij.schemas.actions import GitActionPlan

# ---------------------------------------------------------------------------
# System prompt — defines the LLM's role, output contract, and edge cases
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are the Intent Parser for swij, an AI-native Git assistant.

Your ONLY job is to convert a developer's natural language input into a
structured JSON object that matches the GitActionPlan schema.

## Rules

1. ALWAYS return valid JSON matching the schema. Never return prose outside JSON.
2. Set `action` to the most specific matching action from the allowed list.
3. If the intent maps to NO known git action, set `action: "unknown"` and write
   a helpful, natural-language explanation in `user_message` that tells the user
   what swij CAN help with.
4. Set `confidence` to a float 0.0–1.0. Use lower values when the user's intent
   is ambiguous or could be interpreted multiple ways.
5. For destructive actions (reset, restore, merge, rebase, cherry-pick), set
   `needs_confirmation: true`.
6. When the user says "from my local ..." or "don't fetch", set `auto_fetch: false`.
7. Extract file paths, branch names, commit messages, and refs as accurately as
   possible from the user's words.
8. Do NOT infer or invent values the user didn't specify — leave optional fields
   as null if not present in the input.

## Allowed actions

Inspection (safe): git_status, git_diff, git_log, list_branches, git_remote
Branching: create_branch, checkout_branch, delete_branch
Staging/Committing: git_add, git_commit, git_stash, git_stash_pop
Remote: git_fetch, git_pull, git_push, git_clone
Destructive: git_reset, git_restore, git_merge, git_rebase, git_cherry_pick
Compound: create_branch_workflow, commit_and_push_workflow
Fallback: unknown

## Examples

Input: "show me what changed"
Output: {"action":"git_diff","confidence":0.95}

Input: "create a branch from develop called fix-payment-retry"
Output: {"action":"create_branch","branch_name":"fix-payment-retry","base_branch":"develop","auto_fetch":true,"confidence":1.0}

Input: "commit only src/auth.py with message 'fix token validation'"
Output: {"action":"git_commit","files_to_add":["src/auth.py"],"commit_message":"fix token validation","confidence":1.0}

Input: "hard reset to 3 commits ago"
Output: {"action":"git_reset","reset_mode":"hard","reset_target":"HEAD~3","needs_confirmation":true,"confidence":0.95}

Input: "what's the weather today?"
Output: {"action":"unknown","user_message":"I only help with Git and Bitbucket tasks. I can't check the weather, but I can help you with things like 'show git status', 'create a branch', or 'push my changes'.","confidence":1.0}
"""


# ---------------------------------------------------------------------------
# Parser class
# ---------------------------------------------------------------------------

class IntentParser:
    """
    Converts a raw user string into a validated GitActionPlan.

    Usage
    -----
    parser = IntentParser()
    plan = parser.parse("create a branch from main called hotfix-login")
    """

    def __init__(self) -> None:
        self._client = genai.Client(api_key=get_gemini_api_key())
        self._model_name = get_gemini_model()
        self._confidence_threshold = get_confidence_threshold()

    def parse(self, user_input: str, context: Optional[str] = None) -> GitActionPlan:
        """
        Parse a user's natural language input into a GitActionPlan.

        Parameters
        ----------
        user_input : str
            The raw text typed by the user.
        context : str, optional
            Additional context to inject (e.g. current branch, dirty status).

        Returns
        -------
        GitActionPlan — always returns a valid plan (may be action='unknown')
        """
        prompt = user_input
        if context:
            prompt = f"[Context: {context}]\n\nUser said: {user_input}"

        try:
            response = self._client.models.generate_content(
                model=self._model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    response_mime_type="application/json",
                    response_schema=GitActionPlan,
                    temperature=0.1,  # low temp for consistent extraction
                ),
            )

            # New SDK returns a `.parsed` property when response_schema is a Pydantic model
            if response.parsed is not None:
                return response.parsed  # type: ignore[return-value]

            # Fallback: parse from text if .parsed is None for any reason
            import json
            data = json.loads(response.text)
            return GitActionPlan.model_validate(data)

        except Exception as exc:
            # Catch all (JSON errors, validation errors, API errors)
            # Unknown action is always safe — the agent will ask for clarification
            return GitActionPlan(
                action="unknown",
                user_message=(
                    "I had trouble understanding that request. Could you rephrase it?\n"
                    f"(Error: {type(exc).__name__}: {exc})"
                ),
                confidence=0.0,
            )

    def parse_with_repo_context(
        self,
        user_input: str,
        current_branch: Optional[str] = None,
        is_dirty: bool = False,
        staged_files: Optional[list[str]] = None,
    ) -> GitActionPlan:
        """
        Parse with automatic repo-state context injection.
        Gives the LLM better information about the current situation.
        """
        context_parts = []
        if current_branch:
            context_parts.append(f"current branch: {current_branch}")
        if is_dirty:
            context_parts.append("working tree has uncommitted changes")
        if staged_files:
            context_parts.append(f"staged files: {', '.join(staged_files)}")

        context = "; ".join(context_parts) if context_parts else None
        return self.parse(user_input, context=context)
