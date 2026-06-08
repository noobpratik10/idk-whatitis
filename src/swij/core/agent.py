"""
core/agent.py
=============
The main agentic loop that orchestrates all layers of swij.

Data flow — known actions (happy path):
  User input
    → IntentParser    (English → GitActionPlan)
    → PreCheckEngine  (pre-flight validation)
    → Confirmation    (if red-level or advisory)
    → ExecutionEngine (GitActionPlan → subprocess)
    → ResponseSynthesizer (raw output → natural language)
    → Renderer        (display to user)

Data flow — open-ended questions (ReAct path):
  User input
    → IntentParser    (returns action='unknown')
    → ReactLoop       (Gemini native function calling)
        → tool calls resolved via TOOL_REGISTRY
        → confirmation gate for yellow/red tools
        → final text response rendered directly
    → Renderer        (display to user)

Ctrl+C handling:
  - Caught cleanly at the top level
  - Displays what completed vs. what didn't
  - Repository is never left in an unknown state without the user knowing
"""

from __future__ import annotations

import os
import subprocess
from typing import Optional

from google import genai
from google.genai import types

from swij.config.settings import (
    get_confidence_threshold,
    get_gemini_api_key,
    get_gemini_model,
    get_max_tool_calls,
)
from swij.core.execution_engine import ExecutionEngine
from swij.core.intent_parser import IntentParser
from swij.core.observation import MultiObservation, Observation
from swij.core.pre_check_engine import PreCheckEngine
from swij.core.response_synthesizer import ResponseSynthesizer
from swij.schemas.actions import GitActionPlan
from swij.ui import renderer

# ---------------------------------------------------------------------------
# ReAct agent system prompt
# ---------------------------------------------------------------------------

_REACT_SYSTEM_PROMPT = """\
You are swij, an AI git assistant running in the user's terminal.
You have access to a set of git tools. Use them to gather information and take actions.

## Rules — follow these strictly

1. ONLY use the tools provided. Never invent tool names.
2. NEVER make up branch names, file names, or commit SHAs. Only use values you have
   seen in actual tool output.
3. NEVER call a tool more than twice with identical parameters. If a tool fails twice,
   stop and explain the failure clearly.
4. Before calling any write or destructive tool (non-read operations), you MUST first
   tell the user what you are about to do and why. The system will ask for confirmation.
5. When you have enough information to answer, respond in plain English using markdown.
   Do not keep calling tools once you can answer.
6. If you cannot help with something using only git tools, say so directly.
7. Be concise. Developers are busy.
"""


class Agent:
    """
    The main swij agent. Instantiate once per invocation.

    Usage
    -----
    agent = Agent()
    agent.run("create a branch from develop called fix-login")
    """

    def __init__(self) -> None:
        self._parser = IntentParser()
        self._pre_check = PreCheckEngine()
        self._engine = ExecutionEngine()
        self._synthesizer = ResponseSynthesizer()
        self._confidence_threshold = get_confidence_threshold()
        self._max_tool_calls = get_max_tool_calls()
        self._gemini_client = genai.Client(api_key=get_gemini_api_key())
        self._model_name = get_gemini_model()

    def run(self, user_input: str) -> None:
        """
        Process a single user request end-to-end.
        This is the top-level entry point called from main.py.
        """
        cwd = os.getcwd()

        try:
            self._process(user_input, cwd)
        except KeyboardInterrupt:
            renderer.print_interrupted(completed_steps=[])
        except RuntimeError as exc:
            renderer.print_error(str(exc))

    # ── Core pipeline ─────────────────────────────────────────────────────

    def _process(self, user_input: str, cwd: str) -> None:
        """Inner pipeline — can raise KeyboardInterrupt and RuntimeError."""

        # ── Step 1: Parse intent ──────────────────────────────────────────
        with renderer.thinking("Parsing your request…"):
            repo_context = self._get_repo_context(cwd)
            plan = self._parser.parse(user_input, context=repo_context)

        # ── Step 2: Handle unknown intent → escalate to ReAct loop ────────
        if plan.action == "unknown":
            self._react_loop(user_input, cwd)
            return

        # ── Step 3: Handle low confidence ─────────────────────────────────
        if plan.confidence < self._confidence_threshold:
            message = plan.user_message or (
                f"I interpreted your request as **{plan.action}** but I'm not confident "
                f"(confidence: {plan.confidence:.0%}). Could you be more specific?"
            )
            renderer.print_clarification_request(message)
            return

        # ── Step 4: Run pre-checks ────────────────────────────────────────
        with renderer.thinking("Running pre-flight checks…"):
            check_result = self._pre_check.run(plan, cwd)

        # ── Step 5: Handle blocking pre-check failure ─────────────────────
        if not check_result.passed:
            with renderer.thinking("Analyzing the issue…"):
                message = self._synthesizer.synthesize_pre_check_failure(
                    plan,
                    check_result.blocking_observation,  # type: ignore[arg-type]
                    user_input,
                )
            renderer.print_error(message)
            return

        # ── Step 6: Handle advisories (stale branch, dirty tree warnings) ─
        for advisory in check_result.advisories:
            # Special case: stale branch advisory → ask if user wants to pull
            if "behind" in advisory.stderr and plan.base_branch:
                commits_behind = advisory.stdout or "some"
                remote = plan.remote_name or "origin"
                should_pull = renderer.confirm_stale_branch(
                    plan.base_branch, commits_behind, remote
                )
                if should_pull:
                    self._pull_base_branch(plan, cwd)
            else:
                # Generic advisory — synthesize and ask to confirm
                with renderer.thinking("Preparing advisory…"):
                    advisory_message = self._synthesizer.synthesize_advisory(
                        plan, advisory, user_input
                    )
                should_proceed = renderer.confirm_advisory(advisory_message)
                if not should_proceed:
                    renderer.print_success("Cancelled. No changes were made.")
                    return

        # ── Step 7: Confirm destructive operations ────────────────────────
        if plan.is_destructive or plan.needs_confirmation:
            details = self._build_confirmation_details(plan)
            confirmed = renderer.confirm_destructive(plan.action, details)
            if not confirmed:
                renderer.print_success("Cancelled. No changes were made.")
                return

        # ── Step 8: Execute ───────────────────────────────────────────────
        completed_steps: list[str] = []
        try:
            with renderer.thinking(f"Running {plan.action}…"):
                observation = self._engine.execute(plan, cwd)

            if isinstance(observation, MultiObservation):
                for step_obs in observation.steps:
                    if step_obs.success:
                        completed_steps.append(" ".join(step_obs.command))

        except KeyboardInterrupt:
            renderer.print_interrupted(completed_steps=completed_steps)
            return

        # ── Step 9: Synthesize response ───────────────────────────────────
        with renderer.thinking("Preparing response…"):
            response = self._synthesizer.synthesize(plan, observation, user_input)

        renderer.print_response(response, action=plan.action)

    # ── ReAct loop ─────────────────────────────────────────────────────────

    def _react_loop(self, user_input: str, cwd: str) -> None:
        """
        ReAct (Reason + Act) agent loop using Gemini native function calling.

        Triggered when IntentParser cannot map the request to a known git action.
        Gives Gemini access to all registered tools and lets it call them as needed
        to gather context and produce a final natural-language answer.

        Safety guarantees:
        - Closed tool vocabulary: only TOOL_REGISTRY tools are exposed
        - Hard turn limit: loop stops after MAX_TOOL_CALLS iterations
        - Confirmation gate: yellow/red tools always ask the user before running
        - Grounded system prompt: anti-hallucination rules baked in
        """
        from swij.tools.base import TOOL_REGISTRY

        tool_declarations = TOOL_REGISTRY.function_declarations()
        if not tool_declarations:
            renderer.print_clarification_request(
                "I couldn't understand that request. "
                "Try something like 'show git status' or 'create a branch'."
            )
            return

        gemini_tools = [types.Tool(function_declarations=tool_declarations)]

        # Seed conversation history with the user's message
        conversation: list = [
            types.Content(role="user", parts=[types.Part(text=user_input)]),
        ]

        try:
            with renderer.thinking("Thinking…") as status:
                for _turn in range(self._max_tool_calls):
                    response = self._gemini_client.models.generate_content(
                        model=self._model_name,
                        contents=conversation,
                        config=types.GenerateContentConfig(
                            system_instruction=_REACT_SYSTEM_PROMPT,
                            tools=gemini_tools,
                            temperature=0.3,
                        ),
                    )

                    candidate = response.candidates[0] if response.candidates else None
                    if candidate is None:
                        break

                    parts = candidate.content.parts or []
                    function_calls = [p.function_call for p in parts if getattr(p, "function_call", None)]
                    text_parts = [p.text for p in parts if getattr(p, "text", None)]

                    if not function_calls:
                        # Model returned a final text answer — render and exit
                        final_text = "\n".join(text_parts).strip()
                        if final_text:
                            renderer.print_response(final_text)
                        return

                    # Model wants to call tools — process each call
                    tool_response_parts = []
                    for fc in function_calls:
                        tool_name = fc.name
                        tool_args = dict(fc.args) if fc.args else {}

                        # Update spinner to show which tool is being called
                        status.update(
                            f"[swij.info]→ running {tool_name}…[/swij.info]"
                        )

                        tool_cls = TOOL_REGISTRY.get(tool_name)
                        if tool_cls is None:
                            result_text = f"Error: tool '{tool_name}' is not registered."
                        else:
                            risk = tool_cls.risk_level

                            # Confirmation gate for write/destructive tools
                            if risk in ("yellow", "red"):
                                confirmed = renderer.confirm_destructive(
                                    action=tool_name,
                                    details=(
                                        f"The assistant wants to run **{tool_name}**"
                                        + (f" with: `{tool_args}`" if tool_args else "")
                                    ),
                                )
                                if not confirmed:
                                    result_text = (
                                        "User declined this action. Do not retry it."
                                    )
                                    tool_response_parts.append(
                                        types.Part(
                                            function_response=types.FunctionResponse(
                                                name=tool_name,
                                                response={"output": result_text},
                                            )
                                        )
                                    )
                                    continue

                            obs = self._run_tool_from_args(
                                tool_cls, tool_name, tool_args, cwd
                            )
                            result_text = (
                                obs.stdout if obs.success
                                else f"FAILED (exit {obs.returncode}): {obs.stderr}"
                            )
                            if not result_text:
                                result_text = "(no output)"

                        tool_response_parts.append(
                            types.Part(
                                function_response=types.FunctionResponse(
                                    name=tool_name,
                                    response={"output": result_text},
                                )
                            )
                        )

                    # Append model turn + all tool responses to conversation
                    conversation.append(candidate.content)
                    conversation.append(
                        types.Content(role="user", parts=tool_response_parts)
                    )

                else:
                    # Loop exhausted without final text response
                    renderer.print_clarification_request(
                        "This request needed too many steps to answer. "
                        "Please try breaking it into smaller, more specific questions."
                    )

        except KeyboardInterrupt:
            renderer.print_interrupted(completed_steps=[])

    def _run_tool_from_args(
        self,
        tool_cls: type,
        tool_name: str,
        args: dict,
        cwd: str,
    ) -> Observation:
        """
        Construct a minimal GitActionPlan from the LLM's function call args
        and execute the tool. Maps common arg names to GitActionPlan fields.
        """
        plan_kwargs: dict = {"action": tool_name}  # type: ignore[assignment]

        # Map common LLM-supplied argument names to GitActionPlan fields
        field_map = {
            "branch_name": "branch_name",
            "base_branch": "base_branch",
            "message":     "commit_message",
            "commit":      "reset_target",
            "target":      "reset_target",
            "mode":        "reset_mode",
            "files":       "files_to_add",
            "url":         "remote_url",
            "directory":   "target_directory",
            "remote":      "remote_name",
            "branch":      "branch_name",
            "force":       "force",
            "staged":      "diff_staged",
            "file_path":   "diff_target",
            "count":       "log_count",
        }
        for arg_key, plan_field in field_map.items():
            if arg_key in args:
                plan_kwargs[plan_field] = args[arg_key]

        # files_to_add must be a list, not a comma-string
        if "files_to_add" in plan_kwargs and isinstance(plan_kwargs["files_to_add"], str):
            plan_kwargs["files_to_add"] = [
                f.strip() for f in plan_kwargs["files_to_add"].split(",") if f.strip()
            ]

        plan = GitActionPlan(**plan_kwargs)
        tool = tool_cls()
        return tool.execute(plan, cwd)

    # ── Helpers ───────────────────────────────────────────────────────────

    def _get_repo_context(self, cwd: str) -> Optional[str]:
        """
        Gather current repo state to give the LLM better context.
        Runs silently — failures are non-fatal.
        """
        parts = []
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=cwd, capture_output=True, text=True, timeout=5,
                env=os.environ.copy(),
            )
            if result.returncode == 0:
                parts.append(f"current branch: {result.stdout.strip()}")

            result2 = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=cwd, capture_output=True, text=True, timeout=5,
                env=os.environ.copy(),
            )
            if result2.returncode == 0 and result2.stdout.strip():
                parts.append("working tree has uncommitted changes")

        except Exception:
            pass  # context is optional

        return "; ".join(parts) if parts else None

    def _pull_base_branch(self, plan: GitActionPlan, cwd: str) -> None:
        """Pull the base branch before branching."""
        base = plan.base_branch
        remote = plan.remote_name or "origin"
        with renderer.thinking(f"Pulling {remote}/{base}…"):
            result = subprocess.run(
                ["git", "pull", remote, base],
                cwd=cwd, capture_output=True, text=True, timeout=30,
                env=os.environ.copy(),
            )
        if result.returncode == 0:
            renderer.print_success(f"Pulled latest `{base}` from `{remote}`.")
        else:
            renderer.print_warning(
                f"Pull of `{base}` failed. Continuing with your current local state."
            )

    def _build_confirmation_details(self, plan: GitActionPlan) -> str:
        """Build a human-readable detail string for the confirmation dialog."""
        parts = []
        if plan.action == "git_reset":
            mode = plan.reset_mode or "mixed"
            target = plan.reset_target or "HEAD~1"
            parts.append(f"Reset mode: **{mode}**")
            parts.append(f"Reset target: `{target}`")
            if mode == "hard":
                parts.append("\n⚠ **Hard reset will permanently discard uncommitted changes.**")
        elif plan.action == "delete_branch":
            parts.append(f"Branch to delete: `{plan.branch_name}`")
        elif plan.action == "git_merge":
            parts.append(f"Merging `{plan.branch_name}` into current branch.")
        elif plan.action == "git_rebase":
            parts.append(f"Rebasing current branch onto `{plan.base_branch or plan.branch_name}`.")
        elif plan.action == "git_restore":
            if plan.files_to_add:
                parts.append(f"Files to restore: `{'`, `'.join(plan.files_to_add)}`")
            else:
                parts.append("All tracked files will be restored (all local changes discarded).")
        elif plan.action == "git_cherry_pick":
            parts.append(f"Commit to cherry-pick: `{plan.reset_target}`")

        return "\n".join(parts) if parts else f"Action: `{plan.action}`"
