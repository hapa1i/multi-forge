# Multi-Forge

<p align="left">
  <img src="assets/logo.jpg" alt="Dusk" width=240">
</p>

[![PyPI](https://img.shields.io/pypi/v/multi-forge)](https://pypi.org/project/multi-forge/)
[![Python](https://img.shields.io/pypi/pyversions/multi-forge)](https://pypi.org/project/multi-forge/)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)

> [!WARNING]
> **Research Preview** -- Forge is under active development. APIs, commands, and file formats may change without notice
> between releases. Not recommended for production use.

**Multi-runtime control plane for coding agents: put one vendor's model to work checking another's.**

Forge runs Claude Code or Codex as a managed session, then dispatches other models around it -- supervising writes
against an approved plan, curating handoffs across the vendor boundary, reviewing in a multi-model panel, and metering
what all of it cost. You launch through `forge session start` instead of invoking the runtime directly. Claude sessions
can route to a chosen provider through a local proxy; both runtimes share Forge's session state and policy model.

```bash
# Claude with session tracking (no proxy needed)
forge session start

# Route through a different provider -- --proxy takes a template name and starts it
forge session start planner --proxy openrouter-openai

# Have OpenAI's Codex police a Claude session's edits against the approved plan
forge session fork planner -n executor -w --supervise --supervisor-runtime codex --no-launch
```

## Why Forge?

Claude Code talks to Anthropic and tracks conversations. Forge adds an operational layer on top:

- **Cross-Vendor Supervision** -- Bind the plan supervisor or memory writer to a different consumer lane, or select a
  different runtime per review worker. The policy can evaluate every Write/Edit against the approved plan with a
  read-only `codex exec`; exact repeats may reuse its short-lived verdict cache.
- **Two Runtimes, One Session Graph** -- Claude sessions fork and resume; Codex sessions resume, and new Codex branches
  use `forge session start --runtime codex --resume-from <parent>` to carry curated context across the boundary.
  `forge session adopt` binds a conversation you started outside Forge.
- **Multi-Model Routing** -- Route to GPT, Gemini, or any model via OpenRouter or LiteLLM through a local proxy. Forge
  sets `CLAUDE_CODE_AUTO_COMPACT_WINDOW` so compaction timing matches the routed model's context window.
- **Cost Control** -- `forge telemetry costs show` reports what each proxy actually spent; per-proxy daily and monthly
  caps reject or warn at the ceiling. Cost is reported or marked unavailable -- never inferred from token counts.
- **Sessions That Outlive Context** -- Named sessions persist artifacts, plans, and transcripts. When context fills up,
  hand off to a fresh session with structured or AI-curated history you can edit before it lands.
- **Policy, Review, and Verification** -- TDD and coding-standard bundles, semantic alignment checks, multi-model review
  fan-out, and verification loops that keep an agent working until tests pass.

### Why launch through Forge?

Running `claude` directly bypasses session tracking. When you launch through Forge (`forge session start`), you get:

| Feature                | `claude` directly | `forge session start`                             |
| ---------------------- | ----------------- | ------------------------------------------------- |
| Session tracking       | No                | Yes -- named sessions, artifacts, transcripts     |
| Session resume         | No                | Yes -- editable handoff to fresh context          |
| Status line            | No                | Yes -- proxy, session, policy info                |
| Hook-driven artifacts  | No                | Yes -- plan snapshots, transcript capture         |
| Policy enforcement     | No                | Yes -- TDD, coding standards, supervisor          |
| Search across sessions | No                | Yes -- `forge search` indexes transcripts         |
| Project memory         | No                | Yes -- opt-in; passported docs curated after exit |
| Adopt an existing chat | n/a               | Yes -- `forge session adopt <conversation-id>`    |

Already deep into a bare `claude` or `codex` conversation? `forge session adopt` binds it to a managed session instead
of making you start over -- run it from the directory the conversation was launched in.

## How it Works

Forge sits between you and the agent runtime. It owns session state and policy, dispatches auxiliary consumers through
persisted lane bindings, selects review workers independently per workflow, and optionally routes model traffic through
a local proxy.

```text
You  ->  forge session  ->  Claude Code  |  Codex
              |
              +-- consumer lanes  -> supervisor       (claude | codex)
              |                      memory_writer     (claude | codex)
              |                      shadow_curation   (claude | codex)
              |                      team_supervisor   (claude)
              |
              +-- workflow workers -> panel | analyze | debate | consensus
              |                      (claude | opt-in codex)
              |
              +-- proxy            -> OpenRouter | LiteLLM -> any model
              +-- state            -> artifacts, policy, telemetry
```

**Claude direct mode** (the default for Claude sessions) skips the proxy and talks to Anthropic directly; you still get
sessions, hooks, consumer lanes, and the status line. Add `--proxy` for routing. **OpenRouter** templates call the
OpenRouter API directly -- one API key covers Anthropic, OpenAI, Google, and more. **LiteLLM** templates route through a
[LiteLLM](https://github.com/BerriAI/litellm) proxy, remote or a local subprocess. Twenty user-facing templates ship;
see [docs/end-user/proxy.md](docs/end-user/proxy.md).

## Requirements

- **Platform**: macOS or Linux
- **Python**: 3.11-3.13 (3.14 blocked on upstream `uvloop` wheels -- see #1)
- **Installer**: [`uv`](https://docs.astral.sh/uv/) or [`pipx`](https://pipx.pypa.io/) for the recommended global
  install
- **Claude Code**: required for the default and other Claude-backed workflows; a Codex-only session or skill path does
  not require it
- **Codex** (optional): needed for `--runtime codex` sessions, `forge codex start`, Codex-backed consumer lanes, and the
  opt-in Codex workflow worker. Check readiness with `forge runtime preflight codex`; proxy-routed `forge codex start`
  needs codex >= 0.141.0.
- **Provider auth**: Claude Code login is enough for direct interactive sessions. Proxies and headless workflows need a
  supported API or gateway credential such as `OPENROUTER_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`,
  `OPENAI_API_KEY`, or LiteLLM auth.

## Quick Start

```bash
# Install Forge as a global tool (recommended -- puts `forge` on your PATH)
uv tool install multi-forge
# or: pipx install multi-forge

# Make uv's tool bin available in this shell and future shells
uv tool update-shell
export PATH="$(uv tool dir --bin):$PATH"

# Confirm how forge is installed and whether it is globally reachable
forge extension doctor

# Register runtime hooks once, at user scope
forge extension enable --scope user --profile minimal --with hooks --without commands

# Then, inside a project: install project-owned assets and settings
forge extension enable

# Launch Claude with session tracking (no proxy needed)
forge session start

# Or with multi-model routing -- --proxy accepts a template name and starts the proxy for you
forge auth login -c openrouter                        # store OPENROUTER_API_KEY
forge session start --proxy openrouter-anthropic
```

Developing on Forge itself? See [CONTRIBUTING.md](CONTRIBUTING.md) for the editable install.

Once running, try `/smoke-test` (Claude) or `$smoke-test` (Codex) for a read-only health check, or `/walkthrough` for a
guided tour in a sandboxed test repo.

## Plan, Execute, Review

A typical feature workflow assigns different model roles to planning, execution, and review. The supervisor is a *lane*,
not a fixed model -- pin it to `codex` and a second vendor grades the first.

```bash
# 1. Plan with a high-reasoning model (--proxy takes a template; Forge starts it)
forge session start planner --proxy openrouter-openai
# ... Claude writes a plan, you approve it, /exit

# 2. Execute in a worktree, with the policy evaluating every Write/Edit against
#    the approved plan through read-only Codex (exact repeats may reuse its cache).
forge runtime preflight codex                 # cache the readiness the lane reads
forge session fork planner -n executor -w --supervise --supervisor-runtime codex --no-launch
forge policy supervisor reload -s executor    # REQUIRED: codex has no --resume, so the
                                              # approved plan must reach it in-band
cd ../multi-forge-executor                    # worktrees land at ../<repo-name>-<session-name>
forge session resume executor

# 3. Context filling up? Resume fresh -- supervisor config carries over.
forge session resume executor --fresh --strategy ai-curated

# 4. Review from the planner's perspective, inside the executor's worktree
forge session fork planner --into ../multi-forge-executor

# 5. Push and open a PR
git push origin feature-branch
```

Two prerequisites keep the Codex lane enforcing instead of failing open with a warning:

- **The plan reload is mandatory.** Codex has no `--resume`, so it cannot read the planning conversation. With no plan
  in-band, Forge fails the check open *without spawning Codex* -- it warns, it does not block. Use
  `forge policy supervisor reload`, or `%policy supervisor reload` from inside the session.
- **Preflight is cached, never probed during a check.** `codex doctor` is slow, but it is the probe that discovers
  stored ChatGPT-login auth. The policy hook therefore reads the full result cached by `forge runtime preflight codex`
  instead of rerunning it. A cold or stale cache fails open and prints a refresh hint.

`forge policy supervisor status` shows the bound `(runtime, backend, model)` lane. When preflight selects stored ChatGPT
tokens as the auth source, the check is labeled `subscription_quota` rather than Anthropic usage. Full details in
[docs/end-user/policy.md](docs/end-user/policy.md).

### Codex as a worker runtime

Codex is not only an alternate frontend -- it is a runtime Forge dispatches work to:

- **Other lanes.** `forge session lane set --consumer memory_writer --runtime codex` (also `shadow_curation`) moves that
  consumer onto `codex exec`. `team_supervisor` has no Codex lane and rejects it.
- **A whole task, seeded from a Claude parent.**
  `forge session start impl --runtime codex --resume-from planner --task "Implement the plan."` carries curated context
  across the vendor boundary; continue with `forge session resume impl --task "Now add tests."`.
- **Codex TUI through a Forge proxy.** `forge codex start --proxy <id>` -- the proxy owns upstream auth, so no OpenAI
  login is required or leaked.
- **Capability matrix.** `forge runtime list` shows what each detected runtime supports.

## Cost and Wire Control

```bash
forge telemetry costs show --period month --by-model   # authoritative proxy-scoped spend
forge telemetry activity planner                       # what Forge's automation did in one session
forge proxy set openrouter-openai costs.caps.per_day=20
forge proxy set openrouter-openai costs.on_cap_hit=reject   # or 'warn' for a header-only alert
```

Caps take effect when the proxy next starts, and are enforced *after* each completed request -- one request can cross a
cap and finish before the next is refused. `forge session start --subprocess-proxy <id>` keeps the interactive session
on direct Anthropic routing while supervisor, panel, and memory-writer subprocesses run metered through a proxy (it is
mutually exclusive with `--proxy`). Direct routing does not by itself guarantee subscription billing: the default
`interactive_anthropic_api_key=inherit` passes a resolvable API key. To force the interactive process to use its Claude
login, run `forge config set interactive_anthropic_api_key=omit`; see
[authentication.md](docs/end-user/authentication.md#keeping-a-key-out-of-interactive-sessions-interactive_anthropic_api_key).

A Forge proxy can also be an audit chokepoint. The default wire shape translates Anthropic to OpenAI and **drops
`thinking` blocks**; the shipped `anthropic-passthrough` template forwards the raw body byte-for-byte and already ships
`intercept.mode: inspect`, which hashes the system prompt and tool surface and flags drift when either changes
underneath you. `forge proxy audit show|diff` renders the timeline. Records are redacted before they reach disk --
hashes, lengths, and counts, never prompt or completion text.

## Skills

Nine skills compile for **both** runtimes -- Claude invokes `/<name>`, Codex invokes `$<name>`: `analyze`, `challenge`,
`consensus`, `debate`, `panel`, `review`, `review-docs`, `smoke-test`, `understand`. Only `/walkthrough` and `/qa` are
Claude-only.

The same runners are available from the terminal, and `--check` turns one into an exit-code gate you can script:

```bash
forge workflow panel src/forge/session/ --code   # fan a review out to several models
forge workflow debate "Should we rewrite this in Rust?"
forge workflow panel src/ --code --check         # exit 0 if every worker accepts, else 1
forge workflow list-models                       # which workers are ready right now
```

See [docs/end-user/skills.md](docs/end-user/skills.md) and [docs/end-user/workflow.md](docs/end-user/workflow.md).

## CLI Overview

| Command Group     | Purpose                                               |
| ----------------- | ----------------------------------------------------- |
| `forge session`   | Named sessions, worktrees, resume, fork, adopt, lanes |
| `forge claude`    | Bare launch, settings preset management               |
| `forge codex`     | Codex status, proxy-routed TUI launch                 |
| `forge runtime`   | Runtime inventory and readiness preflight             |
| `forge proxy`     | Model routing, templates, tier mappings, wire audit   |
| `forge model`     | Model catalog, backends, local backend lifecycle      |
| `forge telemetry` | Costs, per-session activity, provider traces          |
| `forge policy`    | Policy enforcement, plan supervision, shadow audit    |
| `forge workflow`  | Workflow runners (panel, analyze, debate, consensus)  |
| `forge memory`    | Project memory passports, shadow proposals            |
| `forge search`    | Transcript search across sessions                     |
| `forge auth`      | Credential management (`credentials.yaml`)            |
| `forge config`    | Runtime preferences (`~/.forge/config.yaml`)          |
| `forge extension` | Enable/sync/disable extensions                        |
| `forge clean`     | Preview and remove orphaned Forge state               |
| `forge logs`      | Log file locations and cleanup                        |
| `forge info`      | System health and installation info                   |

Run `forge <command> --help` for details on any command.

## Documentation

| Audience            | Location                                             | Contents                                              |
| ------------------- | ---------------------------------------------------- | ----------------------------------------------------- |
| **Users**           | [docs/end-user/](docs/end-user/)                     | 13 guides -- start with the Day 1 workflow            |
| **Developers**      | [docs/developer/](docs/developer/)                   | Setup, coding standards, testing guidelines           |
| **Architecture**    | [docs/design.md](docs/design.md)                     | Core system narrative, data flow, invariants          |
| **Workflow design** | [docs/design_workflows.md](docs/design_workflows.md) | Policy, skills, workflow runners, memory architecture |
| **CLI reference**   | [docs/cli_reference.md](docs/cli_reference.md)       | Terminal and direct-command inventory                 |
| **Work Board**      | [docs/board/](docs/board/)                           | Cards, checklists, change log, implementation memory  |

Common starting points: [sessions](docs/end-user/session.md), [proxies](docs/end-user/proxy.md),
[policy and supervision](docs/end-user/policy.md), [model selection](docs/end-user/model_selection.md),
[transfer context](docs/end-user/transfer.md), and [project memory](docs/end-user/memory.md).

## Troubleshooting

> [!NOTE]
> **Corrupt state?** If Forge reports that its state is corrupt, it names the offending file and stops -- it never
> silently runs on bad state. Run `forge clean` to preview what would be removed, then `forge clean --yes` to remove it
> (add `--scope all` to cover every project). For a full reset, delete `.forge` (project-local) or `~/.forge` (global)
> and re-run `forge extension enable`. Your own files and `proxy.yaml` config are never touched by `forge clean`.

`forge extension doctor` reports how Forge is installed, whether the launcher is reachable, and the state of the hook
dispatcher. Upgrading from a pre-OSS Forge install? See
[docs/end-user/README.md](docs/end-user/README.md#upgrading-from-pre-oss-forge).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup and PR guidelines.

## Uninstall

```bash
forge extension disable
uv tool uninstall multi-forge   # or: pipx uninstall multi-forge
```

## License

Apache 2.0 -- see [LICENSE](LICENSE).

Originally developed as Claude Forge at [Thomson Reuters](https://github.com/thomsonreuters/claude-forge) and
open-sourced under Apache 2.0. Continued as Multi-Forge by the original author.
