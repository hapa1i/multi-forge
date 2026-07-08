# End-User Guides

How to use Forge features. Each guide is self-contained; start here for the overview.

## Why Launch Through Forge?

Running `claude` directly works, but you lose session tracking. Forge wraps Claude Code to add:

- **Session tracking** -- named sessions with artifacts, plans, and transcripts
- **Session resume** -- structured or AI-curated transfer when context fills up
- **Hook-driven capture** -- plan snapshots, transcript archival on exit
- **Status line** -- proxy, session, and policy info in the Claude UI
- **Policy enforcement** -- TDD, coding standards, semantic supervisor
- **Search** -- `forge search` across past sessions
- **Memory writer** -- auto-updates project docs on session exit

These features require launching through Forge because they depend on a Forge-managed session's launch environment,
hooks being wired, and the session manifest existing. Running `claude` directly bypasses all of this.

**You don't need a proxy to benefit.** `forge session start` defaults to direct mode (Anthropic API), giving you
everything above without any proxy setup.

## The "Day 1" Workflow

Forge is a global CLI. Install it once (below), then follow the per-session steps A--F.

### Install Forge (once)

```bash
uv tool install multi-forge     # recommended -- puts `forge` on your PATH
# or: pipx install multi-forge

forge extension doctor          # confirm install kind + PATH reachability
```

A global tool keeps `forge` on `PATH` for every shell and the hooks launched from one, avoiding the "activate a project
venv first" trap. Claude launched from the Dock or an IDE inherits a minimal `PATH` that can still miss bare `forge` --
`forge extension doctor` reports that case as `on_path_minimal`. Contributors working on Forge itself use an editable
install instead (`uv sync`); see [CONTRIBUTING.md](../../CONTRIBUTING.md).

### A. Install extensions

```bash
forge extension enable --scope user    # Install runtime hooks once
forge extension enable                 # Set up this project (.forge/, status line, project assets)
```

### B. Launch Claude

The simplest path -- no proxy, no API key setup needed (uses your existing Claude subscription):

```bash
forge session start
```

This creates a managed Forge session (auto-named), launches Claude, and gives you session tracking, hooks, and the
status line.

### C. (Optional) Add multi-model routing

If you want to route through other providers (Gemini, GPT, etc.):

```bash
# Store your credentials (API keys + connection values)
forge auth login

# Create a proxy (OpenRouter direct, no LiteLLM needed)
forge proxy create openrouter-anthropic

# Verify upstream connectivity (optional, recommended on first setup)
forge proxy start openrouter-anthropic --smoke-test

# Launch with proxy routing
forge session start --proxy openrouter-anthropic
```

See [proxy.md](proxy.md) for templates, tier mappings, and per-tier hyperparameter tuning. See
[authentication.md](authentication.md#which-auth-do-i-need) for which credentials each workflow needs.

### D. Resume when context fills up

```bash
# AI-selected highlights (best for long sessions)
forge session resume my-feature --fresh --strategy ai-curated

# Structured skeleton (faster, no LLM call)
forge session resume my-feature --fresh --strategy structured

# Lossless: carry full conversation (lost on /compact)
forge session resume my-feature --fresh --resume-mode native
```

### E. Optional: Enable large context windows

When routing through a proxy, Forge sets `CLAUDE_CODE_AUTO_COMPACT_WINDOW` to match the routed model's context window.
No patching required.

### F. Store credentials

```bash
forge auth login               # Prompt for API keys, store in ~/.forge/credentials.yaml
forge auth status              # Show where each credential comes from (env, file, missing)
```

See [authentication.md](authentication.md) for profiles and credential resolution.

## Feature Guides

### Sessions -- Named Work Units

`forge session start` creates a managed Forge session (1:1 with the Claude process). Sessions track intent, artifacts,
and confirmed state:

```bash
forge session start                                            # Auto-named, direct to Anthropic
forge session start quick-fix                                  # Named, direct to Anthropic
forge session start my-feature --proxy openrouter-anthropic    # With proxy routing
forge session resume my-feature                                # Reattach to conversation
forge session show my-feature                                  # Session details
```

See [session.md](session.md) for worktrees, fork, incognito, and `%` commands. See [transfer.md](transfer.md) for the
`forge session transfer` group (inspect and reshape resume context) and the cross-runtime workflow (plan in Claude,
implement in Codex).

### Policies -- Code Quality Gates

Enable TDD enforcement, coding standards checks, or a semantic supervisor that verifies alignment with your plan:

```bash
forge policy enable --bundle tdd                        # Deterministic TDD policy
forge policy supervisor set planner                     # Semantic plan supervision
forge session fork planner --name executor --supervise # Wire at fork time
forge policy supervisor off                             # Suspend (preserves config)
forge policy supervisor on                              # Resume
forge policy supervisor reload                          # Reload plan after changes
```

See [policy.md](policy.md).

### Skills -- Review, Understand, Panel

Skills teach Claude how to compose Forge capabilities. Model family is auto-detected from session context:

```bash
/forge:review src/forge/session/           # code review
/forge:review-docs docs/design.md          # document review
/forge:understand src/forge/core/ops/      # explain code structure
/forge:panel src/forge/session/ --code     # multi-model code review
```

See [skills.md](skills.md).

### Workflows -- Multi-Model CLI Engine

The CLI engine behind skills. Fan out reviews to multiple models, get adversarial debate, or deep analysis:

```bash
forge workflow panel src/forge/session/ --code
forge workflow debate "Should we rewrite the core in Rust?"
forge workflow analyze "What are the failure modes of the memory writer?"
```

See [workflow.md](workflow.md).

### Model Selection -- Choosing Models for Each Role

Forge templates default per role, not per "newest available." The supervisor judges what the executor produced — and
those are different jobs that reward different capabilities. The same provider's flagship release can be the right pick
for one role and the wrong pick for another:

```bash
# Planner/supervisor source on the proxy default (Opus 4.8)
forge session start planner --proxy openrouter-anthropic

# Executor pinned to the top-tier Fable 5, checked against the planner by a read-only supervisor
forge session start exec --proxy openrouter-anthropic --model claude-fable-5 --supervise planner
```

See [model_selection.md](model_selection.md) for per-role recommendations, the structural reasons context fidelity
varies across model versions, cost optimization order, and a release-validation checklist.

### Hooks -- Lifecycle & Artifacts

Forge hooks capture session artifacts (plans, transcripts) and enforce policies at tool-use boundaries. Installed
automatically by `forge extension enable`.

See [hook.md](hook.md).

### Memory Writer -- Automatic Memory Docs

The memory writer is queued at session end and runs on the next Forge CLI startup to update designated project docs
(checklists, changelogs, pattern files) based on what happened in the session.

See [memory.md](memory.md).

### Search -- Transcript Search

Search across past session transcripts:

```bash
forge search query "proxy routing bug"
forge search rebuild-index
```

See [search.md](search.md).

### Configuration

Runtime preferences live in `~/.forge/config.yaml`. Claude Code settings customizations live in
`~/.forge/claude.preset.json`:

```bash
forge config show
forge config set context_limit=1000000
forge claude preset edit
```

See [config.md](config.md).

### Verification -- Installation Testing

Three tiers of verification:

| Skill                | What it does                        |
| -------------------- | ----------------------------------- |
| `/forge:smoke-test`  | Read-only health check (30 seconds) |
| `/forge:walkthrough` | Interactive feature tour (hermetic) |
| `/forge:qa`          | Full Docker-based QA                |

See [manual_testing.md](manual_testing.md).
