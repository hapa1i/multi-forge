# Forge Workflows -- Multi-Model Review & Analysis

Run structured analysis across multiple workers. `forge workflow` provides four runners that fan out prompts through
Claude and Codex headless runtimes and collect results for synthesis.

- Canonical architecture: [`docs/design.md`](../design.md)
- Proxies (model routing): [`proxy.md`](proxy.md)
- Policies (automatic gating): [`policy.md`](policy.md)

Runtime prerequisites follow the selected workers. Claude-backed workers require `claude` on `PATH`; the opt-in `codex`
worker requires a fresh successful cached preflight. Check them from the same environment that runs the workflow:

```bash
command -v claude
forge runtime preflight codex
```

---

## Quick start

```bash
# Deep analysis on a topic (single model, default: claude-opus)
forge workflow analyze "Should we use event sourcing for the audit log?"

# Multi-model code review (default worker set: gpt-5.6-sol, gemini-3.1-pro-preview, claude-opus)
forge workflow panel src/forge/session/store.py --code

# Multi-model document review
forge workflow panel docs/design.md

# Multi-model review with custom prompt
forge workflow panel -p "Review the error handling in src/auth/"

# Adversarial debate (proposal evaluation)
forge workflow debate "Should we rewrite the core in Rust?"

# Adversarial code evaluation
forge workflow debate src/forge/cli/ --code

# Two-round consensus building
forge workflow consensus "Should we adopt gRPC for internal services?"
```

Unless you pass `-m`, the multi-model workflows use this built-in worker set:

- `gpt-5.6-sol` -- OpenRouter (preferred proxy: `openrouter-openai`)
- `gemini-3.1-pro-preview` -- OpenRouter (preferred proxy: `openrouter-gemini`)
- `claude-opus` -- direct Anthropic, pinned to Claude Opus 4.8

This default set is unchanged and entirely Claude-backed. Add `-m codex` explicitly to run the runtime-native Codex
worker. Codex selects its own model; Forge does not pass a model pin.

Routing is **capability-based**: models declare what they are (family, provider refs), and Forge derives routes at
runtime from proxy templates and credentials. The preferred proxy is a catalog hint, not a hard requirement -- any
compatible proxy found in the registry will work.

Selectable direct Claude workers include `claude-opus-4.6`, `claude-opus-4.6-1m`, `claude-opus-4.8`, and `claude-fable`
(most capable). Additional OSS models include `deepseek-v4-pro`, `minimax-m3`, `qwen3.6-max-preview`, `kimi-k2.6`, and
`glm-5.2`. Use `--proxy` to route all workers through a specific proxy:

```bash
# Route all workers through one proxy (single OPENROUTER_API_KEY setup)
forge workflow panel src/ --code -m gpt-5.6-sol,deepseek-v4-pro --proxy openrouter-openai

# Explicit direct Claude workers
forge workflow panel src/ --code -m claude-opus-4.6,claude-opus-4.8

# Runtime-native Codex worker (read-only sandbox)
forge workflow panel src/ --code -m codex

# Mixed runtime quorum
forge workflow panel src/ --code -m claude-opus,codex
```

Check which workers are locally ready with `forge workflow list-models`. Proxy/direct workers are grouped by primary
credential; runtime-native workers are grouped by runtime preflight. A Codex worker is ready only while its cached
preflight is fresh and successful. Use `--available` to see only ready workers, or `--json` for structured output that
includes each worker's `runtime`.

Use `forge model catalog` for Forge's static model capability catalog; `forge workflow list-models` is the runtime
readiness view for workflow runners.

---

## Workflows

### `forge workflow analyze`

Single-model deep analysis. Combines a structured analysis framework with your topic and sends it to one model.

```bash
forge workflow analyze "Should we split the session module?"
forge workflow analyze -p "Evaluate migration strategy" --json
forge workflow analyze "Architecture review" -m claude-opus --check
```

- First argument (or `-p`) -- topic to analyze
- `-m` -- model to use (default: `claude-opus`)
- `--check` -- gate mode: exit 0 if verdict passes, exit 1 if not

### `forge workflow panel`

Multi-model fan-out. Sends a review framework with your target to the built-in default worker set (or your explicit `-m`
selection) in parallel. Uses document review framework by default; `--code` switches to code review.

```bash
forge workflow panel docs/design.md                    # document review (default)
forge workflow panel src/forge/cli/run.py --code       # code review
forge workflow panel -p "Review the proxy architecture" # custom prompt
forge workflow panel src/ --code --roles security,architecture
forge workflow panel src/ --code --review-type security --severity high
```

- First argument -- file or directory to review (loads review framework automatically)
- `--code` -- use code review framework (default: document review)
- `-p` -- custom review prompt (overrides target+framework and --review-type)
- `--context` -- `blind` (default: fresh subprocess) or `resume:<uuid>` (fork session context)
- `-m` -- models to use (default: `gpt-5.6-sol,gemini-3.1-pro-preview,claude-opus`)
- `--roles` -- comma-separated reviewer roles (security, performance, architecture, maintainability, correctness)
- `--review-type` -- review focus: `full` (default), `security`, `performance`, `quick` (security/performance need
  --code)
- `--severity` -- minimum severity to report: `high` or `critical`
- `--check` -- gate mode: exit 0 if all models pass, exit 1 if any fail

### `forge workflow debate`

Adversarial evaluation with stance injection. Each model receives an assigned stance (for/against/neutral) and evaluates
independently -- workers are **blinded** to each other's output. Uses proposal evaluation by default; `--code` switches
to code evaluation.

```bash
forge workflow debate "Should we use event sourcing?"                    # proposal evaluation (default)
forge workflow debate src/forge/session/ --code                          # code evaluation
forge workflow debate "Evaluate the auth module" --check
forge workflow debate --worker gpt-5.6-sol:for --worker "claude-opus:Focus on security" "proposal"
```

- First argument -- subject to evaluate (proposal text, or file/directory path with `--code`)
- `--code` -- use code evaluation framework (default: proposal evaluation)
- `-p` -- custom prompt (overrides subject+framework)
- `-m` -- models to use (stances assigned cyclically: for, against, neutral)
- `--worker` -- explicit worker spec: `model:stance` or `model:"custom prompt"` (repeatable, mutually exclusive with
  `-m`)
- `--check` -- gate mode: any REJECT verdict exits 1

The CLI builds the evaluation resource internally. Proposal mode uses a 7-point evaluation framework (feasibility,
correctness, trade-offs, risks, completeness, alternatives, recommendation). Code mode uses a 5-point code evaluation
framework (quality, security, performance, architecture, risks).

### `forge workflow consensus`

Two-round multi-model convergence. Role-assigned models evaluate independently in round 1, then reconcile toward a
shared recommendation in round 2. Uses proposal evaluation by default; `--code` switches to code evaluation.

```bash
forge workflow consensus "Should we adopt gRPC for internal services?"      # proposal evaluation
forge workflow consensus src/forge/proxy/ --code                             # code evaluation
forge workflow consensus "Evaluate the caching strategy" --check
forge workflow consensus --worker gpt-5.6-sol:architect --worker claude-opus:security "proposal"
```

- First argument -- subject to evaluate (proposal text, or file/directory path with `--code`)
- `--code` -- use code evaluation framework (default: proposal evaluation)
- `-p` -- custom prompt (overrides subject+framework)
- `-m` -- models to use (roles assigned cyclically)
- `--worker` -- explicit worker spec: `model:role` (repeatable, mutually exclusive with `-m`)
- `--check` -- gate mode: exit 0 if consensus reached, exit 1 if not

---

## Shared flags

All `forge workflow` subcommands support:

| Flag       | Description                                                                                                 |
| ---------- | ----------------------------------------------------------------------------------------------------------- |
| `--json`   | Structured output including worker responses, runtime, resolved model state, routing, durations, and status |
| `--check`  | Gate mode: exit 0 if passed, exit 1 if failed (fail-closed)                                                 |
| `-m`       | Comma-separated worker names (e.g., `claude-opus,codex`)                                                    |
| `--proxy`  | Override proxy-backed workers; direct Claude and Codex workers warn and ignore it                           |
| `--effort` | Claude-worker reasoning effort only: `low`, `medium`, `high`, `xhigh`, or `max`                             |
| `-t`       | Per-worker timeout in seconds (default: 600)                                                                |
| `--cwd`    | Working directory for subprocesses                                                                          |

Single-runtime invocations use that runtime's ordinary parallel dispatcher. Mixed invocations share one global
five-child limit and one cancellation domain; output remains in requested-worker order.

---

## `--check` mode (CI gating)

`--check` evaluates each worker's output for a structured verdict and returns a policy-grade exit code:

- **Exit 0**: all workers succeeded AND emitted accepting verdicts
- **Exit 1**: at least one worker failed or emitted a rejecting verdict

Fail-closed: a worker that succeeds but emits no parseable verdict counts as a failure. This prevents silent
pass-through when models return unstructured output.

Accepted verdict values: `ACCEPT`, `ACCEPT_WITH_CONDITIONS`, `PASS`, `PASSED`, `TRUE`.

```bash
# Use in CI or as a policy gate
forge workflow panel src/critical.py --code --check && echo "Passed" || echo "Failed"
```

---

## Context modes (`panel` only)

`forge workflow panel` supports two context modes for worker subprocesses:

| Mode                      | What workers see                      | Use case                              |
| ------------------------- | ------------------------------------- | ------------------------------------- |
| `--context blind`         | Fresh subprocess, prompt + filesystem | Isolated reviews, cheap, default      |
| `--context resume:<uuid>` | Fork of session with full context     | Architecture reviews, complex changes |

`resume:<uuid>` is Claude-conversation context. Combining it with any Codex worker fails closed; use `--context blind`
for Codex or mixed runs. Other subcommands (`analyze`, `debate`, `consensus`) always run blinded.

---

## Workflows and supervision

Review workflows and the semantic supervisor (see [`policy.md`](policy.md)) answer different questions about the same
code:

| Signal         | Question                    | Perspective    |
| -------------- | --------------------------- | -------------- |
| Supervisor     | "Does this match the plan?" | Plan alignment |
| Review / panel | "Is this code good?"        | Code quality   |

These can have opposite answers — code can be plan-aligned but suboptimal, or plan-divergent but better. Use the
supervisor as the plan-alignment gate and review output as evidence for an explicit plan change or approved deviation. A
typical pattern:

1. Executor implements with supervision enabled (drift is blocked)
2. `forge workflow panel` or `forge workflow consensus` reviews the implemented code
3. Reviewers recommend improvements that weren't in the plan
4. You suspend the supervisor (`%policy supervisor off`), apply the improvement, then reload an updated plan if needed

The review provides the evidence ("frozen dataclasses would be better here"); the supervisor keeps the deviation as your
decision instead of an unapproved executor change.

---

## Troubleshooting

### "No active proxy found" or a worker fails immediately

Workflow routing is capability-based: Forge looks for a running proxy whose template matches the model's provider. The
default models prefer `openrouter-openai` and `openrouter-gemini`, but any compatible proxy will work.

```bash
# See which models are ready vs unavailable (grouped by credential)
forge workflow list-models

# Create the default proxies
forge proxy create openrouter-openai
forge proxy create openrouter-gemini

# Or route everything through one proxy
forge workflow panel src/ --code --proxy openrouter-openai

# Filter to only ready models (useful for scripting)
forge workflow list-models --available
forge workflow list-models --available --json
```

Unknown model names are rejected before execution. Models without a compatible running proxy are flagged by the
preflight check with an actionable suggestion (which proxy to create or start).

For auditability, workflow JSON includes `resolved_models` for every worker. Each entry shows runtime, requested model,
actual routed model ref, provider, proxy, template, routing source, model-selection state, and role/stance when
applicable. The runtime-native Codex entry uses `resolved_model: null` and `model_selection: "runtime_default"`; human
output renders this as `resolved=(runtime default)`.

### "--check failed but output looks fine"

`--check` requires structured JSON output from each worker with a `passed` or `verdict` field. If the model wrote a
plain-text review without JSON, the check fails (no parseable verdict = failure).

### "Worker timed out"

Default timeout is 600 seconds (10 minutes). Increase with `-t`:

```bash
forge workflow analyze "Deep analysis" -t 900
```

### "Worker fails with `--bare: unknown option`"

Workflow subprocesses use `claude -p --bare` for faster startup when `ANTHROPIC_API_KEY` is available. `--bare` requires
Claude Code >= 2.1.81. Upgrade Claude Code to resolve this.

### "Worker fails with `claude CLI not found in PATH`"

The workflow resolved model routing, but the local worker runtime is missing. Install Claude Code or expose `claude` on
`PATH` in the same environment that runs `forge workflow`. Proxy-backed models still need the local `claude -p` binary.

### "Codex worker is unavailable"

Refresh the cached readiness snapshot, then retry:

```bash
forge runtime preflight codex
forge workflow list-models --available
```

Forge intentionally does not run the slower Codex doctor inline for every workflow verb. A cold, stale, or failed cache
entry fails closed instead of silently substituting a Claude worker.

### "debate rejects my proposal"

Debate builds its evaluation resource internally. If you need a custom evaluation framework, use `panel` with a custom
prompt (`-p`) instead.
