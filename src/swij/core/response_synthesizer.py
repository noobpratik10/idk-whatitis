"""
core/response_synthesizer.py
============================
Feeds subprocess results back to Gemini to generate natural-language responses.
Uses the new google.genai SDK (google-generativeai is EOL).

The golden rule: the user NEVER sees raw git output or stderr.
Everything is translated by Gemini into clear, actionable language.
"""

from __future__ import annotations

from google import genai
from google.genai import types

from swij.config.settings import get_gemini_api_key, get_gemini_model
from swij.core.observation import MultiObservation, Observation
from swij.schemas.actions import GitActionPlan

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYNTHESIZER_SYSTEM_PROMPT = """\
You are the Response Synthesizer for swij, an AI-native Git assistant.

You receive:
1. The user's original natural language request
2. The structured action plan that was parsed from it
3. The raw output of the git command(s) that were executed

Your job is to convert this raw data into a clear, friendly, conversational response
that a developer would find immediately useful.

## Rules

1. NEVER show raw git output verbatim unless it is naturally readable (e.g. git log --oneline).
2. For SUCCESS: summarize what happened, highlight key information.
3. For FAILURE: explain what went wrong in plain English, then offer 2-3 specific options
   for how the user can fix it (use swij-style commands where appropriate).
4. For destructive operation failures: be extra clear about what was NOT changed.
5. Be concise — developers are busy. Use bullet points for multiple options.
6. Use markdown formatting lightly — bold for key terms, code backticks for file/branch names.
7. If the output is empty or the operation made no visible change, say so clearly.
8. Format branch names, file paths, and commit SHAs in backticks.
9. Speak in second person ("you", "your branch").
10. Do not start with phrases like "Certainly!" or "Of course!" — just answer directly.
"""


# ---------------------------------------------------------------------------
# Synthesizer class
# ---------------------------------------------------------------------------

class ResponseSynthesizer:
    """
    Uses Gemini to convert raw subprocess observations into human-readable
    natural language responses.
    """

    def __init__(self) -> None:
        self._client = genai.Client(api_key=get_gemini_api_key())
        self._model_name = get_gemini_model()

    def _generate(self, prompt: str, temperature: float = 0.4) -> str:
        """Shared generation call with error fallback."""
        try:
            response = self._client.models.generate_content(
                model=self._model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=SYNTHESIZER_SYSTEM_PROMPT,
                    temperature=temperature,
                ),
            )
            return response.text.strip()
        except Exception:
            return None  # type: ignore[return-value]

    def synthesize(
        self,
        plan: GitActionPlan,
        observation: Observation | MultiObservation,
        user_input: str,
    ) -> str:
        """Generate a natural language response for the user."""
        prompt = "\n".join([
            f"User request: {user_input}",
            f"Action taken: {plan.action}",
            "",
            "Execution result:",
            observation.to_llm_context(),
        ])

        result = self._generate(prompt)
        if result:
            return result

        # Fallback
        if isinstance(observation, MultiObservation):
            return "✓ Done." if observation.success else self._fallback_error(observation)
        return "✓ Done." if observation.success else self._fallback_error(observation)

    def synthesize_pre_check_failure(
        self,
        plan: GitActionPlan,
        blocking_obs: Observation,
        user_input: str,
    ) -> str:
        """Synthesize a response for a blocking pre-check failure."""
        prompt = (
            f"User request: {user_input}\n\n"
            f"Planned action: {plan.action}\n\n"
            f"Pre-flight check failed:\n{blocking_obs.to_llm_context()}\n\n"
            "Explain why the operation cannot proceed right now, and suggest "
            "what the user should do. Be specific and helpful."
        )
        return self._generate(prompt) or blocking_obs.stderr

    def synthesize_advisory(
        self,
        plan: GitActionPlan,
        advisory: Observation,
        user_input: str,
    ) -> str:
        """Synthesize a short advisory warning to show before proceeding."""
        prompt = (
            f"User request: {user_input}\n\n"
            f"Planned action: {plan.action}\n\n"
            f"Advisory finding:\n{advisory.to_llm_context()}\n\n"
            "Write a concise warning (1-3 sentences) and ask if the user wants "
            "to proceed or take the recommended action instead."
        )
        return self._generate(prompt) or advisory.stderr

    @staticmethod
    def _fallback_error(obs: Observation | MultiObservation) -> str:
        if isinstance(obs, MultiObservation):
            failed = obs.failed_step
            stderr = failed.stderr if failed else "Unknown error"
        else:
            stderr = obs.stderr
        return f"✗ The operation failed.\n\nRaw error: {stderr}"
