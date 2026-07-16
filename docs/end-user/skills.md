# Forge Skills

Forge installs runtime-specific skills that teach Claude Code and Codex how to compose Forge capabilities into
workflows. Claude invokes a skill as `/forge:<name>`; Codex uses `$<name>`.

- Canonical architecture: [`docs/design.md` §5](../design.md#5-extensions-workflows-and-testing)
- Workflow CLI (engine): [`workflow.md`](workflow.md)
- Session context (model detection): [`session.md`](session.md)

---

## Quick start

```text
# Claude Code: portable skills
/forge:review src/forge/session/
/forge:review-docs docs/design.md
/forge:understand src/forge/core/ops/session_context.py

# Codex: the same portable frontends
$review src/forge/session/
$review-docs docs/design.md
$understand src/forge/core/ops/session_context.py

# Claude-only workflow frontends
/forge:panel src/forge/session/ --code
/forge:analyze "Should we use event sourcing for the audit log?"
/forge:debate "Should we migrate from skills to MCP?"
```

Five skills currently compile for both runtimes: `challenge`, `smoke-test`, `review`, `review-docs`, and `understand`.
For the argument-taking skills, the same task text follows the runtime-specific selector. `review`, `review-docs`, and
`understand` keep model-family resource selection orthogonal to runtime; `challenge` consumes only the claim text and
`smoke-test` runs its fixed read-only checks.

Six skills remain Claude-only. `panel`, `analyze`, `debate`, and `consensus` still start `claude -p` workflow workers;
making those workers runtime-neutral is separate work. `walkthrough` and `qa` drive Claude-specific manual-test flows.

## Installation and runtime targets

```bash
# Automatic: Claude skills, plus Codex skills when codex is detected
forge extension enable --scope user

# Explicitly select the SKILLS runtime package
forge extension enable --scope user --runtime codex

# Truly Codex-only project skills: no other Claude modules or settings
forge extension enable --scope project --profile minimal \
  --with skills --without commands --runtime codex
```

`--runtime claude|codex|all` is repeatable and controls only the SKILLS module. It does not filter commands, agents,
permissions, settings, status line, or hooks selected by the profile. Therefore a standard-profile `--runtime codex`
still changes its normal Claude surfaces. `forge extension sync` preserves the runtime set already tracked for that
installation, even if a runtime temporarily disappears from PATH.

| Runtime     | User scope                                          | Project scope           | Local scope             |
| ----------- | --------------------------------------------------- | ----------------------- | ----------------------- |
| Claude Code | `$CLAUDE_HOME/skills` (normally `~/.claude/skills`) | `<root>/.claude/skills` | `<root>/.claude/skills` |
| Codex       | `$HOME/.agents/skills`                              | `<root>/.agents/skills` | Unsupported             |

Codex skills never use `$CODEX_HOME`. Codex has no private local-only skill directory, so Forge refuses an explicit
Codex local request instead of writing personal state into the shared project `.agents/skills` directory.

---

## `/forge:review`

Review code for conformance, correctness, and architecture alignment.

```text
Claude Code: /forge:review [target]
Codex:       $review [target]
```

| Argument | Required | Description                                                         |
| -------- | -------- | ------------------------------------------------------------------- |
| `target` | Optional | File, directory, or instruction on what to review (defaults to cwd) |

**Model-aware resources:** The skill loads model-specific review instructions (`code-openai.md`, `code-gemini.md`, etc.)
based on the session's proxy. Falls back to the Opus-optimized default if no model-specific resource exists.

**Multi-model alternative:** For independent reviews from multiple models in parallel, use `forge workflow panel --code`
(CLI) or `/forge:panel --code` (skill).

---

## `/forge:review-docs`

Review design documents, specs, and technical writing for completeness and consistency.

```text
Claude Code: /forge:review-docs [target]
Codex:       $review-docs [target]
```

| Argument | Required | Description                                                         |
| -------- | -------- | ------------------------------------------------------------------- |
| `target` | Optional | File, directory, or instruction on what to review (defaults to cwd) |

Same model-aware resource selection as `/forge:review`, but loads `docs.md` / `docs-{family}.md` rubrics.

**Multi-model alternative:** For independent reviews from multiple models, use `forge workflow panel` (CLI) or
`/forge:panel` (skill).

---

## `/forge:understand`

Explain code, documentation, or technical concepts. Auto-detects code vs docs mode.

```text
Claude Code: /forge:understand [target] [--mode code|docs] [--depth quick|detailed|deep]
Codex:       $understand [target] [--mode code|docs] [--depth quick|detailed|deep]
```

| Argument  | Required | Description                                                                    |
| --------- | -------- | ------------------------------------------------------------------------------ |
| `target`  | Optional | File, directory, question, or instruction on what to explain (defaults to cwd) |
| `--mode`  | Optional | `code` or `docs` (default: auto-detected from target)                          |
| `--depth` | Optional | `quick`, `detailed`, or `deep` (default: `detailed`)                           |

Auto-detects `code` or `docs` mode from the target (file extensions, directory contents). Same model-aware resource
selection as other skills.

**Depth levels** control output length and analysis method:

| Depth    | Output        | Method                                  |
| -------- | ------------- | --------------------------------------- |
| quick    | \<500 words   | High-level overview                     |
| detailed | 500-1000      | Step-by-step with architecture and flow |
| deep     | Comprehensive | Multi-step systematic investigation     |

---

## `/forge:panel`

Multi-model panel review. Multiple models review independently, then findings are synthesized.

```text
/forge:panel [target] [--code] [--models model1,model2]
```

Claude Code only. The workflow engine still launches Claude workers even when Codex is installed.

| Argument   | Required | Description                                                         |
| ---------- | -------- | ------------------------------------------------------------------- |
| `target`   | Optional | File, directory, or instruction on what to review (defaults to cwd) |
| `--code`   | Optional | Switch: use code review framework (default: document review)        |
| `--models` | Optional | Comma-separated model list (default: Forge workflow defaults)       |

The panel runs `forge workflow panel` under the hood. Each model reviews independently, then the main agent synthesizes
consensus findings, unique insights, and conflicts.

**Default models:**

| Model                    | Strength                            | Via                     |
| ------------------------ | ----------------------------------- | ----------------------- |
| `gpt-5.6-sol`            | Logical problems, systematic review | openrouter-openai proxy |
| `gemini-3.1-pro-preview` | Balanced analysis, large context    | openrouter-gemini       |
| `claude-opus`            | Default Claude Opus 4.8 reasoning   | Direct Anthropic        |

Selectable direct Claude workers include `claude-opus-4.6`, `claude-opus-4.6-1m`, `claude-opus-4.8`, and `claude-fable`
(most capable). The default `claude-opus` worker resolves to Opus 4.8; use `--models claude-opus-4.6,claude-opus-4.8`
when you want both Opus 4.6 and the bounded-review Opus 4.8 worker in the panel, or add `claude-fable` for the top-tier
model.

**Requirements:** GPT-5.6 Sol and Gemini require active proxies; Claude Opus requires `ANTHROPIC_API_KEY`. See
[authentication.md](authentication.md#which-auth-do-i-need) for setup.

---

## `/forge:debate`

Adversarial multi-model evaluation. Models argue for, against, and neutrally about a subject.

```text
/forge:debate [subject] [--code] [--models model1,model2]
```

Claude Code only. The workflow engine still launches Claude workers even when Codex is installed.

| Argument   | Required | Description                                                                     |
| ---------- | -------- | ------------------------------------------------------------------------------- |
| `subject`  | Optional | File, directory, proposal, or instruction on what to evaluate (defaults to cwd) |
| `--code`   | Optional | Switch: use code evaluation framework (default: proposal)                       |
| `--models` | Optional | Comma-separated model list (default: Forge workflow defaults)                   |

The debate runs `forge workflow debate` under the hood. Each model is assigned a stance (for/against/neutral) and
evaluates independently -- workers are blinded to each other's output. The main agent synthesizes points of agreement,
key disagreements, and an evidence-weighted recommendation.

**Default models:**

| Model                    | Stance  | Role                     | Via                     |
| ------------------------ | ------- | ------------------------ | ----------------------- |
| `gpt-5.6-sol`            | FOR     | Supporter -- strengths   | openrouter-openai proxy |
| `gemini-3.1-pro-preview` | AGAINST | Critic -- risks          | openrouter-gemini       |
| `claude-opus`            | NEUTRAL | Analyst -- balanced view | Direct Anthropic        |

**Requirements:** GPT-5.6 Sol and Gemini require active proxies; Claude Opus requires `ANTHROPIC_API_KEY`. See
[authentication.md](authentication.md#which-auth-do-i-need) for setup.

---

## `/forge:challenge`

Pressure-test a claim, recommendation, or assumption with adversarial skepticism.

```text
Claude Code: /forge:challenge [claim or objection]
Codex:       $challenge [claim or objection]
```

| Argument | Required | Description                                                            |
| -------- | -------- | ---------------------------------------------------------------------- |
| `claim`  | Optional | Statement, objection, or question to pressure-test (inferred if empty) |

The skill defaults to skepticism: it assumes the claim may be wrong and tries to prove that. Only softens to a balanced
conclusion if the skeptical case fails. Returns a verdict: validated, partially validated, not supported, or
insufficient evidence.

**Model-invocable in Claude:** Claude can trigger this automatically when you say "are you sure?", "push back on this",
or "what am I missing?". In either runtime, an explicit invocation without arguments infers the claim from the preceding
conversation.

---

## Other skills

| Skill                               | Runtime        | Purpose                                                          |
| ----------------------------------- | -------------- | ---------------------------------------------------------------- |
| `/forge:analyze`                    | Claude only    | Deep single-model analysis (default model: claude-opus)          |
| `/forge:consensus`                  | Claude only    | Two-round multi-model convergence toward a shared recommendation |
| `/forge:smoke-test` / `$smoke-test` | Claude + Codex | Read-only installation health check                              |
| `/forge:walkthrough`                | Claude only    | Interactive feature tour (hermetic test repo)                    |
| `/forge:qa`                         | Claude only    | Full Docker-based QA (requires `full` profile)                   |

The portable smoke test resolves its bundled script from the installed skill directory, so `$smoke-test` and
`/forge:smoke-test` do not depend on the session CWD.

---

## Model-aware resource selection

`review`, `review-docs`, and `understand` automatically detect the model family from the session's proxy template:

```
Session -> proxy template -> tier model name -> vendor prefix -> family
```

| Family      | Templates using it          | Resource suffix |
| ----------- | --------------------------- | --------------- |
| `openai`    | `openrouter-openai`         | `-openai.md`    |
| `gemini`    | `openrouter-gemini`         | `-gemini.md`    |
| `anthropic` | `litellm-anthropic`, direct | (default)       |

The detection chain uses `forge session show --field model_family`, which resolves managed sessions from the
Forge-managed session's launch environment and otherwise falls back to local environment metadata such as
`ACTIVE_TEMPLATE`, `ANTHROPIC_BASE_URL`, and direct-model env vars. If detection fails, skills fall back to the
Opus-optimized default resource.

These skills also print the resolved model when Forge can identify it. In unmanaged direct runtime sessions, the host
may not expose the exact selected model to Forge; in that case the preflight says the exact model is not available
instead of reporting `none`.

**No extra skill configuration is needed.** Forge selects the resource from the detected model family.

For per-role guidance on when to use Opus 4.8 or Opus 4.6, when to mix families for `/forge:panel`, and when to
cross-route a supervisor to Gemini, see [model_selection.md](model_selection.md). The supervisor guidance there treats
long-context retrieval and citation fidelity as the checks to validate locally.

---

## Troubleshooting

### "Skill not found"

Skills are installed by `forge extension enable`. Check tracked package health first, then the selected runtime target:

```bash
forge extension status --json
ls "${CLAUDE_HOME:-$HOME/.claude}/skills/"  # Claude user packages
ls "$HOME/.agents/skills/"                  # Codex user packages
```

The status states are `present`, `missing`, `duplicate`, and `invalid-target`; each unhealthy package includes a
recovery. Run `forge extension sync` for missing tracked files. A Claude-only skill such as `panel` will not appear in a
Codex target.

### Wrong model instructions selected

Check the detected family:

```bash
forge session show --field model_family
forge session show --field main_model
```

If the family is wrong, the proxy template's tier models may not have the expected vendor prefix. Check with
`forge session show --json` to see the full proxy and model mapping.

### Skills installed in both user and project scope

Claude can have independent user and project/local copies, which can cause stale instructions or unexpected precedence
when one scope is outdated. Codex should have exactly one visible copy of each skill: the same name at user and project
scope is ambiguous, so Forge's duplicate scan prevents a second managed install. Runtime hooks are user-scoped;
project/local installs do not add new hook blocks.

Check with:

```bash
ls "${CLAUDE_HOME:-$HOME/.claude}/skills/"  # Claude user
ls .claude/skills/                              # Claude project/local
ls "$HOME/.agents/skills/"                     # Codex user
ls .agents/skills/                              # Codex project
```

Forge does not deduplicate Claude packages across scopes. For Codex, Forge reports a same-name package elsewhere in the
applicable user/project/admin scan chain and never overwrites or deletes it, even with `--force`. Automatic enable skips
a new affected package; an explicit request or a duplicate discovered beside an already managed package fails the whole
plan. Remove or rename the duplicate yourself. Use sync when the package is already tracked; if automatic enable skipped
the new package, rerun enable after cleanup because sync preserves the tracked runtime set rather than expanding it.

Prefer one skill scope per runtime/project. If you keep project-level skills, reinstall only the user-scope runtime
hooks:

```bash
forge extension disable --scope user
forge extension enable --scope project
forge extension enable --scope user --profile minimal --with hooks,codex-hooks --without commands
```

See [design_appendix.md §C.5](../design_appendix.md#c5-multi-scope-installation-skill-resolution) for details.

### Panel fails with "No active proxy found"

The panel's default model set includes `gpt-5.6-sol` and `gemini-3.1-pro-preview`, which require active proxies:

```bash
forge proxy create openrouter-openai
forge proxy create openrouter-gemini
```
