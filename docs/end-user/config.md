# Forge Configuration — Quick Reference

Configuration is split by ownership. Each type of setting has a single authoritative location:

| What you want to change                          | Where                              | Command                                |
| ------------------------------------------------ | ---------------------------------- | -------------------------------------- |
| Proxy mode, context limit, timeouts, logging     | `~/.forge/config.yaml`             | `forge config set/edit`                |
| Model routing, reasoning effort, temperature     | `~/.forge/proxies/<id>/proxy.yaml` | `forge proxy set/edit`                 |
| Claude Code hooks, status line, permissions, env | `~/.forge/claude.preset.json`      | `forge claude preset ...`              |
| Policy, memory, verification settings            | Session manifest                   | `forge session set`                    |
| Multi-model review and analysis                  | N/A (uses proxy/session config)    | [workflow.md](workflow.md)             |
| Automatic doc updates after sessions             | Session manifest (`memory.*`)      | [memory.md](memory.md)                 |
| API keys and credentials                         | `~/.forge/credentials.yaml`        | [authentication.md](authentication.md) |

---

## Runtime config (`~/.forge/config.yaml`)

Global Forge preferences. This file is **optional** — Forge works with built-in defaults when it's missing.
`forge config show` auto-creates the file on first access with documented defaults and comments. Bare `forge config`
prints command help.

```bash
# Show config commands
forge config

# Auto-create with commented defaults, then view effective config
forge config show
forge config show --raw     # YAML only, no headings or syntax highlighting

# Set a value
forge config set proxy_mode=sidecar
forge config set status_timeout=1.0

# Edit in $EDITOR
forge config edit

# Reset to built-in defaults
forge config reset proxy_mode   # Reset one key
forge config reset              # Delete config.yaml and use defaults
```

Notes:

- `forge config show` displays the effective config: built-in defaults, file values, and any environment overrides.
- `forge config edit` validates the edited YAML before applying it.
- `forge config reset <key>` removes that key from the file; `forge config reset` removes the whole file.
- `%config` inside Claude Code is read-only and shows the same effective runtime config.

Available settings:

| Key                              | Default                | Description                                                                                                                                                                                                                   |
| -------------------------------- | ---------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `proxy_mode`                     | `host`                 | `host` (proxy on host) or `sidecar` (bundled in Docker)                                                                                                                                                                       |
| `sidecar_image`                  | `forge-sidecar:latest` | Docker image for sidecar mode                                                                                                                                                                                                 |
| `user_agent_claude_code_version` | *(empty)*              | Version in User-Agent header sent to upstream LLM providers                                                                                                                                                                   |
| `context_limit`                  | `200000`               | Fallback auto-compact window for proxy mode (passed as `CLAUDE_CODE_AUTO_COMPACT_WINDOW`)                                                                                                                                     |
| `status_timeout`                 | `2.0`                  | Status line proxy/git call timeout (seconds)                                                                                                                                                                                  |
| `memory_writer_timeout`          | `300`                  | Memory writer timeout (seconds)                                                                                                                                                                                               |
| `log_level`                      | `off`                  | File logging level (`off`, `debug`, `info`, `warning`)                                                                                                                                                                        |
| `policy_summary_feedback`        | `on`                   | Post-evaluation summary lines and additionalContext (`on`/`off`)                                                                                                                                                              |
| `log_tool_failures`              | `false`                | Log tool failures to `~/.forge/logs/tool_failures/` (proxy; includes tool inputs/errors)                                                                                                                                      |
| `auth_ignore_env`                | `false`                | Ignore env vars for credential resolution; use credential file only. See [authentication.md](authentication.md#ignoring-environment-variables-auth_ignore_env)                                                                |
| `interactive_anthropic_api_key`  | `inherit`              | `omit` strips `ANTHROPIC_API_KEY` from interactive `claude` launches only (headless subprocesses keep it). See [authentication.md](authentication.md#keeping-a-key-out-of-interactive-sessions-interactive_anthropic_api_key) |

Environment overrides:

- `FORGE_DEBUG` overrides `log_level`. Accepted values: `1/true/yes` -> `debug`, `0/false/no/off` -> `off`, or explicit
  `debug/info/warning`

**Note on running processes:** Runtime config is cached per-process. Changes via `forge config set` take effect for new
CLI invocations and new sessions, but **already-running proxies do not pick up changes until restart**. To toggle
`log_tool_failures` on a live proxy, run `forge proxy stop <id> && forge proxy start <id>`.

**In-session access (read-only):** Type `%config` in the Claude prompt to see effective config. See
[hook.md](hook.md#in-session-commands--commands) for all `%` commands.

---

## Claude Code preset (`~/.forge/claude.preset.json`)

Forge keeps Claude Code settings customizations in a separate JSON preset. This file is user-editable and is merged into
Claude Code `settings.json` when you run `forge extension enable`.

```bash
# Shorthand for `forge claude preset show`
forge claude preset

# Show the current preset
forge claude preset show
forge claude preset show --raw

# Edit in $EDITOR
forge claude preset edit

# Reset to built-in defaults
forge claude preset reset
forge claude preset reset --yes
```

Built-in defaults include only Forge infrastructure:

- `hooks`: Forge hook wiring (`forge hook ...`)
- `statusLine`: `forge status-line`
- `permissions`: Write/Edit (required by the memory writer)

Forge merges only four setting families from the preset: `hooks`, `statusLine`, `env`, and `permissions`.

Use the preset when you want Forge to keep applying your preferred Claude Code settings on enable/re-enable, for
example:

- extra `env` entries
- personal `permissions`
- advanced hook or status-line customization if you intentionally want to override Forge defaults

Forge's built-in preset sets `statusLine` to `forge status-line` and nothing else. Claude Code status-line options such
as `refreshInterval` (poll cadence) and `padding` are **not** auto-installed — add them yourself via
`forge claude preset edit` (under the `statusLine` object). Forge intentionally leaves them to you so re-enabling never
overwrites your cadence/padding choices. Segment selection, palette, glyphs, and cost mode live in
`~/.forge/config.yaml` under `statusline:` instead (see `forge config set statusline.<key>`).

Notes:

- The preset file is auto-created on first access.
- `forge claude preset edit` validates JSON before saving.
- `forge claude preset reset` restores the built-in preset; without `--force`, it asks for confirmation.
- If the preset file is corrupted, Forge tells you to fix it with `forge claude preset edit` or reset it.

---

## Status line (`statusline:`)

The status line's fields, colors, and cost behavior live in `~/.forge/config.yaml` under `statusline:` (not the Claude
Code preset). Set keys with `forge config set statusline.<key>=<value>`:

| Key              | Values                        | Default       | Meaning                                              |
| ---------------- | ----------------------------- | ------------- | ---------------------------------------------------- |
| `segments`       | comma-separated segment names | (default bar) | Which fields show, in order. Empty = the default bar |
| `cost_mode`      | `auto` `api` `subscription`   | `auto`        | How the cost field is interpreted (see below)        |
| `palette`        | `default` `earthy`            | `default`     | Color theme                                          |
| `glyphs`         | `ascii` `unicode`             | `ascii`       | Progress-bar fill (`#`/`-` vs block characters)      |
| `cache_hit`      | `auto` `off`                  | `auto`        | `off` hides the `cache_hit` segment even if listed   |
| `cache_hit_ttl`  | seconds                       | `12`          | Direct-mode cache-hit recompute throttle window      |
| `forge_cost_ttl` | seconds                       | `10`          | `forge_cost` segment recompute throttle window       |

**Segments.** The default bar is `path, branch, breadcrumb, model, cost, lines, tokens, think, loop, sidecar`. Opt-in
segments (add to `segments` to enable): `rate_limits`, `cache_hit`, and the Forge-unique `supervisor`, `policy`,
`audit`, `drift`, `spend_cap`, `launch`, `forge_cost`. `forge config set` rejects unknown names; an empty list restores
the default bar. The `launch` segment shows how the session reached the model (`direct` / `proxy:<id>`) and the api-key
posture (`key:env|file|none|omit`); it appears only for Forge-managed sessions, not ambient `claude`. The `forge_cost`
segment shows `forge +$Y` — the LLM cost Forge added for this session (memory writer, supervisor, review fan-out),
**excluding** the main interactive session, reported-or-nothing (subscription/OAuth sessions show nothing) and distinct
from Claude's own `cost`; Forge-managed sessions only.

```bash
forge config set statusline.segments=path,model,cost,cache_hit,spend_cap
forge config set statusline.palette=earthy
forge config set statusline.cost_mode=subscription
```

**Billing-aware cost.** Claude Code runs on either a per-token API key (dollars are real) or a subscription/OAuth login
(dollars are a phantom; quota burn is the real signal). `cost_mode` picks the honest view:

- `api` — show real `$` spend.
- `subscription` — show the 5-hour quota instead of dollars.
- `auto` (default) — the 5-hour quota when Claude reports it, otherwise a hedged `≈$`. An `ANTHROPIC_API_KEY` in your
  environment is a capability, not proof of who pays (Forge may have hydrated it into an OAuth session), so `auto` never
  shows plain `$` from key presence — declare `cost_mode=api` if you bill per token and want real dollars.

Under a proxy the cost field shows the proxy's *reported* `~$`; the `~` flags that it can undercount, since
cost-unavailable routes are excluded rather than priced from a local table.

The status-line `cost` is **Claude's** native signal, not Forge's spend. For when to use it vs `forge proxy costs show`
(authoritative spend), `forge activity` (Forge automation activity), and the `forge_cost` segment, see
[which surface answers which question?](proxy.md#which-surface-answers-which-question).

**Removed:** the old flat `show_rate_limits` key. Add `rate_limits` to `statusline.segments` instead (e.g.
`forge config set statusline.segments=path,model,rate_limits`).

---

## Secrets (`forge authentication`)

API keys and credentials are managed via `forge auth login` and stored in `~/.forge/credentials.yaml`. These are for
Forge proxy routing and subprocesses, not your Claude Code login. Environment variables (`.env`, shell exports) still
work and take precedence over stored credentials (unless `auth_ignore_env` is set).

```bash
# Interactive credential menu
forge auth login

# Configure a single credential
forge auth login -c anthropic-api

# Check what's configured and where each key comes from
forge auth status
```

See [authentication.md](authentication.md) for credential details, profiles, migration, and full CLI reference.

**Rule:** Credential storage holds secrets and connection values (e.g., `LITELLM_BASE_URL`). Connection values are a
convenience fallback for bootstrapping proxy creation. Once `proxy.yaml` exists, proxy-owned routing is authoritative.

---

## Proxy files (`~/.forge/proxies/<id>/proxy.yaml`)

Model routing and hyperparameters. Each proxy is a self-contained YAML file — no merge with templates at runtime.

See [proxy.md](proxy.md).

---

## Worktree config (auto-copied)

When `forge session fork --worktree` or `forge session start --worktree` creates a git worktree, Forge copies untracked
runtime config from the main repo. These files are NOT git-tracked, so worktrees wouldn't have them otherwise.

**Copied automatically:**

| Path                           | Purpose                                       |
| ------------------------------ | --------------------------------------------- |
| `.env`, `.env.local`           | Environment variables (API keys, base URLs)   |
| `.envrc`                       | direnv configuration                          |
| `.mcp.json`, `.mcp.local.json` | MCP server configuration                      |
| `docker/certs/`                | Additional CA certificates (entire directory) |

Files/directories are skipped if they already exist in the target or are tracked by git. `--into` forks skip this copy
entirely (the target worktree already has its own config).

## Additional CA certificates

For environments with SSL inspection (e.g. enterprise, Zscaler), place **CA certificate** files in `docker/certs/`:

```bash
# CA certificate .pem or .crt files are auto-installed in Docker builds
cp your-ca.pem docker/certs/
```

The Dockerfile discovers all `.pem` and `.crt` files (top-level only — subdirectories are not scanned), copies them into
the Debian system trust store (`/usr/local/share/ca-certificates/`), and runs `update-ca-certificates` to merge them
into the canonical OS bundle at `/etc/ssl/certs/ca-certificates.crt`. Node.js (Claude Code) reads that bundle via
`ENV NODE_EXTRA_CA_CERTS=/etc/ssl/certs/ca-certificates.crt`, which is set unconditionally — the file always exists
(Mozilla defaults are present even with no user-added certs), so there is no empty-file warning. No filename convention
required — any `.pem` or `.crt` works.

**Security**: Only place CA certificate files here. **Never place private keys** (`.pem` files containing `PRIVATE KEY`
blocks) in this directory — they would be concatenated into the trust bundle and baked into the Docker image layer.

For worktree forks, the `docker/certs/` directory is automatically copied from the main repo (see above).

---

## Internal (not user-editable)

| What            | Location                                 |
| --------------- | ---------------------------------------- |
| Model catalog   | `src/forge/core/data/model_catalog.yaml` |
| Proxy templates | `src/forge/config/defaults/templates/`   |

To customize routing, create a proxy from a template and edit it. See [proxy.md](proxy.md).
