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

---

## 10. Phase 2: True Agentic Loop — ReAct Architecture

> This section defines the architectural upgrade from the current **linear single-pass pipeline** to a **proper tool-calling agent loop** (the industry standard). This is what will allow swij to answer questions like *"suggest a commit message"*, *"why is my push failing?"*, and *"what changed in the last 5 commits that touched auth files?"*

---

### 10.1 Why the Current Architecture Cannot Do This

The current pipeline in `agent.py` is a straight line:

```
User Input → IntentParser → PreCheckEngine → ExecutionEngine → ResponseSynthesizer → Output
              (decides ONCE)                  (runs ONE command)
```

**The core flaw:** The `IntentParser` must classify the request into a pre-known action *before* gathering any context. If the request does not map to a known git verb (e.g., *"suggest a commit message"*), it returns `action: "unknown"` and the pipeline terminates immediately — before any git command is ever run. The `ResponseSynthesizer` never gets a chance to help because it only runs *after* a successful execution.

**The result:** The tool can only do things in its fixed vocabulary list. Anything that requires "think first, then decide what to run" is impossible.

---

### 10.2 The Industry Standard: ReAct + Native Tool Calling

The industry-standard solution is called **ReAct (Reason + Act)**. It is the pattern used internally by:
- **Claude Code** (Anthropic)
- **Cursor** (AI code editor)
- **OpenHands** (open-source AI dev agent)
- **GitHub Copilot Workspace**

The idea: instead of the LLM deciding everything upfront, you give it a **loop** where it can call tools on demand to gather context before responding.

```
User Input
    │
    ▼
┌──────────────────────────────────────────────────────┐
│                    AGENT LOOP                        │
│                                                      │
│  1. Think: "What do I need to answer this?"          │
│       │                                              │
│  2. Act: Call a tool (git_diff, git_log, git_status) │
│       │                                              │
│  3. Observe: Read tool output                        │
│       │                                              │
│  4. "Do I have enough?" ──No──► (back to Step 1)     │
│       │ Yes                                          │
└───────┼──────────────────────────────────────────────┘
        │
        ▼
   Synthesize Final Response → Output to user
```

**For the commit message example**, the agent loop does:
1. Think: *"User wants a commit message. I need to see the changes."*
2. Act: Call `git_diff` tool.
3. Observe: Gets the full diff.
4. Think: *"Now I have the context. I can write the message."*
5. Respond: Returns a well-crafted, context-aware commit message.

Zero hallucination. Zero made-up data. The model only responds based on real git output it actually ran.

---

### 10.3 How We Implement This in swij (Gemini Native Function Calling)

Gemini's API has **native function calling / tool use** built in. This is the right implementation path — we define our git commands as `FunctionDeclaration` objects, and Gemini decides when to call them and chains them automatically.

**High-level flow change:**

```python
# CURRENT (linear):
plan  = intent_parser.parse(user_input)      # LLM call 1 — classifies
obs   = execution_engine.execute(plan, cwd)  # runs one subprocess
resp  = synthesizer.synthesize(obs)          # LLM call 2 — formats output

# PROPOSED (agentic loop):
agent_loop.run(user_input, cwd)
# ↳ Internally: LLM decides which tools to call → tools run → LLM reads
#   output → LLM decides to call more tools OR respond → final output
```

**What changes structurally:**

| Component | Current Role | After ReAct |
|---|---|---|
| `IntentParser` | Classify intent into fixed schema | **Removed** — LLM decides tool calls natively |
| `ExecutionEngine` | Route JSON plan → subprocess | **Becomes a tool executor** — runs whichever function the LLM requests |
| `ResponseSynthesizer` | Second LLM call for formatting | **Merged into the agent loop** — the loop's final response IS the synthesized output |
| `agent.py` | Orchestrate the linear steps | **Becomes the ReAct loop driver** |

**The Tool Definitions (new concept):**

Each git command becomes a `FunctionDeclaration` that the LLM can request:

```python
# Conceptual — not final code

from google.genai import types

SWIJ_TOOLS = [
    types.FunctionDeclaration(
        name="git_status",
        description="Get the current status of the git repository. Shows staged, unstaged, and untracked files.",
        parameters={},  # no params needed
    ),
    types.FunctionDeclaration(
        name="git_diff",
        description="Show the diff of uncommitted changes. Use this to understand what was changed before writing a commit message.",
        parameters={
            "staged": {"type": "boolean", "description": "If true, show staged changes. If false, show unstaged."},
            "file_path": {"type": "string", "description": "Optional specific file path to diff."},
        },
    ),
    types.FunctionDeclaration(
        name="git_log",
        description="Show recent commit history.",
        parameters={
            "count": {"type": "integer", "description": "Number of commits to show. Default 10."},
        },
    ),
    types.FunctionDeclaration(
        name="git_commit",
        description="Stage all changes and commit with a message. ALWAYS ask for confirmation before running this.",
        parameters={
            "message": {"type": "string", "description": "The commit message."},
            "files": {"type": "array", "description": "Specific files to stage. Empty means all."},
        },
    ),
    # ... all other git tools
]
```

The LLM sends back a `function_call` response, we run the subprocess, return the output, and the loop continues.

---

### 10.4 Hallucination Prevention — The Most Important Problem

> This is the core challenge. An LLM that can call tools freely could:
> - Invent git commands that don't exist
> - Make up file paths or branch names
> - Run the wrong command and enter an infinite retry loop
> - Never stop calling tools and run forever

Here is the multi-layer defense system:

#### Layer 1: Closed Tool Vocabulary (The Most Important Guard)

**The LLM can ONLY call functions we explicitly define.** It cannot invent a tool called `git_deploy` or `run_script`. The Gemini API enforces this at the API level — if the model tries to call a function not in our `SWIJ_TOOLS` list, the API rejects it. This alone eliminates 90% of hallucination risk.

```python
# The model is FORCED to pick from our list. No free-form shell access.
response = client.models.generate_content(
    model=model_name,
    contents=conversation_history,
    config=types.GenerateContentConfig(
        tools=SWIJ_TOOLS,
        tool_choice="auto",  # LLM decides when to call tools
        system_instruction=AGENT_SYSTEM_PROMPT,
    )
)
```

#### Layer 2: Hard Turn Limit (Anti-Infinite-Loop Guard)

The loop **must have a maximum number of iterations**. If the agent hasn't produced a final answer after N tool calls, it terminates and tells the user.

```python
MAX_TOOL_CALLS = 8  # Tunable constant

for turn in range(MAX_TOOL_CALLS):
    response = call_llm(conversation_history)
    if response.is_final_text:   # model returned text, not a tool call
        break
    tool_result = run_tool(response.function_call)
    conversation_history.append(tool_result)
else:
    # Exceeded max turns — tell the user and stop
    renderer.print_error("I needed too many steps to answer this. Please rephrase.")
```

This makes it **impossible** for the loop to run forever.

#### Layer 3: Destructive Action Guard (Confirmation Required)

The system prompt explicitly instructs the LLM that any tool marked as destructive (`git_reset`, `git_merge`, `git_rebase`, `git_cherry_pick`) **must not be called** until the user has explicitly confirmed. The tool definitions themselves also include a `requires_confirmation: true` metadata field.

Before executing any destructive function call from the LLM, our loop checks this flag and stops to ask the user — exactly like the current `pre_check_engine` does.

#### Layer 4: Grounded System Prompt (Anti-Scope-Creep Guard)

The agent system prompt is strict and explicit:

```
You are swij, an AI git assistant. You can ONLY help with git and Bitbucket tasks.
You have access to a set of git tools. Use them to gather the information you need
before responding.

Rules:
- NEVER make up branch names, file names, or commit SHAs. Only use names you have
  seen in actual tool output.
- NEVER call a tool more than twice with the same parameters. If a command fails
  twice, explain the failure and stop.
- NEVER call destructive tools without explicit user confirmation in your response.
- If you cannot answer using only git tools, say so clearly.
- When you have enough information, respond in plain English. Do not keep calling tools.
```

This prompt acts as the LLM's "conscience" — it explicitly forbids the most common hallucination patterns.

#### Layer 5: Observation Validation (Anti-Bad-Data Guard)

Every tool call result is validated before being fed back to the LLM:
- Non-zero exit codes are flagged as failures with the stderr message.
- Timeouts are caught and surfaced as tool errors.
- Empty output is explicitly labeled as `"(no output)"` — not an empty string, which the LLM might try to re-run.

This ensures the LLM always receives structured, honest observations, not ambiguous empty responses it might misinterpret.

#### Summary: The 5-Layer Hallucination Shield

| Layer | Mechanism | Guards Against |
|---|---|---|
| 1 | Closed tool vocabulary | LLM inventing commands |
| 2 | Hard turn limit (MAX=8) | Infinite loops |
| 3 | Destructive action confirmation gate | Unsafe auto-execution |
| 4 | Strict system prompt rules | Scope creep, making up names |
| 5 | Observation validation | Bad/empty data misinterpretation |

---

### 10.5 Migration Plan: Current Code → ReAct Loop

We do **not** throw away the current code. We migrate incrementally:

**Step 1:** Keep the current linear pipeline working as-is (fallback).

**Step 2:** Add a new `ReactAgent` class alongside the existing `Agent`. Route only "advisory" requests (ones that return `unknown`) to the new ReAct loop first.

**Step 3:** Once ReAct is stable, make it the default for all requests and retire the `IntentParser` + `ExecutionEngine` as separate classes (their logic moves into tool definitions).

**Files that change:**
- `core/agent.py` — Add `ReactAgent` class with the loop
- `core/tools/` — New folder. Each git tool becomes a `FunctionDeclaration` + a Python function that runs the subprocess
- `core/intent_parser.py` — Eventually deprecated; the LLM decides natively
- `core/execution_engine.py` — Logic moves into individual tool functions

**Files that stay the same:**
- `ui/renderer.py` — No change
- `config/settings.py` — No change
- `schemas/actions.py` — Can be kept for internal type hints

---

### 10.6 Final Decisions (Locked)

All open questions are answered. Locked decisions:

| Question | Decision |
|---|---|
| `MAX_TOOL_CALLS` | Configurable via `SWIJ_MAX_TOOL_CALLS` env var (default: 8) — added to `settings.py` alongside existing vars |
| Simple vs complex requests | `IntentParser` stays for simple known actions. Only `unknown` intents are escalated to the ReAct loop. No redundant loops for simple commands. |
| New classes vs. modifying agent | **Modify `agent.py` directly** — add the ReAct path inside the existing `Agent` class. No new classes. |
| Retiring old classes | Nothing retired. `IntentParser`, `ExecutionEngine`, `PreCheckEngine`, `ResponseSynthesizer` all stay. The ReAct loop uses the existing tool classes from `TOOL_REGISTRY` for execution. |
| Read vs. write tool access | **Read tools (green) run freely.** Write/destructive tools always pause and ask for confirmation before executing. |
| Memory across invocations | **No cross-invocation memory** for now. Each `swij "..."` call is stateless. |
| Turn limit exceeded | Tell the user: *"This request needed too many steps. Please break it down."* |
| Tool call verbosity | **Dynamic spinner**: update spinner text to show the current tool being called (e.g. `→ running git diff…`). No separate step list. |

---

### 10.7 Precise Execution Plan

> [!IMPORTANT]
> This is the exact set of file changes to implement. Minimal edits, no bloat, no unnecessary rewrites.

#### File 1: `config/settings.py` — ADD one accessor
Add `get_max_tool_calls()` reading `SWIJ_MAX_TOOL_CALLS` env var (default `8`).

#### File 2: `core/agent.py` — MODIFY the `_process` method
When `plan.action == "unknown"`, instead of showing a clarification panel, route into the new **ReAct path** inside the same `Agent` class:
```
_react_loop(user_input, cwd)  # new private method on Agent
```
All other actions keep the existing linear pipeline exactly as-is.

The `_react_loop` method:
1. Builds `FunctionDeclaration` objects from the existing `TOOL_REGISTRY` (read-only tools only, at first).
2. Runs the Gemini `generate_content` call in a `for turn in range(max_tool_calls)` loop.
3. On each `function_call` response: update spinner text → run the tool via `TOOL_REGISTRY` → append result to conversation history.
4. On `function_call` for write tools: pause → ask user to confirm → run or cancel.
5. On `text` response: break → render the final answer via `renderer.print_response`.
6. On loop exhaustion: `renderer.print_clarification_request("This needed too many steps…")`.

#### File 3: `core/response_synthesizer.py` — NO CHANGE
Used only by the existing linear path. The ReAct loop's final LLM text response is rendered directly.

#### File 4: `tools/base.py` — ADD two class attributes to `GitTool`
Add `llm_description: str` and `llm_parameters: dict` class attributes. These provide the text for `FunctionDeclaration` so the tool self-describes to the LLM, staying consistent with the Tool Registry Pattern.

#### File 5: Each tool file — ADD the two new attributes
`inspection_tools.py`, `branch_tools.py`, `commit_tools.py`, `remote_tools.py`, `destructive_tools.py` — each tool class gets `llm_description` and `llm_parameters` filled in.

#### Nothing else changes.
`pre_check_engine.py`, `observation.py`, `schemas/actions.py`, `ui/renderer.py`, `main.py`, `config/settings.py` (except the one accessor) — all untouched.

