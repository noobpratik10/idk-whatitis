# swij

> Your AI-native terminal teammate for Git & Bitbucket.

**swij** (named after Swati + Jitendra) is a terminal-first AI agent that eliminates workflow friction — no more memorizing git commands, copy-pasting errors into ChatGPT, or switching to browser UIs.

## Usage

```bash
swij "create a branch from develop called fix-payment-retry"
swij "what did I change?"
swij "commit only src/auth.py with message 'fix token validation'"
swij "push my changes"
swij "show me the last 5 commits"
```

## Installation

### Prerequisites
- Python 3.11+
- [uv](https://docs.astral.sh/uv/) package manager
- A [Google Gemini API key](https://aistudio.google.com/)

### Setup

```bash
# Clone the repo
git clone <repo-url>
cd swij

# Install dependencies
uv sync

# Configure your API key
cp .env.example .env
# Edit .env and add your GEMINI_API_KEY

# Run it
uv run swij "show git status"
```

### Install globally (once packaged)

```bash
uv tool install swij
```

## Architecture

swij uses a **Layered Capability Architecture**:

```
Layer 3 — Controlled Freeform (escape hatch for power users)
Layer 2 — AI Planner (LLM chains multiple actions for complex intents)
Layer 1 — Safe Deterministic Tools (atomic git operations)
```

The user types natural language → Gemini parses it into a structured JSON action plan → validated pre-checks run → the right tool executes → Gemini synthesizes the result back into natural language.

**Errors are never shown raw.** Every stderr output is fed back to Gemini, which explains what went wrong and offers options.

## Supported Actions

**Safe (immediate execution):** `git status`, `git log`, `git diff`, `list branches`

**Standard (with pre-checks):** `checkout`, `switch`, `fetch`, `pull`, `add`, `commit`, `push`, `stash`

**Destructive (requires confirmation):** `reset`, `merge`, `branch delete`

## License

MIT
