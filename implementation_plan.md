# AI-Native Git & Bitbucket Assistant — Phase 1 Deep Design Document

> **Ground rule:** We do not write a single line of code until EVERY section below is aligned on and no doubts remain.

---

## 1. Project Intent (Why We're Building This)

You are building a terminal-first AI agent whose **sole purpose is reducing developer workflow friction**. Not to write code, not to fix bugs — just to eliminate the ceremony of:
- Remembering git commands
- Switching between the terminal and the Bitbucket browser UI
- Copy-pasting errors into ChatGPT
- Manually filling PR descriptions and RCA fields

The end experience should feel like talking to a very knowledgeable teammate sitting next to you in the terminal.

---

## 2. Tech Stack — Final Decisions

### 2.1 Language: Python ✅
Python is the correct choice here. It has:
- Best-in-class libraries for terminal UI (`Rich`, `Typer`)
- Excellent LLM SDKs
- `subprocess` for git orchestration
- Strong ecosystem for future Bitbucket REST API, Jira, etc.
There is no better language for this tool.

### 2.2 Package Manager: Why `uv` and not `pip`?

You asked: *"what does this `uv` package manager mean? why not pip?"*

**Why does a package manager exist at all?**
When you write Python code, you rely on third-party libraries (like `rich`, `typer`, `google-generativeai`). Those libraries themselves depend on other libraries. Without a package manager, installing and tracking all of these manually becomes chaos. `pip` is the default Python package manager.

**Why `uv` instead of `pip`?**
| Feature | `pip` + `venv` | `uv` |
|---|---|---|
| Speed | Slow — pip is written in Python | **10–100x faster** — written in Rust |
| Env management | Manual (two steps: create venv, then activate) | One command (`uv venv`, `uv run`) |
| Lock files | Needs separate `pip-tools` | Built-in (`uv.lock`) |
| Reproducibility | OK | Excellent — same exact packages always |
| Industry direction | Legacy | Modern standard (2024+) |

For a real-world tool we plan to distribute, `uv` is the right call. It will make setup, development, and future distribution much cleaner. You won't feel the difference in daily usage — it just works faster and more reliably.

### 2.3 LLM: Google Gemini ✅

Since you have a Gemini Pro subscription, we will use:
- **`gemini-2.0-flash`** as the default model for the Intent Parser.

**Why Flash over Pro?**
- Intent parsing is a **simple structured extraction task**, not reasoning. Flash is fast, cheap, and more than capable of reliably converting `"create a branch from main called fix-login"` → a JSON object.
- Pro-level intelligence is reserved for heavier tasks (Phase 3: generating PR descriptions from diffs, generating RCA summaries).

We will use the **Google `google-generativeai` Python SDK** and enable **Structured Output mode** (Gemini's native JSON mode), which guarantees the model returns a Pydantic-compatible object every time.

---

## 3. The Layered Capability Architecture

This is the central design of the entire system. Based on your feedback and the expert advice in your chat history, we are adopting a **Layered Capability Architecture** — not fully rigid, not fully autonomous, but a controlled hybrid.

```
Layer 3 — Controlled Freeform (escape hatch for power users, needs confirmation)
Layer 2 — AI Planner (LLM chains multiple Layer 1 actions for complex intents)
Layer 1 — Safe Deterministic Tools (the core atomic actions; what gets executed)
```

This is exactly how production AI agents like Claude Code and OpenHands are built internally: the LLM "reasons" but can only "act" through approved tool calls.

---

## 4. Complete System Architecture (Phase 1)

### 4.1 End-to-End Data Flow

```
User Types Nat. Language
         |
         v
  [CLI Entrypoint]              # Captures input, shows spinner, renders output (Typer + Rich)
         |
         v
  [Intent Parser]               # Gemini Flash → converts English → GitActionPlan (Pydantic JSON)
         |
         v
  [Pre-Check Engine]            # Validates state BEFORE execution (pre-flight checks)
         |
         v
  [Execution Engine / Router]   # Routes GitActionPlan → correct Tool method
         |
         v
  [Tool Registry]               # The catalog of all supported git operations
    ├── GitManager               # Executes subprocess git commands
    └── (Future) BitbucketManager
         |
         v
  [Observation Collector]       # Captures stdout, stderr, return codes
         |
         v
  [Response Synthesizer]        # Feeds raw output BACK to Gemini → generates human response
         |
         v
  [CLI Output Layer]            # Renders final natural language response to user (Rich)
```

**Key insight from your feedback:** The user is interacting in natural language. Therefore, both **input** and **output** must be natural language. The raw `stderr` of a git command is NEVER shown directly. It gets fed back to Gemini, which synthesizes a clear, human-readable explanation with options.

### 4.2 Why JSON? What Problem Does It Solve?

You asked: *"why JSON? what does it solve for us? what's the standard practice?"*

The LLM is a text-in, text-out system. Without a contract, it might say:
- *"Sure! I'll create a branch called fix-login from main for you!"* (unparseable as a command)
- Or sometimes: `git checkout -b fix-login main` (a raw shell string — dangerous to blindly execute)

**JSON solves the "contract" problem.** We force the model to always output a machine-readable structured object:
```json
{
  "action": "create_branch",
  "branch_name": "fix-login",
  "base_branch": "main",
  "auto_fetch": true
}
```
Our code reads this JSON, validates it with Pydantic, and hands it to the Execution Engine. The Execution Engine doesn't care how the user phrased the request — it only sees the clean JSON.

This is the **standard practice** in all production AI systems (OpenAI function calling, Gemini structured outputs, Anthropic tool use). The LLM fills in a predefined "form" rather than generating free text.

### 4.3 The "Unknown Intent" Response

You said: *"the response shouldn't be hardcoded, it should be generated."*

100% correct. When the LLM detects that the user's intent doesn't map to any known git action (e.g., "what's the weather?"), it outputs:
```json
{
  "action": "unknown",
  "user_message": "I'm only able to help with Git and Bitbucket tasks right now. It sounds like you're asking about the weather — that's outside my scope. Try asking me things like 'create a branch from main' or 'show me the git diff'."
}
```
The `user_message` field is generated by the LLM itself in context. It is never hardcoded. The CLI just renders whatever is in that field.

---

## 5. Error Handling: The Two-Layer Policy System

You proposed a two-layer approach and you were exactly right. Here is the formalized version:

### 5.1 Layer A: Pre-Check Policy (Proactive, Before Execution)

Before the Execution Engine runs any tool, the Pre-Check Engine runs a checklist of conditions known to be relevant to that specific action. This prevents predictable failures.

| Action | Pre-Checks Run |
|---|---|
| `checkout_branch` | Is the working tree dirty? Are there uncommitted changes? |
| `create_branch` | Does the branch name already exist locally? Remotely? |
| `commit` | Are there any staged files? Is the working directory clean? |
| `push` | Is the current branch tracking a remote? Does the remote exist? |
| `merge` | Is there an active merge conflict already? |

**Decision on undeterminism:** If the pre-check finds a conflict, the agent does **not** proceed automatically. It presents the situation and options to the user first. The level of autonomy is calibrated by risk:
- **Low risk** (e.g., `git status` before branching): Done silently, automatically.
- **Medium risk** (e.g., fetching before branch creation): Done automatically but logged/shown to user.
- **High risk** (e.g., "you have uncommitted changes"): Agent STOPS and asks the user what to do.

**On your `git fetch` question:** When creating a branch from a base, we will automatically run `git fetch origin <base_branch>` by default. This is standard practice. If the user explicitly says "create branch from my local develop" or "don't fetch first", the Intent Parser captures that preference and the pre-check is skipped. Otherwise, always fetch. Fetching is non-destructive.

### 5.2 Layer B: Reactive Feedback Loop (After Execution Fails)

If a command fails despite pre-checks (unexpected errors do happen), the raw `stderr` is NOT shown to the user. Instead:

1. `subprocess` returns a non-zero exit code + `stderr` string
2. The **Observation Collector** packages this into a structured failure object
3. This is fed BACK to Gemini as context: *"The command `git checkout main` failed with this error: `error: Your local changes to 'auth.py' would be overwritten by checkout.`"*
4. Gemini synthesizes a human response with context + options:
   > "Switching to `main` would overwrite your unsaved changes in `auth.py`. Here's what you can do:
   > - **Stash** your changes (`ai stash my changes`) — saves them for later
   > - **Commit** your changes first (`ai commit my current work`)
   > - **Discard** your changes — WARNING: this is permanent
   > What would you like to do?"
5. User replies in natural language, and the cycle continues.

This is a **multi-turn agentic loop**, and it's what makes the tool feel intelligent vs. a simple command wrapper.

---

## 6. The Tool Registry: Flexible, Expandable Git Support

### 6.1 How Many Git Commands to Support?

You found the right data: ~15–25 commands cover real-world daily work. We will support all of them in Phase 1 and Phase 2. Here is the target list, organized by risk level:

**Safe (Green — execute immediately):**
- `git status`, `git log`, `git diff`, `git branch -a`, `git remote -v`

**Standard (Yellow — execute with pre-checks):**
- `git checkout`, `git switch`, `git fetch`, `git pull`, `git add`, `git commit`, `git push`, `git clone`, `git stash`, `git restore`

**Destructive (Red — ALWAYS require explicit user confirmation):**
- `git reset`, `git rebase`, `git merge`, `git cherry-pick`, `git stash drop`, `git branch -d`

### 6.2 The Tool Registry Pattern (For Flexibility & Extensibility)

You asked: *"how are we going to make a structure so that this is flexible, expandable, maintainable?"*

We will use the **Tool Registry Pattern**. Instead of a giant `if/elif` chain, each git action is a self-contained class that registers itself. Adding a new action never requires touching existing code.

```python
# Conceptual design — not final code yet

class GitTool:
    """Base class for all git tools. Every tool self-describes its schema."""
    action_name: str          # e.g. "create_branch"
    risk_level: str           # "green" | "yellow" | "red"
    pre_checks: list          # list of pre-check functions to run
    description: str          # human-readable description

class CreateBranchTool(GitTool):
    action_name = "create_branch"
    risk_level = "yellow"
    pre_checks = [check_branch_exists, check_uncommitted_changes]

class HardResetTool(GitTool):
    action_name = "hard_reset"
    risk_level = "red"        # will trigger mandatory confirmation dialog
    pre_checks = [warn_data_loss]

# Registry — all tools in one place
TOOL_REGISTRY = {
    "create_branch": CreateBranchTool,
    "checkout_branch": CheckoutBranchTool,
    "git_status": GitStatusTool,
    # ... adding a new tool = add one class + register it here
}
```

This gives us:
- **Extensibility:** New tools = new classes, zero changes to existing code
- **Testability:** Each tool is independently testable
- **Safety by design:** Risk level is baked into the tool definition, not scattered across `if` statements
- **Auto-documentation:** The registry can generate a `help` page automatically

### 6.3 `subprocess` Reliability — Your Concerns Addressed

You asked: *"is subprocess reliable? Will it encounter issues like env var conflicts or permission issues?"*

`subprocess` is the right call, and here's why it's reliable for our use case:

| Concern | How We Handle It |
|---|---|
| Environment variable conflicts | We always pass `env=os.environ.copy()` to subprocess, inheriting the user's actual shell environment, including PATH. |
| Git not found | We run a startup check: `git --version`. If git isn't in PATH, we exit with a clear error immediately. |
| Permission issues | These are surfaced from git's stderr and handled by Layer B (Reactive Feedback Loop). |
| Windows vs. macOS/Linux path differences | We use `pathlib` for all file paths and let `subprocess` handle the shell differences. |
| Hanging commands (e.g., `git fetch` taking forever) | We set a `timeout` parameter on all subprocess calls. If exceeded, we kill the process and inform the user. |

`subprocess` is used in production by major tools including `pip`, `poetry`, `poetry`, and GitHub CLI internals. It is battle-tested for this exact use case.

---

## 7. Production-Grade Project Structure

You said: *"I'm trying to make a real tool here, not a toy."*

Here is the production-grade folder structure:

```
git-ai/                              # Root of the project
│
├── pyproject.toml                   # Project metadata, dependencies (uv-managed)
├── uv.lock                          # Locked dependency tree (committed to git)
├── README.md
├── .env.example                     # Template: GEMINI_API_KEY=...
│
├── src/
│   └── swij/                       # Core Python package
│       │
│       ├── __init__.py
│       ├── main.py                  # CLI entrypoint (Typer app)
│       │
│       ├── core/
│       │   ├── __init__.py
│       │   ├── agent.py             # The main agentic loop (orchestrates all layers)
│       │   ├── intent_parser.py     # Gemini structured output → GitActionPlan
│       │   ├── pre_check_engine.py  # Pre-flight validation logic
│       │   ├── execution_engine.py  # Routes JSON → Tool in registry
│       │   ├── observation.py       # Captures subprocess results (stdout/stderr/code)
│       │   └── response_synthesizer.py  # Feeds failure/success to Gemini → natural language
│       │
│       ├── tools/
│       │   ├── __init__.py
│       │   ├── base.py              # GitTool base class + TOOL_REGISTRY
│       │   ├── branch_tools.py      # create_branch, checkout_branch, list_branches
│       │   ├── commit_tools.py      # git_add, git_commit, git_stash
│       │   ├── remote_tools.py      # git_push, git_pull, git_fetch, git_clone
│       │   ├── inspection_tools.py  # git_status, git_diff, git_log
│       │   └── destructive_tools.py # git_reset, git_merge (with mandatory confirmation)
│       │
│       ├── schemas/
│       │   ├── __init__.py
│       │   └── actions.py           # All Pydantic models for GitActionPlan
│       │
│       ├── ui/
│       │   ├── __init__.py
│       │   ├── renderer.py          # Rich console: spinners, panels, confirmations
│       │   └── prompts.py           # Confirmation dialogs ("Are you sure? y/n")
│       │
│       └── config/
│           ├── __init__.py
│           └── settings.py          # Reads .env, validates API keys at startup
│
└── tests/
    ├── unit/
    │   ├── test_intent_parser.py
    │   └── test_pre_check_engine.py
    └── integration/
        └── test_git_manager.py      # Runs against a temp git repo
```

**Why this structure?**
- `src/swij/` layout is the industry standard for distributable Python packages. You can later run `pip install git-ai` with this.
- `tools/` is organized by domain, not by function. Easy to navigate, easy to add new commands.
- `schemas/` are separate so both the parser and the engine can import them without circular imports.
- `tests/` are first-class citizens — not an afterthought.

---

## 8. The Complete Pydantic Schema (Phase 1)

```python
# src/swij/schemas/actions.py  (Conceptual — for review, not final code)

from pydantic import BaseModel, Field
from typing import Optional, Literal, List

# All possible actions in Phase 1
ActionType = Literal[
    # Inspection
    "git_status", "git_diff", "git_log", "list_branches",
    # Branching
    "create_branch", "checkout_branch", "delete_branch",
    # Staging & Committing
    "git_add", "git_commit", "git_stash", "git_stash_pop",
    # Remote
    "git_fetch", "git_pull", "git_push", "git_clone",
    # Destructive (requires confirmation)
    "git_reset", "git_restore",
    # Multi-step compound (Layer 2 planner)
    "create_branch_workflow",  # fetch + create + checkout in one go
    # Fallback
    "unknown"
]

class GitActionPlan(BaseModel):
    """The structured output the LLM always produces."""
    action: ActionType
    # Branch params
    branch_name: Optional[str] = Field(None, description="Target or new branch name")
    base_branch: Optional[str] = Field(None, description="Base branch to branch off from")
    # Commit params
    commit_message: Optional[str] = Field(None, description="Commit message if provided")
    files_to_add: Optional[List[str]] = Field(None, description="Specific files to stage. None means all.")
    # Remote params
    remote_url: Optional[str] = Field(None, description="Remote URL for clone")
    # Intent flags
    auto_fetch: bool = Field(True, description="Should we fetch before branching?")
    needs_confirmation: bool = Field(False, description="LLM sets true if action seems risky")
    # Unknown intent
    user_message: Optional[str] = Field(None, description="Human message from LLM for unknown/error states")
    # Confidence
    confidence: float = Field(1.0, description="LLM confidence in this interpretation, 0.0–1.0")
```

**Note on `confidence`:** If the user says something ambiguous (e.g., `"make a new thing from develop"`), the LLM sets `confidence: 0.6`. Below a threshold (say 0.75), the agent asks for clarification rather than proceeding. This directly addresses your point about handling undeterminism.

---

## 9. Open Questions / Remaining Doubts

> [!IMPORTANT]
> These are the remaining decisions that need your input before we finalize this design completely.

### Q1: Agentic Loop — How many turns?
For multi-step flows (e.g., user says "start work on login bug" which requires fetch + create branch + checkout), should the agent execute all steps in a single shot and show a summary at the end? Or should it pause between each step to show progress and ask "okay to continue"? 

My recommendation: **show progress in real-time** (Rich progress steps) but only pause for confirmation on risky steps. Your thoughts?

### Q2: Stale Branch Warning
When you run `git fetch` before branching and we find that your local `develop` is 15 commits behind the remote, should the agent:
- (A) Automatically pull to update your local `develop` before branching
- (B) Warn you but leave the decision to you
- (C) Always just branch off whatever is there locally

### Q3: Commit Scope in Phase 1
In Phase 1, the basic commit feature is `ai "commit my changes as 'fix login timeout'"`. Should we also support `ai "commit only the auth.py file"` in Phase 1? (This requires the `files_to_add` field which is already in the schema.)

### Q4: Tool Name & Command
What do you want to type in the terminal to invoke the tool? Options:
- `ai "create a branch from main"`
- `gai "create a branch from main"`  (git-ai)
- `flow "create a branch from main"`
- Something else?

This is more important than it sounds — it determines how the tool is installed and invoked.

---

Once you answer these four questions, the design is locked. We start coding.
