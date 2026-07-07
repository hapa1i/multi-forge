# Execution checklist: Env-var interface boundary

Execution plan for branch `env-var-interface-boundary`. Contract and rationale in [`card.md`](card.md).

## Current focus

Phase 0 (exhaustive inventory + open-question decisions) is the gate. Everything downstream — the classification table,
the string rewrites, and the guard's allowlist — sources from Phase 0's inventory, so it must be complete before Phase 1
starts. **Docs + strings + one new test only; no behavior change** (no env var renamed, removed, or re-resolved;
resolution order `FORGE_FORK_NAME -> FORGE_SESSION -> UUID` untouched).

**Status: plan folded review rounds 1-2; awaiting go-ahead before implementation.**

## Grounding delta (verified 2026-07-07 on this branch)

The card's cited sites all check out (`memory.py:753,817`; `session_memory.py:52,73,86,97`; `session_lane.py:118`;
`session_context.py:202`; `session.py:333`), and the two guard-precedent tests exist in `tests/src/cli/test_output.py`.
Findings shaping the plan:

- **The card's "~8 sites" undercounts.** Beyond the cited error/help-option sites, these also name `$FORGE_SESSION` as
  user-facing vocabulary: Click **command docstrings** `session_manage.py:753,998`, `session_memory.py:66,91`, and
  `claude.py:154` (`start_cmd`, added in review round 1), plus help-epilog examples living *inside* command docstrings
  `policy.py:1478,1528` + `activity.py:57`. This is *why* Phase 0's inventory must be exhaustive.
- **The guard must cover docstrings and op-layer raises, or it misses its own worklist.** The 7 docstring-class sites
  are invisible to a `help=`/`click.echo`-only walk; and `session.py:333` (`ForgeOpError`) + `session_context.py:202`
  (`SessionContextError`) are op-layer `raise`s the command-core renders (design.md §3.12), not `ClickException`s. Both
  folded into the D-EV-3 sink list below.
- **Direct-command `%` payloads are already clean; two flagged docstrings are internal.** `_handle_cmd_help`
  (`direct_commands.py:91`) emits a hardcoded `reason` naming no env var, and `%session` payloads already say "current
  session". `direct_commands.py:120,182` are docstrings on *private* handlers, never emitted. So `%` responses need **no
  rewrite today** — the guard covers them against future re-leaks.
- **Inventory method discriminates correctly** (evidence it earns its place): `claude.py:154` is a Click-command
  docstring (in scope), while `policy.py:141` (private-helper docstring) and `proxy/server.py:1836` (internal docstring)
  name `FORGE_SESSION` but are *not* Click sinks (out of scope). The decorator-scoped docstring rule separates them.
- **User-facing docs leak too, beyond `end-user/` and beyond `FORGE_SESSION`** (full internal-class sweep 2026-07-07,
  review round 2). `docs/cli_reference.md:101` is a normal-flow command doc that names `$FORGE_SESSION`;
  `session.md:730` names `FORGE_SUBPROCESS_PROXY` (a *different* internal-class family) in a how-to. So the doc
  scan/rewrite covers `end-user/**` **plus `cli_reference.md`**, and targets all internal-class names. Design docs stay
  out (they are the architecture contract and name internals legitimately; the classification table itself lives in the
  appendix).

## Phase 0 — Exhaustive inventory + decisions (GATE)

- [ ] **Real env-var inventory.** Enumerate every `FORGE_*` name read/written via environment APIs or launch env
  construction in `src/`: `os.environ[...]` / `.get()` / `.pop()` / `.setdefault()`, `os.getenv`, `os.putenv` if
  present, explicit env dict keys, subprocess/container env strings (for example Docker `-e FORGE_...=...`), and
  `*_VAR = "FORGE_*"` constants that are actually used as environment keys. Separate these from regex-only tokens
  (constants like `FORGE_MAX_DEPTH`, headers `FORGE_*_HEADER`, `_FORGE_*` module constants that are not env keys,
  QA-shell vars). Assertion: a written list tagging each entry real-env-var vs regex-only, with the three card-named
  false positives (`FORGE_MAX_DEPTH`, `WT_FORGE_LOG_SNAPSHOTS`, `FORGE_REV`) in the excluded column.
- [ ] **Exhaustive rewrite worklist.** From the inventory, list *every* user-visible string (Click `help=`/`short_help=`
  /`epilog=`, command/group docstrings, error/tip text, op-layer `raise` messages, `%` payload `reason`) that names an
  internal-class env var. Assertion: worklist is a superset of the seeded table below; each row marks normal-flow
  (rewrite) vs diagnostic (keep).
- [ ] **Decision D-EV-1 — `FORGE_STATUS_TRUNCATE` class.** Recommend **public-diagnostic** (genuine user value: the only
  way a wide-terminal user disables truncation — read at `status_line.py:1712`, `=0` disables). **But it is undocumented
  in `docs/` today**, so public-diagnostic requires the Phase 2 doc task below, or the table is self-inconsistent day
  one. Assertion: recorded in the table with rationale + a linked Phase 2 doc task.
- [ ] **Decision D-EV-2 — classification-table home.** New `design_appendix.md` section (reference material) + a
  one-line pointer from `design.md` §3.10 (one-authority rule). The card's own table becomes a stale snapshot after
  Phase 1 — fine (cards are context, design docs are contract); Phase 1 does **not** update the card table. Assertion:
  one authority, no duplicated live table.
- [ ] **Decision D-EV-3 — guard mechanics: two-layer.** Assertion: approach recorded with the false-positive tradeoff.
  - **Layer 1 — Python AST walk** over `src/forge/cli/**` + `src/forge/core/ops/**`, targeting user-visible sinks only:
    (i) Click help kwargs `help=`/`short_help=`/`epilog=`; (ii) Click command/group **docstrings** —
    `ast.get_docstring()` on any `FunctionDef` whose decorators include a `.command(`/`.group(` call (includes
    `claude.py` `start_cmd` + the 7 docstring sites; **excludes** plain-helper docstrings like `policy.py:141`); (iii)
    echo/output sinks `click.echo`, `click.ClickException`,
    `print_error`/`print_tip`/`print_error_with_tip`/`handle_session_error`; (iv) **op-layer raises** — string args to
    *any* `raise` in those two trees (path-scoped scan, **not** an exception-family enumeration, so a newly minted
    exception class can't silently escape; allowlist absorbs the rare internal case); (v) `%` payload `reason` values.
    Walk `ast.JoinedStr` parts so an f-string composing a name is caught. **No diagnostic allowlist here** — `logger.*`
    is a non-sink by construction (out of scope, not "exempt").
  - **Layer 2 — docs literal scan** over `docs/end-user/**` **and `docs/cli_reference.md`** (both user-facing; design
    docs excluded — architecture contract, name internals legitimately, and the classification table lives in the
    appendix). A literal scan is the right tool in prose (no `os.environ.get` false positives). **Allowlist by
    classification, not by file:** flag **internal-class names only**, so public + public-diagnostic names
    (`FORGE_HOME`, `FORGE_PROFILE`, `FORGE_DEBUG`, `FORGE_STATUS_TRUNCATE`) pass **everywhere** — `config.md` needs
    **no** file exemption (its documented `FORGE_DEBUG` passes; an internal leak there is still caught). Internal-class
    names are allowed only in **paired diagnostic blocks**: `<!-- forge-env-vocab: diagnostic:start -->` through
    `<!-- forge-env-vocab: diagnostic:end -->`. No whole-file diagnostic exemptions: even `hook.md` mixes explanatory
    and troubleshooting material, so only its explicit resolution/troubleshooting blocks get markers. Markers are paired
    (not heading-scoped, not "next paragraph") because legitimate diagnostics can span a list, blockquote, or table; the
    guard fails on unclosed/nested markers. This also handles `session.md:44`, which is diagnostic resolution-order
    content under a *non-troubleshooting* heading. Homes the card's "unsupported advice gone: repo-wide string scan"
    acceptance row.
  - **Allowlist consumption:** the guard owns a Python `{name: class}` mapping (operational data); a parity test asserts
    its name set equals the appendix table's `FORGE_*` names (presence, not prose formatting). Doc stays the human
    authority; parity blocks drift. Idiom precedent: statusline `SEGMENT_NAMES == SEGMENTS`, the effort-vocabulary drift
    guards.

**Seeded rewrite worklist** (Phase 0 finalizes; line numbers may drift). Error shape uses `Use --session <name>` per
cli_style_guidelines.md ("flags use `Use --flag`"); the strings being replaced already comply, so keep it:

| Site                              | Kind              | Current (names env var)                                  | Rewrite intent                                                                  |
| --------------------------------- | ----------------- | -------------------------------------------------------- | ------------------------------------------------------------------------------- |
| `cli/memory.py:753`               | error (raise)     | "...Set FORGE_SESSION or pass --session."                | "...Use --session <name> or run inside a Forge-managed session."                |
| `cli/memory.py:817`               | error (raise)     | (same advice)                                            | (same)                                                                          |
| `core/ops/session.py:333`         | error (raise)     | "...Use --session or set $FORGE_SESSION."                | "...Use --session <name> or run inside a Forge-managed session."                |
| `core/ops/session_context.py:202` | error (raise)     | "No session found (no argument, no $FORGE_SESSION)"      | "No session found. Use --session <name> or run inside a Forge-managed session." |
| `cli/session_memory.py:73,97`     | error (raise)     | "...run inside a Forge session ($FORGE_SESSION)."        | "...run inside a Forge-managed session."                                        |
| `cli/session_memory.py:52,86`     | help=             | "Target session (default: ambient $FORGE_SESSION)."      | "Target session (default: the current session)."                                |
| `cli/session_lane.py:118`         | help=             | (same)                                                   | (same)                                                                          |
| `cli/session_memory.py:66,91`     | docstring         | "Resolves $FORGE_SESSION when --session is omitted."     | "Resolves the current session when --session is omitted."                       |
| `cli/session_manage.py:753,998`   | docstring         | "Without NAME/SESSION_ID, resolves from $FORGE_SESSION." | "...resolves the current session."                                              |
| `cli/claude.py:154`               | docstring         | "Bare launcher: no session state, no FORGE_SESSION."     | "Bare launcher: no session state (not a managed session)."                      |
| `cli/policy.py:1478,1528`         | docstring example | "# current session ($FORGE_SESSION)"                     | "# current session"                                                             |
| `cli/activity.py:57`              | docstring example | "# current session ($FORGE_SESSION)"                     | "# current session"                                                             |

Confirmed **out of scope** (naming an env var but not a user-visible sink): `cli/policy.py:141` (private-helper
docstring), `proxy/server.py:1836` (internal docstring), `status_line.py:1653/1711` (debug log/comment), all
`os.environ.get("FORGE_SESSION")` reads.

## Phase 1 — Classification table (the durable deliverable)

- [ ] Write the classification table (Public / Public-diagnostic / Internal-wiring / Test-QA / decided
  `FORGE_STATUS_TRUNCATE`) in the D-EV-2 home, populated from the Phase 0 inventory. Assertion: every real env var from
  the inventory appears exactly once; `FORGE_HOME`/`FORGE_PROFILE`/`FORGE_DEBUG` public, the session family internal.
- [ ] Add the owned cross-reference pointer (design.md §3.10, optionally §3.4). Assertion: one authority, no duplicated
  live table.

## Phase 2 — Normal-flow string rewrites + implied doc

- [ ] Rewrite every normal-flow error/raise site from the worklist (unsupported "Set FORGE_SESSION" advice eliminated).
  Assertion: `rg "Set FORGE_SESSION|set \$FORGE_SESSION" src/` returns nothing in user-visible strings.
- [ ] Rewrite every normal-flow `help=`/docstring/example site. Assertion: no `--session` help text or
  `# current session` example names an env var.
- [ ] Rewrite the full user-facing **doc** worklist (complete internal-class sweep 2026-07-07):
  - `cli_reference.md:101` — "resolves `$FORGE_SESSION`" -> "resolves the current session".
  - `end-user/README.md:17`, `skills.md:219` — concept: depend-on-`FORGE_SESSION` -> "a Forge-managed session's launch
    environment".
  - `session.md:86` (bare-launch concept), `:287` (walkthrough "sets `FORGE_SESSION=...`" -> "records the session
    identity in the launch environment"), `:155` + `:809` (example comments -> `# current session`).
  - `session.md:730` — **`FORGE_SUBPROCESS_PROXY`** (not the session family): "sets `FORGE_SUBPROCESS_PROXY` for child
    jobs" -> "routes child jobs through the proxy".
  - Assertion: none of these name an internal-class env var; the docs scan is green.
- [ ] **Mark diagnostic blocks that legitimately keep internal names** with paired
  `<!-- forge-env-vocab: diagnostic:start -->` / `<!-- forge-env-vocab: diagnostic:end -->` comments: `session.md:44`
  (resolution-order reference — keep explicit; optionally slim to a pointer to `hook.md`'s canonical table),
  `session.md:891` (troubleshooting table), and the specific `hook.md` resolution/troubleshooting blocks (`:36-48`,
  `:57-58`, `:304-309`, `:323-326`, `:349-353` as of this branch). No whole-file `hook.md` exemption. The
  `status_line.py` debug log is a non-sink (untouched). Assertion: marked blocks retain their names and the guard
  exempts them; an internal-class name elsewhere in `hook.md` still fails the docs scan.
- [ ] **D-EV-1 doc task:** add one line documenting `FORGE_STATUS_TRUNCATE` as a public-diagnostic toggle (statusline
  section of `config.md` or the end-user statusline doc). Assertion: the var the table calls "documented" is actually
  documented.

## Phase 3 — Two-layer guard test

- [ ] Add `tests/src/cli/test_env_vocabulary.py` implementing D-EV-3, with the guard's Python `{name: class}` mapping as
  the allowlist source. Assertions:
  - (a) a planted internal name in a `help=` string, a Click-command docstring, and an op-layer `raise` is each flagged;
  - (b) a legitimate env read such as `os.environ.get("FORGE_SESSION")` or `os.getenv("FORGE_PROXY_ID")` is **not**
    flagged;
  - (c) a plain-helper docstring (`policy.py:141`-shape) is **not** flagged (validates decorator-scoping);
  - (d) the docs scan flags a planted internal name in a concept passage (incl. `cli_reference.md`) and in an unmarked
    normal-flow `hook.md` passage, but **not** a public-diagnostic name (`FORGE_DEBUG` in `config.md`) nor a paired
    diagnostic block;
  - (e) table↔guard parity: the mapping's name set equals the appendix table's `FORGE_*` names;
  - (f) the current tree passes after Phase 2.

## Acceptance tests

| Test                           | Fixture                                                    | Assertion                                                                                                                                                                    | Test File                                                  |
| ------------------------------ | ---------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------- |
| Guard (Python sinks)           | AST walk over `help=`/docstrings/echo/`raise`/`%` payloads | internal names flagged; env reads + plain-helper docstrings not flagged                                                                                                      | `tests/src/cli/test_env_vocabulary.py` (new)               |
| Guard (docs scan)              | literal scan over `end-user/**` + `cli_reference.md`       | internal name in a concept passage flagged; `FORGE_DEBUG` in `config.md` not flagged (public-diagnostic); paired diagnostic blocks exempt; no whole-file `hook.md` exemption | same                                                       |
| Table↔guard parity             | Python mapping vs appendix section                         | name sets equal (presence, not prose)                                                                                                                                        | same                                                       |
| Error rewrite                  | no ambient session, no `--session`                         | error says "Use --session <name> ... Forge-managed session"; names no env var                                                                                                | `test_memory.py`, `test_session_memory.py` (updated)       |
| Help rewrite                   | `--session` option `--help`                                | "default: the current session"; names no env var                                                                                                                             | `test_session_memory.py`, `test_session_lane.py` (updated) |
| Unsupported advice gone        | repo-wide + docs string scan                               | no user-visible string instructs setting `FORGE_SESSION`                                                                                                                     | guard test                                                 |
| Table complete + accurate      | design docs vs `rg FORGE_ src/` inventory                  | every real env var classified; regex-only tokens excluded; `FORGE_STATUS_TRUNCATE` documented where the table says so                                                        | doc check                                                  |
| Troubleshooting stays explicit | `hook.md` resolution/troubleshooting tables                | env-var names retained                                                                                                                                                       | doc check                                                  |
| No behavior change             | resolution-order + env-read unit tests                     | existing `session_context`/resolution tests pass unchanged                                                                                                                   | existing suites                                            |

## Closeout

- [ ] Grep the suite for assertions on old strings and update them alongside the rewrites:
  `rg -n "FORGE_SESSION" tests/ | rg -i "assert|help|error|reason"`.
- [ ] Focused suites green:
  `uv run pytest tests/src/cli/test_env_vocabulary.py tests/src/cli/test_memory.py tests/src/cli/test_session_memory.py tests/src/cli/test_session_lane.py tests/src/cli/test_output.py -q`
  plus the session/ops resolution tests; `make pre-commit` clean.
- [ ] Integration not required (docs + strings + a source-scan test; no hook/session/proxy runtime behavior changes).
  Record the rationale in the change-log entry.
- [ ] `change_log.md` entry (Goal / Key changes / Verification).
- [ ] Promotion candidate for `impl_notes.md` after review: the `FORGE_*` classification (internal-wiring vs public) and
  the two-layer guard as the drift check — durable because T4/T5/T6 will author new surfaces against it.
- [ ] Lane move `doing/ -> done/`; repoint the epic card's inbound link (`../env_var_interface_boundary/card.md`) if
  closeout changes it.
