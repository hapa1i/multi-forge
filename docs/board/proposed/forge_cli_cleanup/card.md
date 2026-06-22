# Forge CLI Cleanup And Taxonomy

**Status**: Proposed. No command surface has changed yet. This card records the CLI style audit and proposes a
taxonomy-level cleanup before adding more command groups.

**References**: `docs/developer/cli_style_guidelines.md`, `docs/cli_reference.md`, `docs/design.md` §3.12,
`docs/board/done/remove_cli_tombstones/`, `docs/board/proposed/forge_codex_command_group/card.md`.

## Summary

Forge's command set has grown around useful implementation layers: sessions, proxies, provider traces, backend catalogs,
runtimes, transfer context, memory, policy, workflows, and install hooks. Individually most commands are defensible.
Together, the top-level taxonomy now asks users to understand too many internal boundaries.

The confusing cluster is:

```text
forge activity
forge backend
forge provider trace
forge runtime
forge transfer
forge proxy costs
```

These names overlap in plain English, but they answer different questions:

| Current surface        | Actual owner / meaning                                                       |
| ---------------------- | ---------------------------------------------------------------------------- |
| `forge activity`       | Per-session Forge automation outcomes and model-call evidence                |
| `forge provider trace` | Local request-level downstream/provider provenance                           |
| `forge backend`        | Model source catalog, auth probes, local lifecycle instances, reconciliation |
| `forge runtime`        | Agent frontend capabilities and preflight (`claude`, `codex`, `gemini`)      |
| `forge transfer`       | Parent/child session resume/fork context artifacts                           |
| `forge proxy costs`    | Spend/cost telemetry recorded by proxy and usage ledgers                     |

This card proposes a reorganization around user jobs:

- Session work units and transfer context live under `forge session`.
- Durable project memory docs live under `forge memory`.
- Model backend management lives under one model-oriented namespace.
- Request, cost, and activity evidence lives under `forge telemetry`.
- Agent frontends stay under `forge runtime`.
- Local routing proxy instances stay under `forge proxy`.

This is the largest user-visible break in the cleanup set. At minimum it moves three live observability surfaces
(`forge activity`, `forge provider trace`, `forge proxy costs`) and the live backend surface (`forge backend`). Size the
docs, changelog, end-user migration notes, and tests accordingly.

## Proposed Target Taxonomy

Sketch, not final API:

```text
forge session ...                 # work units and session-scoped context
forge session transfer show|regenerate|edit|diff

forge memory track|list|passport|shadows

forge proxy ...                   # local routing proxies and templates
forge proxy audit show|diff       # audit capture is proxy-configured

forge model backend list|show|edit|set|create|start|stop|delete|test-auth|validate|reconcile

forge telemetry trace list|show|explain
forge telemetry costs show|reset
forge telemetry activity [session]

forge runtime list|preflight      # agent frontends, not model backends
forge auth ...
forge policy ...
forge workflow ...
forge search ...
forge extension ...
forge config ...
forge logs
forge clean
forge info
```

The important split:

```text
forge memory ...                  # durable project knowledge and memory-doc passports
forge session transfer ...        # transient parent/child launch context
```

That resolves the current `memory` / `transfer` clash: memory is long-lived project material; transfer is session
continuity.

The observability split is equally important:

```text
forge model backend ...           # manage what Forge can route to
forge telemetry ...               # understand what happened and what it cost
```

`activity`, request trace, and costs are all evidence surfaces. Keeping them together avoids making users guess whether
session state, model catalog, or proxy ownership is the right entry point for "what happened?"

## Relationship To `forge codex`

The proposed [`forge codex` command group](../forge_codex_command_group/card.md) is CLI-taxonomy work too. It sketches a
sessionless, proxy-backed Codex launcher and a Codex-specific status surface while keeping managed Codex sessions under
`forge session start/resume --runtime codex`.

This cleanup card should coordinate with that proposal rather than independently reserving or renaming the same space:

- `forge runtime` remains the generic agent-frontend capability/preflight surface.
- `forge session ... --runtime codex` remains the managed-session path.
- `forge codex ...`, if accepted, is a runtime-specific convenience surface with specific Forge-added value; it should
  not become a thin alias for native `codex`.
- Any broader top-level taxonomy decision here should explicitly decide whether runtime-specific groups such as
  `forge codex` are allowed exceptions, and what bar they must clear.

## Audit Findings To Address

### 1. Observability is split across data-owner namespaces

The current "what happened / what did it cost?" surfaces are spread across `forge activity`, `forge provider trace`, and
`forge proxy costs`. Each placement follows a plausible owner boundary, but the user job is one observability job.

Desired outcome:

- Add `forge telemetry` as the job-named home for activity, request trace, and cost/spend views.
- Keep `forge model backend` focused on routing/model-backend management, not request provenance.
- Decide explicitly whether `forge proxy audit` stays under `proxy` because capture is proxy-configured or eventually
  joins `telemetry`.

### 2. Hidden deprecated command conflicts with clean-break policy

`forge session context` still exists as a hidden deprecated alias for `forge session show`. The CLI style guide now says
removed shortcuts are clean breaks: no hidden tombstones or compatibility commands that exist only to preserve old
names.

Desired outcome:

- Remove `forge session context`.
- Keep `forge session show [session] --json --field ...` as the one session context/read surface.
- Update `docs/cli_reference.md` to stop naming the deprecated alias.

### 3. Destructive cleanup semantics are inconsistent

Current cleanup surfaces use different safety defaults:

| Surface                      | Current behavior                                  |
| ---------------------------- | ------------------------------------------------- |
| `forge clean`                | Dry-run by default; `--yes` mutates               |
| `forge session clean`        | Mutates by default; `--dry-run` previews          |
| `forge proxy clean`          | Mutates immediately                               |
| `forge proxy costs reset`    | Prompts unless `--yes`; also supports `--dry-run` |
| `forge session delete --all` | Prompts unless `--yes`                            |
| `forge proxy delete --all`   | Prompts unless `--yes`                            |

Desired outcome:

- Standardize cleanup verbs around dry-run by default plus `--yes` to mutate, unless the command name is explicitly
  `delete` or `reset`.
- Add `--json` to cleanup read/preflight output where useful.
- Keep destructive semantics visible in help text and docs.

### 4. Read surfaces and `--json` destinations are inconsistent

The style guide says list/show and other scriptable read commands expose `--json`. Audit found likely gaps:

- `forge authentication status`
- `forge authentication profiles`
- `forge backend show`
- `forge claude preset show`
- `forge config show`
- `forge memory report show`
- `forge memory shadows show`
- `forge proxy template list`
- `forge proxy template show`
- `forge search status`
- `forge transfer diff`

Some of these may intentionally be raw-text surfaces, but the card should make each decision explicit. If a command is a
read surface and not intentionally raw, add `--json` using the `as_json` destination idiom.

There is a sibling consistency issue in shipped code: existing `--json` options already mix `as_json` and `json_output`,
including within the same modules. That makes the style-guide rule hard to audit mechanically.

Desired outcome:

- Add missing `--json` support to read surfaces unless the surface is intentionally raw text.
- Normalize existing `--json` option destinations to the style-guide idiom, or record a narrow exception for commands
  whose output object is better named `json_output`.
- Keep the user-facing option name stable as `--json`; this is implementation/API hygiene, not a flag rename.

### 5. Config-object verbs drift across similar command groups

Config-like surfaces use different verb sets and naming conventions:

- `forge config ...`
- `forge proxy ...`
- `forge claude preset ...`
- `forge proxy template ...`
- proposed `forge model backend ...`

The current spread includes variations of `show`, `get`, `set`, `edit`, `reset`, `validate`, and `delete`, with no
single rule for when a config object gets each verb. `src/forge/cli/config_cmd.py` also describes parity that the
command tree does not fully provide.

Desired outcome:

- Define a small, explicit verb vocabulary for editable config objects.
- Apply it consistently to proxy configs, proxy templates, Claude presets, backend configs, and top-level Forge config.
- Preserve backend lifecycle verbs (`create`, `start`, `stop`, `delete`, `reconcile`) when moving under
  `forge model backend`; do not relabel the namespace while silently dropping capabilities.

### 6. `forge search query` is inverted relative to normal CLI output

`forge search query <terms>` currently emits JSON unconditionally. Most Forge read commands default to human output and
reserve JSON for `--json`.

Desired outcome:

- Make human-readable search results the default.
- Add `--json` for the current structured shape.
- Preserve enough stability for scripts by documenting the JSON schema.

### 7. Policy supervisor naming and actions are overloaded

`forge policy supervise` handles configuration, status display, suspend/resume, remove, reload, cascade toggles, and
checker options through one verb with many flags. It also sits next to `forge policy supervisor`, which means one-shot
file evaluation. The names are too close for commands with different jobs.

Possible outcome:

```text
forge policy supervisor status
forge policy supervisor set <target>
forge policy supervisor off|on|remove
forge policy supervisor reload [--from <path>]
forge policy supervisor evaluate -f <path> -r <id>
```

Open question: whether `supervise` should disappear entirely or become one leaf under `policy supervisor`. Do not use
`check` as the supervisor leaf: `forge policy check` already owns the bundle-engine on-demand evaluation verb.

### 8. Hook management is documented as user-facing but hidden

`forge hook` is hidden because most hook handlers are internal runtime entry points. But `forge hook enable` and
`forge hook disable` are documented as advanced user-facing install commands.

Desired outcome, choose one:

- Keep runtime hook handlers hidden, but expose hook installation through a visible surface.
- Or stop documenting `forge hook enable|disable` and route users through `forge extension enable|disable`.

Do not leave a hidden group as the only documented way to reach an advanced user operation.

### 9. Tip, error, and recovery output bypass the helper layer

Most Rich-styled tips now go through `forge.cli.output`, but some CLI paths still hand-roll `Tip:` via `click.echo` or
embed tips inside `ClickException` messages. The larger drift is hand-rolled `[red]Error:[/red]` markup across the CLI,
which bypasses `print_error` and makes terminal recovery output inconsistent.

Examples found in:

- `src/forge/cli/auth.py`
- `src/forge/cli/claude.py`
- `src/forge/cli/hooks/install.py`
- `src/forge/cli/session.py`

Desired outcome:

- Terminal CLI recovery output uses `print_tip`, `print_error`, or `print_error_with_tip`.
- Terminal errors do not hand-roll `[red]Error:[/red]` outside `forge.cli.output` or a documented, narrow allowlist.
- JSON/direct-command hook payloads remain separate where they intentionally render assistant-facing text.
- Tests cover literal `[dim]Tip:`, plain `Tip:`, and `[red]Error:[/red]` drift outside the helper layer, so the guard
  catches both recovery tips and error markup.

### 10. Read commands mix stdout and stderr by output mode

Some read commands print human tables to a Rich console configured for stderr while printing `--json` to stdout. For
example, `forge proxy costs ...` and `forge proxy audit ...` currently split streams by output mode.

Desired outcome:

- Define stream ownership in the style guide: command results/read output go to stdout; diagnostics, warnings, prompts,
  and errors go to stderr.
- Make human and JSON variants of the same read command follow the same result stream unless there is a documented
  terminal UX exception.
- Keep JSON output stdout-only for scripting.

### 11. Session selector syntax is scattered

Session-scoped commands mix optional positionals and `--session`:

| Shape                          | Examples                                                 |
| ------------------------------ | -------------------------------------------------------- |
| Optional positional session    | `session show [session]`, `telemetry activity [session]` |
| `--session` option             | `policy status --session`, `memory enable`               |
| Mixed parent/child positionals | `transfer show <parent> --child <child>`                 |

Desired outcome:

- Define a session selector rule in the CLI style guide.
- Apply it consistently during the taxonomy move.
- Prefer optional positional only when the command's primary object is naturally "the session"; use `--session` when the
  session is ambient scope for another primary object.
- Treat `forge telemetry activity|costs|trace` scope flags as one application of this selector rule, not a separate
  taxonomy-only decision.

### 12. Alias docs and alias policy need cleanup

Runtime aliases include `auth`, `ext`, `extensions`, `sess`, `mem`, and `cfg`. The CLI reference currently documents
only some of them. `extensions -> extension` is a one-off backward-compat shim, not the deliberate short-alias pattern.
There is also a canonical-name inversion: the code and docs treat `authentication` as canonical with `auth` as the
alias, but the proposed taxonomy and most human examples naturally use `forge auth ...`.

The current alias set also looks arbitrary from a user's point of view. It is not clear why `authentication`,
`extension`, `session`, `memory`, and `config` get aliases while other high-traffic groups such as `proxy` or `policy`
do not. The taxonomy move should re-decide aliases after the final top-level nouns are known, including whether new
groups such as `telemetry` or `model` get short forms.

Desired outcome:

- Decide canonical group names independently from historical implementation names.
- Decide whether `authentication` remains canonical or whether `auth` becomes the canonical command.
- Decide whether `extensions -> extension` still earns its exception.
- Decide which top-level groups get short aliases, using an explicit rule rather than the current inherited set.
- Update `_ALIASES`, `_DISPLAY_ALIASES`, `docs/cli_reference.md`, and `docs/developer/cli_style_guidelines.md` together.

### 13. Non-leaf group behavior is mostly compliant but should be normalized

No live non-leaf group was found doing hidden work on bare invocation. `forge config` and `forge search` manually print
help on bare group invocation rather than using the common `no_args_is_help=True` shape.

Desired outcome:

- Keep behavior as-is if there is a reason.
- Otherwise normalize group declarations so future audits can reason about them mechanically.

### 14. Smaller redundancy and naming candidates need a pass

Several smaller surfaces look redundant, stale, or unintuitive enough to include in the implementation audit:

- `forge proxy clean` may be near-dead if list/create/start already prune stale proxy registry entries.
- `forge proxy metrics --all` appears redundant with the no-argument aggregate behavior.
- `forge memory track` mixes a verb-like command name with object management semantics.
- `forge extension sync` and `forge extension enable` should be reviewed for naming overlap.
- `forge session resume --resume-mode` and `forge session fork --resume-mode` expose divergent value names (`native`
  versus `native-relocate`) for related jobs.
- `docs/cli_reference.md` still describes `forge proxy edit <id>` as editing a "proxy overlay", which should be checked
  against current backend/proxy terminology.

Desired outcome:

- Decide which candidates are real cleanup work and which should remain documented exceptions.
- Remove or rename dead/redundant verbs only when the behavior is already covered by a clearer surface.
- Update docs and tests for any chosen removals or renames.

## Proposed Slices

01. **Taxonomy decision slice.** Finalize the command tree, especially:
    - the exact `forge telemetry` leaves and scope flags, using the session-selector rule from finding 11;
    - whether `forge model backend` is the right nesting for the unified backend vocabulary;
    - whether session-scoped memory activation/reporting moves under `session memory`;
    - whether hook management remains user-reachable.
02. **Session-scope move.** Move or introduce the canonical surfaces:
    - `forge session transfer ...`;
    - optionally `forge session memory ...`.
03. **Telemetry move.** Co-locate evidence surfaces under one observability namespace:
    - `forge activity ...` -> `forge telemetry activity ...`;
    - `forge provider trace ...` -> `forge telemetry trace ...`;
    - `forge proxy costs ...` -> `forge telemetry costs ...`;
    - decide whether `forge proxy audit ...` remains under `proxy` because capture/configuration is proxy-owned, or
      moves into telemetry later.
04. **Model/backend move.** Rename or reorganize:
    - `forge backend ...` into `forge model backend ...`;
    - preserve lifecycle-heavy backend verbs (`create`, `start`, `stop`, `delete`) and backend terminology unless the
      taxonomy decision slice explicitly chooses more churn.
    - add or preserve config-object verbs such as `show`, `edit`, `set`, `validate`, and `test-auth` so backend config
      is not less capable than proxy config.
    - keep `forge runtime ...` narrowly about agent frontends.
    - do not add new backend config-object verbs until slice 08 decides the shared config-object vocabulary.
05. **Alias and canonical-name pass.** After the taxonomy moves are chosen, decide canonical names and short aliases:
    - resolve `authentication` versus `auth`;
    - decide whether `extensions -> extension` survives as an exception;
    - decide whether new or moved groups such as `telemetry`, `model`, and `model backend` get aliases;
    - update `_ALIASES`, `_DISPLAY_ALIASES`, docs, and the CLI style guide together.
06. **Clean-break removal.** Remove `forge session context` and any other compatibility-only surface discovered during
    implementation. Do not add tombstone commands unless the style guide is explicitly changed.
07. **Read-output consistency.** Add missing `--json` support, normalize existing `--json` option destinations, fix
    `search query` default output, define result-stream ownership, and document schemas.
08. **Config-object parity.** Normalize the editable object verbs across `config`, `proxy`, `claude preset`,
    `proxy template`, and `model backend`, or record deliberate exceptions in the style guide.
09. **Destructive-command consistency.** Standardize clean/delete/reset confirmation and dry-run semantics.
10. **Policy supervisor cleanup.** Split `policy supervise` / `policy supervisor` into clearer leaves or document the
    chosen exception. Use `evaluate`, not `check`, for the one-shot supervisor evaluator if it remains under the
    supervisor group.
11. **Recovery-output cleanup.** Route terminal tips and errors through `forge.cli.output` and expand tests to catch
    hand-rolled `Tip:` and `[red]Error:[/red]` markup drift.
12. **Non-leaf group normalization.** Normalize bare group invocation declarations where practical, or document the
    commands that intentionally keep manual help printing.
13. **Small-surface cleanup.** Audit the smaller redundancy/naming candidates (`proxy clean`, `proxy metrics --all`,
    `memory track`, `extension sync`, `resume-mode` values, and stale docs wording) and either fix or document each one.
14. **Docs and references.** Update `docs/cli_reference.md`, relevant `docs/end-user/*` guides, design docs if command
    ownership changes, and the CLI style guide if new rules are introduced.

## Migration Policy

The current project policy favors clean breaks. Unless the card explicitly changes that policy:

- Do not add hidden tombstones for removed or moved commands.
- Do not add compatibility aliases just to preserve old paths.
- Name replacements in docs and changelog.
- Update tests to assert removed commands fail through Click's native "no such command" / "no such option" behavior
  where appropriate.

If a transition window is truly needed, record it as an exception in this card before implementation starts.

This card intentionally proposes a large clean break. The migration notes should call out the live-path moves by name:

- `forge activity ...` -> `forge telemetry activity ...`
- `forge provider trace ...` -> `forge telemetry trace ...`
- `forge proxy costs ...` -> `forge telemetry costs ...`
- `forge backend ...` -> `forge model backend ...`

## Acceptance Criteria

- `uv run forge --help` presents a smaller, guessable top-level taxonomy.
- `forge telemetry` is the single observability entry point for activity, request trace, and cost/spend views.
- `forge model backend` preserves the unified-backend lifecycle surface or documents any intentional vocabulary change.
- Canonical top-level names and aliases are explicitly chosen after the taxonomy move, including `auth` versus
  `authentication`.
- Non-leaf groups print help when invoked bare, preferably through a consistent declaration pattern.
- Removed shortcuts are gone, not hidden.
- List/show/read surfaces either support `--json` or document why they intentionally do not.
- Existing `--json` option destinations are normalized to the style-guide idiom or documented as intentional exceptions.
- `forge search query` has human output by default and JSON behind `--json`.
- Editable config-object groups use a consistent verb vocabulary or document deliberate exceptions.
- Human and JSON output variants of read commands follow the documented stdout/stderr policy.
- Cleanup verbs have consistent dry-run/confirmation behavior.
- Terminal recovery tips and errors go through `forge.cli.output`, with guard tests for hand-rolled `Tip:` and
  `[red]Error:[/red]` markup drift.
- `docs/cli_reference.md` and end-user docs match the shipped surface.
- Changelog or migration docs explicitly name the moved live commands.
- `make pre-commit` passes; targeted CLI tests cover old-path removal, new command paths, help text, JSON output, and
  output-stream behavior.

## Open Questions

01. What exact scope flags should `forge telemetry activity|costs|trace` share (`--session`,
    `--scope workspace|project|all`, `--period`, etc.), and how do they instantiate the session-selector rule from
    finding 11?
02. Should `forge proxy audit show|diff` stay under `proxy` because capture/configuration is proxy-owned, or move into
    `telemetry` once the observability namespace exists?
03. Should `forge model backend` be the final backend nesting, or is the rename churn from top-level `backend` too high
    for the value it adds?
04. Should `forge memory report show` move to `forge session memory report`, since reports are session writer artifacts?
05. Should `forge memory enable|disable|status` move under `session memory`, leaving top-level `memory` for project
    docs?
06. Should `forge hook enable|disable` become visible, move under `extension`, or disappear from user docs?
07. Should workspace-level telemetry aggregation wait for the existing `workspace_scope` card, or should this card
    reserve names such as `forge telemetry activity --scope workspace`?
08. Are any `--json` destinations intentionally clearer as `json_output`, or should the implementation standardize on
    `as_json` everywhere?
09. Should human read output always go to stdout, or are there existing terminal UX exceptions worth preserving?
10. Should `auth` become canonical instead of `authentication`, and what rule decides which groups get aliases?
11. Should new top-level groups such as `telemetry` or `model` have aliases, or should the cleanup reduce aliases
    overall?
