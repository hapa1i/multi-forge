# Checklist: Forge CLI Cleanup And Taxonomy

**Card**: [card.md](card.md) - **Branch**: `forge_cli_cleanup` - **Lane**: doing

Accepted 2026-06-23 at user request and moved `proposed/ -> doing/` directly.

Deepened 2026-06-23 from a read-only verification pass over the live CLI (every card finding checked at file:line,
corrections adversarially refuted). The reconciliation below is the basis for the concrete assertions in Phases 1-2 —
read it before starting a slice.

## Current focus

Phase 1 is a **decision gate**, not code. The card is a large clean break; the cheapest way to de-risk it is to settle
the taxonomy and the open questions first, then drain the five debt ledgers the test suite already tracks. Do not rename
a live surface before the matching decision is recorded here.

**Progress (2026-06-23):** Slice 02 shipped (session-scope move — `forge transfer` -> `forge session transfer`;
`forge memory enable|disable|status|report` -> `forge session memory ...`, passport verbs stay top-level), Slice 03
shipped (`forge activity`/`forge provider trace`/`forge proxy costs` moved to `forge telemetry`, `%provider trace`
retired), Slice 04 shipped (`forge backend` moved to `forge model backend`; `forge model catalog` added), and Slice 06
shipped (`forge session context` removed). Decision gate: **D1-D9 all decided.** See the Phase 1 section for details. D1
= move to `forge telemetry` + delete emptied `provider`; D2 = keep `proxy audit` under `proxy`; D3 = build `forge model`
namespace (backend moves under it); **D4 = split `forge memory` — activation/report verbs move to
`forge session memory`, passport verbs stay top-level**; D5 = route hook install through `extension` (de-document
`hook enable|disable`); D7 = tiered config-object verbs, `backend` excluded; **D8 = normalize all `json_output` ->
`as_json`**; **D9 = wait for the `workspace_scope` card (no `--scope workspace` on telemetry here)**. **D6 =
finalized:** `auth` canonical (no `authentication` alias); new nouns `telemetry`/`model` get no alias; the `extensions`
shim is removed; `ext`/`sess`/`mem`/`cfg` kept. **Slice 05 shipped 2026-06-24 — the final code slice. All Phase 2 slices
(02-12) are complete and the card's code work is done. Closeout done: change log entry added, docs synced,
`make pre-commit` clean, Docker integration 34/34 pass. Remaining: human-gated `impl_notes` promotion and the `doing/`
-> `done/` lane move (on merge).**

## Audit reconciliation (verified 2026-06-23)

### Corrections to the card (verify before trusting the card text)

| #                                     | Card framing                                                                    | Verified reality                                                                                                                                                                                                                                                                                                                                             | Action                                                                                                                                                              |
| ------------------------------------- | ------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| F13                                   | `forge config`/`forge search` hand-roll `invoke_without_command` "for a reason" | Both **only echo help**; `subcommand_metavar`/`help_option_names` work fine with `no_args_is_help=True` (adversarially confirmed). The card's normalization point **stands**.                                                                                                                                                                                | Normalize both to `no_args_is_help=True` (slice 12).                                                                                                                |
| F14f                                  | `forge proxy edit` "proxy overlay" wording may be stale                         | "Proxy overlay" is **canonical** terminology (design_appendix §A.1 title; `proxy_orchestrator.py:134 _get_proxy_overlay_dir`). Not stale.                                                                                                                                                                                                                    | **No-op.** Drop this bullet; do not "fix" the wording.                                                                                                              |
| F3                                    | Table lists per-command cleanup defaults                                        | All six rows confirmed; `forge proxy clean` (`proxy.py:1288`) has **zero** safety flags and prunes immediately — the most dangerous.                                                                                                                                                                                                                         | Standardize `clean` verbs (slice 09).                                                                                                                               |
| `forge model backend` (slice 04 / Q3) | Proposed nesting                                                                | `forge model` with a single child `backend` is a **single-child group nest** the guide forbids and `test_no_single_leaf_groups` would flag.                                                                                                                                                                                                                  | **Resolved in Slice 04:** introduced `forge model` only with ≥2 visible children (`backend` + `catalog`).                                                           |
| F4                                    | "11 read surfaces lack `--json`"                                                | Confirmed; but the guard only inspects leaves named `catalog/list/report/show/status`, so `forge authentication profiles` and `forge session transfer diff` are **invisible** to it (not in `JSON_MISSING_ALLOWLIST`).                                                                                                                                       | Add `--json` to all; extend the guard to cover `profiles`/`diff` (slice 07).                                                                                        |
| F9                                    | Hand-rolled tips/errors bypass helpers                                          | `test_cli_rich_tips_*` only catches Rich `[dim]Tip:`; **10 terminal tips** slip through — 8 plain `click.echo("Tip: …")` (auth ×4, claude ×2, install ×2) **plus 2 `ClickException`-embedded** (`session.py:111,126`, my prior row wrongly said session.py has only errors). 3 assistant-facing payloads (`direct_commands.py:79,162,705`) must stay exempt. | Migrate all 10; `ClickException` bodies become plain-error-only; reword the 2 non-recovery sites; guard allowlist = the 3 `direct_commands.py` payloads (slice 11). |

### Debt ledgers already tracking this card (drain, never grow)

Each `*_ALLOWLIST` is a pre-existing-violation ledger; `_assert_ledger` fails on a *new* violation **and** on an
allowlisted entry that was fixed-without-removal. "Done" for these slices = the entry is gone from the ledger.

| Ledger (file)                                                | Entries                                                                                                                                                                                                                                                                                           | Owning slice |
| ------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------ |
| `JSON_DEST_ALLOWLIST` (`test_command_tree_invariants.py:49`) | `proxy create`, `proxy metrics`, `policy check`, `policy supervisor`, `workflow {list-models,panel,analyze,debate,consensus}` — 9 using `json_output` not `as_json`                                                                                                                               | 07           |
| `JSON_MISSING_ALLOWLIST` (`:134`)                            | `authentication status`, `model backend show`, `proxy template {list,show}`, `claude preset show`, `config show`, `memory shadows show`, `search status` — 8 read leaves with no `--json` (the 9th, `memory report show`, was resolved early in Slice 02 as `forge session memory report --json`) | 07           |
| `SINGLE_LEAF_GROUP_ALLOWLIST` (`:65`)                        | ~~`forge provider`, `forge policy shadow`, `forge memory report`~~ **DRAINED to `set()`** (provider deleted Slice 03; memory report flattened Slice 02; `policy shadow` gained a `status` leaf Slice 12). Locked never-grow guard.                                                                | 03 / 12      |
| `LEAF_NAMING_ALLOWLIST` (`:110`)                             | `forge policy: supervise\|supervisor` (confusable; `supervise` is a prefix of `supervisor`)                                                                                                                                                                                                       | 10           |
| `CLI_ERROR_MARKUP_ALLOWLIST` (`test_output.py`)              | ~~18 files with hand-rolled `[red]Error:`~~ **DRAINED to `set()` in Slice 11** (234 sites routed to `print_error`); now a locked never-grow guard                                                                                                                                                 | 11           |

### Guard gaps (rules with no mechanical enforcement yet)

- **Destructive verbs (F3):** ~~`_(review)_`~~ **CLOSED in Slice 09** — `test_clean_verbs_preview_by_default` +
  `test_destructive_prompt_verbs_use_yes` now guard the clean/delete/reset flag shape; the style guide rule is
  `_Guard:_` (only the prompt presence/wording stays review). F14a (`proxy clean` redundancy) resolved here by removal,
  so the Slice 12 / F14 candidate list no longer needs to cover it.
- **Stream ownership (F10):** `_(review)_` only; no tree-wide stdout/stderr capture test. Slice 03 moved
  `proxy_costs.py` to stdout for both human and `--json` telemetry-cost output and added focused assertions.
  `proxy_audit.py:17` still renders human tables to `Console(stderr=True)` while `--json` goes to stdout, so the general
  guard remains slice 07 work.
- **Session selectors (F11):** `_(review)_`; rule is written (style guide §Command Shape) but unguarded.
- **Config-object verbs (F5):** D7 decided (tiered core `{show,edit,reset}` + optional `{set,validate}`, `backend`
  excluded); slice 08 adds the parity guard on the three pure-config objects.
- **`--json` guard scope (F4):** only `_READ_LEAVES` terminal names are checked (`catalog/list/report/show/status`;
  `report` added in Slice 02). Terminal-name allowlisting is fragile — a flatten/rename can move a read leaf out of
  coverage (as `report show` -> `report` did, caught and fixed in Slice 02). Slice 07 must extend `_READ_LEAVES` for
  `profiles`/`diff`/`query` and should consider a complementary keyword/docstring guard so a future rename can't
  silently drop a read surface.
- **Tip guard scope (F9):** ~~only `[dim]Tip:` Rich markup~~ **CLOSED in Slice 11** —
  `test_cli_rich_tips_go_through_output_helpers` now scans the literal `Tip:` (catches plain `click.echo("Tip: …")` and
  the 2 `ClickException`-embedded tips), allowlisting only the 3 assistant-facing `hooks/direct_commands.py` payloads.
  The `proxy_costs.py` help docstring and `session_fork.py` convention comment were reworded, so the final allowlist is
  exactly the payloads. Error markup is guarded the same way; both ledgers are drained and locked.

## Phase 0 - Board start

- [x] Create execution branch `forge_cli_cleanup`.
- [x] Move card from `docs/board/proposed/forge_cli_cleanup/` to `docs/board/doing/forge_cli_cleanup/`.
- [x] Update card status and references for the accepted lane.
- [x] Add this initial checklist.
- [x] Commit initial board-start state on the branch.

## Phase 1 - Taxonomy decision gate

Record a decision (with rationale) for each item before any Phase 2 slice that depends on it. Recommendations are
defaults to accept or override, not commitments.

- [x] **D1 Observability namespace (F1/F10, slice 03). DECIDED 2026-06-23: YES — move to
  `forge telemetry {activity,trace,costs}`.** Verified correction: `forge provider`'s only child is the `trace` group
  (`provider.py:76`), so moving `trace` to `telemetry` **empties** `provider`. Delete the `provider` group + its
  `main.py:384` registration outright and **remove** the `forge provider` entry from `SINGLE_LEAF_GROUP_ALLOWLIST` (not
  "edit the comment" — `_assert_ledger` fails on fixed-but-unremoved entries). The 3-leaf subgroup is `telemetry trace`,
  not provider. **Retire** the `%provider trace` direct-command mirror with no `%telemetry` replacement (clean break;
  don't grow the surface in a cleanup). Fix `proxy_costs.py:20`/`proxy_audit.py:17` stderr→stdout. `proxy audit` stays
  under `proxy` (D2 still open). Guard gap to close in slice 03: `test_no_single_leaf_groups` checks `len==1` only —
  tighten to `len<=1` so an emptied group can't pass silently.

- [x] **D2 Proxy audit placement (Q2). DECIDED 2026-06-23: KEEP `forge proxy audit show|diff` under `proxy`.** Capture
  is proxy-configured and the audit is about a specific proxy's downstream behavior, so it stays a 2-leaf subgroup under
  `proxy` (no telemetry move). Consequence to document at the call site: `audit` reads the same
  `~/.forge/telemetry/downstream/` data that `forge telemetry trace` (D1) reads, but the two live in different
  namespaces — note this split in `proxy_audit.py`/docs so it doesn't read as an oversight. Since `audit` is **not**
  moving, its `proxy_audit.py:17` stderr→stdout stream fix is owned by **slice 07** (stream ownership), not slice 03;
  slice 03 keeps only `proxy_costs.py:20` (which does move to `telemetry costs`).

- [x] **D3 Backend namespace (F5/Q3). DECIDED 2026-06-23: BUILD the `forge model` namespace.** Create a `forge model`
  group, move all 8 backend verbs to `forge model backend` (`list/show/test-auth/create/start/stop/delete/reconcile`,
  preserved verbatim), and add a real sibling leaf `forge model catalog` (or `list`) wiring `core/models/catalog.py`
  (zero CLI today). Two children (`backend` subgroup + `catalog` leaf) satisfy the ≥2-visible-leaves rule, so no
  `SINGLE_LEAF_GROUP_ALLOWLIST` entry and no single-child nest. Public-surface clean break (coding_standards §5): every
  `forge backend …` path moves to `forge model backend …` in one change (code + tests + docs + changelog). The catalog
  leaf must do real work, not a stub. New noun `model` flows into D6 alias decisions.

- [x] **D4 Memory split (Q4/Q5). DECIDED 2026-06-23: YES — split `forge memory`.** Session-scoped activation/report
  verbs (`enable`/`disable`/`status`/`report`) move under a new `forge session memory` subgroup; top-level
  `forge memory` keeps the project-doc passport verbs (`track`/`list`/`passport`/`shadows`). `report` **flattens** on
  the move to `forge session memory report` (a leaf carrying `[session]`/`--latest`/`--all`), which clears the
  `forge memory report` `SINGLE_LEAF_GROUP_ALLOWLIST` entry. Public-surface clean break (coding_standards §5): old
  `forge memory {enable,disable,status}` and `forge memory report show` return Click `No such command` in the same
  change (code + tests + docs + QA/walkthrough checklists + changelog). Owns Slice 02 alongside the unconditional
  `forge transfer -> forge session transfer` move.

- [x] **D5 Hook visibility (F8/Q6). DECIDED 2026-06-23: route end-users through `forge extension enable|disable`;
  de-document `forge hook enable|disable`.** Verified state: `forge hook` is already `hidden=True`
  (`hooks/_group.py:8`), so the command tree does **not** change — D5 is a docs decision. Keep the dispatcher handlers
  (`forge hook session-start|stop|policy-check|codex-session-start|codex-policy-check`) hidden and documented only as
  *what Claude Code / Codex invoke*. **Nuance (verified):** `forge hook enable|disable` are **not** redundant with
  `extension enable|disable` — `forge hook enable` always targets `settings.local.json`, while `forge extension enable`
  uses the scope's main settings file (`hook.md:96,358`; `extension*.py:526` enable / `:768` disable). So the
  lower-level `hook enable|disable` commands **stay** (hidden) for advanced `settings.local.json` targeting; we only
  stop presenting them as the user path. Docs work (tracked under "Docs and verification" → `hook.md`): rewrite the
  user-facing install sections (`hook.md:~88-96, ~340, ~358`) to point at `forge extension enable|disable`; keep the
  `forge hook <name>` dispatcher table (`hook.md` + `cli_reference.md:227`). No code change.

- [x] **D6 Alias + canonical names (F12/Q10/Q11). DECIDED 2026-06-23 (was partial; now complete).** `auth` is the
  **canonical** command name (register `name="auth"`, not `"authentication"`); **no `authentication` alias** kept —
  clean break (user: "auth is one word, I'm ok with the shortened version"). New nouns `telemetry`/`model` get **no
  short alias** — the names are already short and guessable (user: "no short aliases"). The `extensions -> extension`
  back-compat shim is **removed** (clean break; user: "back-compat can be removed"). The deliberate pre-existing short
  aliases **stay**: `ext`/`sess`/`mem`/`cfg`. **Rule recorded for the style guide (slice 05):** a top-level group earns
  a short alias only as a deliberate, rationale-backed UX affordance; new nouns get none by default; canonical names
  follow user vocabulary (short human form wins); pure back-compat rename shims are clean-broken, not kept.

  - **Final `_ALIASES` (alias -> target) after Slice 05:** `ext`->`extension`, `sess`->`session`, `mem`->`memory`,
    `cfg`->`config` (four; `auth`->`authentication` and `extensions`->`extension` removed).
  - **Final `_DISPLAY_ALIASES`:** remove `authentication`->`auth`; keep `extension`->`ext`, `session`->`sess`,
    `memory`->`mem`, `config`->`cfg`; no entries for `telemetry`/`model`.
  - Verified against live `main.py:50-65` by a map+verify workflow: every current alias has a verdict and
    `telemetry`/`model` are confirmed alias-free. Slice 05 carries the implementation (still runs **last**); its
    expanded blast radius (the canonical-rename mechanics plus doc/test/QA fallout the verify pass surfaced) is folded
    into the Slice 05 task below.

- [x] **D7 Config-object verb vocabulary (F5/slice 08). DECIDED 2026-06-23: TIERED vocabulary, `backend` EXCLUDED.**
  Verified verb matrix (all checked at source): `config`={show,edit,set,reset}; `proxy template`={show,edit,reset,list};
  `claude preset`={show,edit,reset}; `proxy`={show,edit,set,validate,+lifecycle}; `backend`={show,+lifecycle} (no
  edit/set/reset). So: **core `{show, edit, reset}`** is mandatory and **already satisfied** by config/template/preset
  (docs-only for them); **optional `{set, validate}`** where meaningful (`set`: config, proxy; `validate`: proxy);
  `proxy` is a documented partial-lifecycle exception (has `clean`/`delete`, no `reset`). **`backend` is NOT an
  editable-config object** — it is a lifecycle resource (`create`/`reconcile` regenerate its config; an in-place
  `edit`/`set` would fight `reconcile`), documented under the lifecycle-sibling rule (style guide L79-81, which already
  omits backend from the editable-config list at L88-89). Rejected the flat `{show,edit,set,reset,validate}` (no object
  implements it; would mandate net-new commands). Always fix the false proxy-parity docstring at `config_cmd.py:6-9`.
  Churn ~2-3 files. Records into the style guide; **unblocks slice 08**.

- [x] **D8 `--json` destination policy (Q8). DECIDED 2026-06-23: NORMALIZE all `json_output` -> `as_json`.** All 9
  `JSON_DEST_ALLOWLIST` leaves (`proxy create`, `proxy metrics`, `policy check`, `policy supervisor`,
  `workflow {list-models,panel,analyze,debate,consensus}`) rebind the `--json` option dest to `as_json`. The user-facing
  `--json` flag name is unchanged (implementation hygiene, not a flag rename); `JSON_DEST_ALLOWLIST` drains to `{}`.
  Implemented in Slice 07.

- [x] **D9 Workspace-scope coordination (Q7). DECIDED 2026-06-23: WAIT for the `workspace_scope` card.** This cleanup
  card does **not** introduce or reserve `forge telemetry … --scope workspace`; the workspace-scoped telemetry
  aggregation (flag + behavior) is owned by `docs/board/proposed/workspace_scope/`. `forge telemetry activity` keeps its
  current selector (optional positional `[session]` + `--days`/`--all`). Slice 07 scope-flag work is limited to the F11
  session-selector rule, not workspace scope.

- [x] Record every D1-D9 outcome inline here (with date) before starting the matching Phase 2 slice. (D1-D9 all recorded
  with dates as of 2026-06-23.)

## Phase 2 - Implementation slices

Each slice's assertion names an observable behavior and the test that proves it. Tick only when the test passes and the
verification is recorded.

- [x] **Slice 03 - Telemetry move (D1, D2).** Added `forge telemetry activity|trace|costs`; old terminal paths
  (`forge activity`, `forge provider trace`, `forge proxy costs`) now return Click `No such command` (clean break, no
  tombstone). `forge proxy audit show|diff` **stays under `proxy`** (D2). Deleted the emptied `forge provider` group,
  its `main.py` registration, and its `SINGLE_LEAF_GROUP_ALLOWLIST` entry. Tightened `test_no_single_leaf_groups` to
  flag `len<=1`. Moved telemetry-cost human output to stdout and asserted both human and `--json` cost output use stdout
  with empty stderr. **Direct-command mirror retired:** deleted `%provider trace list|show|explain` with no `%telemetry`
  replacement, removed the `%help` advert, and deleted `tests/src/cli/hooks/test_direct_commands_provider.py`. Updated
  docs/QA/operator guidance. Verification:
  `uv run pytest tests/src/cli/test_telemetry.py tests/src/cli/test_activity.py tests/src/cli/test_provider_trace.py tests/src/cli/test_proxy_costs.py tests/src/cli/test_command_tree_invariants.py tests/src/cli/hooks`
  (213 passed) and
  `./scripts/test-integration.sh tests/integration/cli/test_session_commands_integration.py::TestActivityCommand::test_activity_reports_supervisor_errors`
  (1 passed). Also ran `uv build` and `make pre-commit`.
- [x] **Slice 02 - Session-scope move (D4).** Moved `forge transfer show|regenerate|edit|diff` to
  `forge session transfer …` and split `forge memory`: activation/report verbs (`enable`/`disable`/`status`/`report`)
  moved to a new `forge session memory` group; top-level `forge memory` keeps the passport verbs
  (`track`/`list`/`passport`/`shadows`). `report` flattened from the former single-leaf `forge memory report show`. Both
  subgroups wired onto `session` in `cli/main.py` (assembly layer) to avoid a `session <-> transfer/memory` import
  cycle; new module `cli/session_memory.py` routes errors through `print_error`. Old `forge transfer …`,
  `forge memory {enable,disable,status}`, and `forge memory report show` return Click `No such command` (exit 2, clean
  break, no tombstone). Removed `forge memory report` from `SINGLE_LEAF_GROUP_ALLOWLIST` (flattened). The flatten
  changed the leaf's terminal name from `show` (a guarded read-leaf name) to `report` (unguarded), which would have
  hidden the `forge memory report show` JSON-missing debt; instead of silently dropping the ledger entry, **fixed** it
  here — `forge session memory report` gained `--json` (dest `as_json`: latest path+content, or the list under `--all`)
  and `report` was added to the guard's `_READ_LEAVES` so the flattened leaf stays enforced. Net: one fewer leaf for
  Slice 07 to drain, no hidden debt. Tests for the moved verbs relocated to the mirrored
  `tests/src/cli/test_session_memory.py` (new module -> own test file) with clean-break classes; `report --json` covered
  in `test_memory_report.py`; repointed the cross-package `tests/src/review/test_skill_content.py` skill-content guard
  and two regression-test docstrings. Verification: `uv run pytest tests/src/cli` incl. `test_session_memory.py` +
  `test_command_tree_invariants.py`; `make pre-commit` clean;
  `./scripts/test-integration.sh tests/integration/cli/test_handoff_integration.py` (10 passed — exercises
  `forge session memory enable`/`report` on a wheel-installed forge).
- [x] **Slice 04 - Model namespace (D3 = build).** Created `forge model` with two visible children: `backend` and
  `catalog`. Moved all 8 backend verbs to `forge model backend`
  (`list/show/test-auth/create/start/stop/delete/reconcile`, preserved verbatim). Added `forge model catalog` over
  `core/models/catalog.py` with human output and `--json` (`as_json`, covered by the read-leaf guard). Old
  `forge backend …` paths return Click `No such command` (clean break). Updated tests, docs, shipped QA checklist,
  shipped config templates/defaults, backend recovery guidance, integration harness/fixtures, `AGENTS.md`,
  `impl_notes.md`, and the changelog. Reworded `forge workflow list-models` as workflow-model readiness to avoid
  catalog/static vs runtime-readiness overlap. Updated `JSON_MISSING_ALLOWLIST` from `forge backend show` to
  `forge model backend show`; `forge model backend show --json` remains Slice 07 debt. Verification: 69 targeted
  unit/regression tests, backend integration (8), and proxy fixture smoke (1) passed.
- [x] **Slice 06 - Clean-break removals.** Deleted `forge session context` (was `session_manage.py:857`, `hidden=True`)
  and its now-dead `_print_session_context` helper + both `__all__` exports; **deleted**
  `tests/src/cli/test_session_context.py` (removed code → delete test). The ops module `forge.core.ops.session_context`
  is kept — used by `session show`/`activity`/`policy`/direct commands — and its
  `tests/src/core/ops/test_session_context.py` stays; corrected its "Used by" docstring and two mis-attributed comments
  in `session_manage.py`. Dropped the `cli_reference.md` note; fixed the stale "deprecated" `impl_notes.md` reference.
  Verified `forge session context` exits 2 with Click `No such command` (no tombstone). **Tombstone sweep:** `context`
  was the only deprecated-alias `hidden=True` command; `hook`/`memory-writer`/`status-line`/`policy shadow run` are live
  internals, left intact. 267 affected tests pass.
- [x] **Slice 07 - Read-output consistency.**
  - **A (`--json` added).** 10 read leaves grew `--json` (dest `as_json`): the 8 `JSON_MISSING_ALLOWLIST` leaves
    (`auth status`, `model backend show`, `proxy template list/show`, `claude preset show`, `config show`,
    `memory shadows show`, `search status`) **plus** `auth profiles` and `session transfer diff`. New shapes are stable
    - fully populated even on empty/early-return paths. Notable shapes: `auth status` exposes only source/provenance
      labels — secret `value` is `null` (verified programmatically, no leakage) — and carries an always-present
      `warning` key (corrupt-file degrade is no longer silent, matching the human path); `memory shadows show` is
      multi-row `{official, scope, shadows:[…]}`; `claude preset show` parses **only** in the `--json` branch (human
      mode still tolerates a corrupt file); `transfer diff` is `{parent, child, has_drift, diff}`. `_READ_LEAVES` +=
      `profiles`/`diff`; `JSON_MISSING_ALLOWLIST` → `{}`.
  - **B (`--json` dest normalized, D8).** 9 leaves' `--json` dest `json_output` → `as_json` across
    `proxy.py`/`policy.py`/ `workflow.py`. Deviation from plan: a uniform `replace_all` rename (helpers + leaves
    together) instead of adapting at the call boundary — every `json_output` ref was leaf-private
    (`_display_all_metrics`, `_run_preflight`, `_handle_routing_error`, `_handle_review_output`), so the uniform rename
    is simpler with no cross-leaf ripple. `JSON_DEST_ALLOWLIST` → `{}`.
  - **C (`search query` inverted).** `forge search query` now prints a Rich table (`Score`/`Session`/`Snippet` +
    `Found N result(s)`) by default; `--json` re-emits the prior shape **byte-stable**, including its conditional
    `error`/`hint`/empty variants. Consumers updated: 11 JSON-parsing sites in `test_search.py` (+2 new human-default
    tests), the walkthrough-stop regression test, the search integration test, QA 12.3 + walkthrough 10.5 checklists,
    `search.md`, and `cli_reference.md`. Stale "outputs JSON" docstrings reworded.
  - **D (stream ownership).** `proxy_audit.py:17` `Console(stderr=True)` → `Console()` so both `audit show`/`diff` human
    tables land on stdout (JSON already did). New `tests/src/cli/test_output_streams.py` (7 tests, plain `CliRunner()` —
    Click 8.2 removed `mix_stderr`): `--json` for `telemetry costs show`/`trace list`/`proxy audit show`/`diff` is valid
    JSON on stdout with empty stderr; `telemetry activity --json` seeded via monkeypatch (bare call exits 1, no
    session); audit human tables asserted on stdout.
  - **F11 (session-selectors, record-only).** Audit of ~32 session-scoped commands found 100% compliance with
    `cli_style_guidelines.md:83-86`; the rule stays `_(review)_` (no new guard). Resolves card Open Question 1:
    `telemetry activity [session]` / `costs show [proxy_id]` / `trace list --session` differ correctly because each
    applies the selector rule to its own primary object (no shared selector to unify).
  - **Shape tests (review follow-up).** The structural guard only proves `--json` presence, so added ~40 behavioral
    shape tests across the 10 new branches (parseability, exact key sets, dispatch/empty/error/no-secret paths),
    authored + adversarially verified via a fan-out workflow. Fixed the `auth status` silent corrupt-file degrade (now a
    `warning` key) and corrected `cli_style_guidelines.md`, which still called the stream guard "planned/not wired".
- [x] **Slice 08 - Config-object parity (D7 = tiered).** SHIPPED 2026-06-23. Enumerated the tiered vocab in the style
  guide (replacing the deferred placeholder at L91-94): core `{show, edit, reset}` (already met by
  `config`/`proxy template`/`claude preset`), optional `{set, validate}`, a per-surface table, and a dual
  `_Guard:_`/`_(review)_` marker. `proxy` documented as the partial-lifecycle exception (`clean`/`delete`, no `reset`);
  **`backend` excluded** as a lifecycle resource under the sibling-verbs rule (L79-81). Reworded the false proxy-parity
  docstring at `config_cmd.py:1-10` (dropped the "matches forge proxy show/set/edit" lines; names core+optional
  membership and points at the style guide). Added `test_editable_config_objects_share_core_verbs` — a **positive**
  core-set assertion (no debt to drain) on the three editable-config objects plus a **boundary lock** asserting
  `proxy`/`model backend` carry no `reset`, so prose and code can't drift. No net-new commands. Verification: the new
  guard + the 4 existing tree invariants (5 passed); full `tests/src/cli` (2022 passed); `make pre-commit` clean.
- [x] **Slice 09 - Destructive consistency (F3).** SHIPPED 2026-06-24. `clean` verbs now preview by default and mutate
  only with `--yes`. **F14a resolved → REMOVE:** verified `forge proxy clean` fully redundant (`prune_stale_proxies()`
  prunes registry **and** overlay dirs, and `list`/`create`/`start` each call it before their work; `forge clean` covers
  it globally) → deleted the command + its 7 stale doc/QA refs (module header, cli_reference, design.md, three
  `end-user/proxy.md` incl. the troubleshooting recovery row, the QA auto step) with `forge clean`/auto-pruning named as
  the replacement. **Conformed** `forge session clean` (dropped `--dry-run`, added `--yes`, default→preview;
  `main.py:46` exemption comment updated) and `forge search clean` (added `--yes` + read-only `find_missing()` detectors
  on `SearchDocumentStore`/`IndexStateStore` for the preview). **Two guards** (positive assertions, no ledger):
  `test_clean_verbs_preview_by_default` (clean leaves carry `--yes`, never `--dry-run`) and
  `test_destructive_prompt_verbs_use_yes` (delete/reset carry `--yes`; `forge session reset` is the one permanent
  exemption — a non-deleting override-layer reset, not a session/artifact delete). Style guide destructive rule flipped
  `_(review)_` → `_Guard:_`. Verification: 395 tests across `test_command_tree_invariants` (7), `test_session_commands`,
  `test_search`, `test_proxy_commands` (removal → exit 2), and the search-store `find_missing` units;
  `forge proxy clean` errors via Click; no stale `proxy clean` reference survives outside board files; `make pre-commit`
  clean.
- [x] **Slice 10 - Policy supervisor cleanup (F7). SHIPPED.** Deleted `forge policy supervise` and promoted the lone
  one-shot `supervisor` leaf into a `forge policy supervisor` group with **8 leaves**
  `{status, set, off, on, remove, reload, cascade, evaluate}` (full fidelity: `remove` + a standalone `cascade on|off`
  leaf preserved; cascade also stays a `set` modifier). The one-shot file-vs-plan eval is now `supervisor evaluate`
  (`evaluate`, not `check` — `forge policy check` keeps bundle-engine eval, untouched). The re-slice is CLI-only; the
  `supervisor.py` ops layer was unchanged (each leaf maps 1:1). `%policy supervise` direct command renamed to
  `%policy supervisor` (handler `_handle_policy_supervisor`, sub-verbs unchanged). **Two clean breaks:** old
  `forge policy supervise` and the bare one-shot `forge policy supervisor -f` both error via Click (exit 2); old
  `%policy supervise` falls through the in-session dispatcher to block-JSON usage naming `supervisor` (no Click).
  **Guards:** dropped the `forge policy: supervise|supervisor` entry from `LEAF_NAMING_ALLOWLIST` (now `{}`); the new
  `supervisor status` leaf is forced by `_READ_LEAVES` to expose `--json` (shared `_supervisor_status_dict` with
  `policy status`); no new confusable sibling pairs. **Verification:** 59 in `test_policy_supervisor.py` (incl. 2
  clean-break tests + configured/unconfigured `status --json` shapes), 84 in `test_user_prompt_dispatcher.py` (incl.
  old-verb-falls-through), 7 tree invariants, 2032 in `tests/src/cli`; complete doc/QA sweep (10 files) with empty stale
  greps; `make pre-commit` clean.
- [x] **Slice 11 - Recovery-output cleanup (F9). SHIPPED 2026-06-24.** Routed every hand-rolled terminal `Tip:` and
  `[red]Error:[/red]` through `forge.cli.output`, and locked both debt ledgers.
  - **234 `[red]Error:[/red]` → `print_error`** across 18 modules via two deterministic codemods (221 single-line + 13
    multi-line concat blocks), receiver-preserving so rendered output is byte-identical (`print_error` reconstructs the
    same `console.print`); redundant `style="red"` kwargs dropped. `CLI_ERROR_MARKUP_ALLOWLIST` → `set()`.
  - **10 tips routed**: 8 plain `click.echo("Tip: …")` (auth ×4, claude ×2, hooks/install ×2) → `print_tip`; the 2
    `session.py` `ClickException`-embedded tips → `print_error_with_tip` + `sys.exit(1)`. The proxy resolver
    (`_resolve_routing_from_cli`) now prints-and-exits instead of raising — verified no caller catches `ClickException`
    (only `backend.py` does, and it doesn't call the resolver) and all 13 resolver tests mock it. `claude.py`
    proxy-error branches use `print_error_with_tip` too.
  - **2 non-recovery `Tip:` reworded**: `proxy_costs.py` help docstring (dropped the `Tip:` prefix, kept guidance) and
    the `session_fork.py` convention comment. Final remaining literal `Tip:` outside `output.py` = exactly the 3
    `hooks/direct_commands.py` assistant payloads.
  - **Guard broadened**: `test_cli_rich_tips_go_through_output_helpers` now scans the literal `Tip:` (superset of
    `[dim]Tip:`; catches plain echoes + ClickException-embedded) with a file allowlist `{direct_commands.py}`, mirroring
    the shrink-only error ledger. Both guards fail on any new offender.
  - **Scope boundary (recorded)**: plain `click.echo("Error: …")` without Rich markup (~11 files) is out of F9 scope;
    only `[red]Error:[/red]`/`Tip:` are guarded. Plain echoes migrated only where intertwined with a moved tip.
  - Verification: full unit 6879 passed (clean run-tree env), `tests/src/cli` 2032 passed incl. 13 `test_output.py`
    guards, `make pre-commit` clean. Docs synced (`CLAUDE.md`, `cli_style_guidelines.md`).
  - **Post-review fixes (2026-06-24):** (1) **stream regression** — the resolver's `print_error*(console=console)` had
    moved proxy errors/tips from Click's stderr onto stdout; added shared `output.err_console` and routed the resolver's
    5 sites (and `hooks/install.py`) through it; helper defaults stay stdout (flipping them = ~71 bare sites, out of
    scope); regression test `tests/regression/test_bug_slice11_resolver_error_stream.py` exercises the real (unmocked)
    resolver. (2) **Tip allowlist tightened** file-level → payload-level: pinned to the 3 exact `direct_commands.py`
    payload sentences + stale-check, so a new `Tip:` even inside that file now fails (all 4 branches verified).
- [x] **Slice 12 - Non-leaf + small surfaces. SHIPPED 2026-06-24.** Normalized the two hand-rolled non-leaf groups,
  drained the last single-leaf-group entry, and resolved the F14 candidates.
  - **F13**: `forge config` + `forge search` → `no_args_is_help=True` (drop the `invoke_without_command` help
    callbacks). Behavior change recorded: bare invocation now prints help to stderr + exit **2** (was exit 0/stdout),
    matching `telemetry`/`model`. Updated the two bare-help tests (exit 2, assert on `result.stderr`).
  - **Single-leaf drain**: added `forge policy shadow status [session] --json` (sample rate + pending/done counts) →
    `shadow` is now show + status; `SINGLE_LEAF_GROUP_ALLOWLIST` → `set()`. Hidden `run` worker + its Stop-hook `Popen`
    untouched (chosen over collapsing to avoid the silent DEVNULL spawn path). New named `count_pending_candidates`
    helper (vs `count_existing_candidates`, which counts all lifecycle states).
  - **F14 `proxy metrics --all` removed** (clean break): bare `metrics` already aggregates when >1; old `--all` → exit 2
    "No such option". Converted the two `--all` tests + added a clean-break test.
  - **F14 resume-mode**: documented the intentional `{native,transfer}` vs `{transfer,native-relocate}` asymmetry at
    both call sites (comment only).
  - **F14 `memory track` / `extension sync`**: kept as-is — names are defensible (rename suggestions rested on a
    misread: `enable` = first-time setup, `sync` = refresh existing). F14f no-op (proxy-overlay wording canonical).
  - **Fold-in**: `claude.py start_cmd`'s 5 error sites → `output.err_console` (stderr); updated 3 stderr assertions.
  - Docs: `cli_reference.md` (+shadow status, −metrics --all), `end-user/proxy.md`, QA `4-proxy.md`,
    `design_workflows.md` (+shadow status), `cli_style_guidelines.md` (no_args_is_help → stderr/exit 2).
  - Verification: 267 tests across touched CLI files pass; tree invariants pass with both allowlists empty;
    `make pre-commit` clean.
- [x] **Slice 05 - Alias + canonical pass (D6). SHIPPED 2026-06-24.** Applied the D6 alias set as the final code slice.
  - **Functional (`src/forge/cli/main.py`)**: `_ALIASES` -> `{ext, sess, mem, cfg}` (dropped `auth`/`extensions`);
    `_DISPLAY_ALIASES` -> `{extension, session, memory, config}` (dropped `authentication`); flipped the registration to
    `main.add_command(auth, name="auth")`. The `extensions` Python symbol and its `name="extension"` registration are
    unchanged (symbol != CLI alias).
  - **Help/comment accuracy** (kept drift sweep 1 clean): `auth.py` help text -> `forge auth`;
    `install/{cli,hooks,preset,settings_merge}.py` comments + `test_version.py` docstrings + QA `2-extension.md` ->
    singular `extension`.
  - **Tests**: `extensions` -> `extension` CLI strings in `test_startup_queue.py` (6) + 3 integration files
    (`test_installer.py` — incl. the `:158` output assertion, now matching the real singular `forge extension enable`
    tip; `test_project_identity.py`; `test_startup_queue_integration.py`). Added `test_removed_aliases_are_clean_breaks`
    (bare + leaf `authentication`/`extensions` forms exit 2 "No such command") and
    `test_canonical_command_names_resolve` in `test_command_tree_invariants.py`.
    `test_extension_enable.py`/`test_version.py` object-invocations and `test_auth.py`/`test_memory.py` (`mem`) left
    untouched (verified safe).
  - **Docs**: `cli_reference.md` (alias sentence + table rows), `cli_style_guidelines.md` (crisp D6 rule: deliberate
    aliases only / new nouns get none / rename shims are temporary), `end-user/authentication.md` (removed the now-false
    "Alias" banner + all command forms), `end-user/README.md`, `config.md`, root `README.md`, QA `checklist.md` +
    `3-authentication.md`.
  - **Reconciliation with the original planned bullets (verified 2026-06-24)**: (a) the planned `JSON_MISSING_ALLOWLIST`
    rename (`forge authentication status` -> `forge auth status`) was a **no-op** — that ledger was already drained to
    `{}` in Slice 07, so there was nothing to rename. (b) The blast radius was **wider** than the original bullets
    enumerated: it also required `auth.py` help text, `install/*.py` + `test_version.py` docstrings, the
    `test_installer.py`/`test_project_identity.py` integration shell commands, and
    `authentication.md`/`README.md`/`config.md` end-user docs.
  - **Verification**: 2314 cli+install unit tests pass; new clean-break + canonical guards pass; manual smoke (exit
    2/2/0/0; help shows `auth` + `extension (ext)`); both drift sweeps clean (sweep 2's two `extensions.py` hits are
    benign English prose, `forge extension status` already singular); a 3-lens read-only adversarial verification
    workflow (completeness / alias-mechanism / diff-review) returned clean with zero findings; `make pre-commit` clean;
    Docker integration 34/34 pass (`test_installer.py` / `test_project_identity.py` /
    `test_startup_queue_integration.py`) on a wheel-installed forge.

### Acceptance table (risky / multi-file moves)

| Test                        | Fixture                          | Assertion                                                                                                                                                                                                                                          | Test File                                                    |
| --------------------------- | -------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------ |
| Telemetry new paths         | proxy + session with telemetry   | `forge telemetry {activity,trace,costs}` exit 0; shapes match old `--json`                                                                                                                                                                         | `tests/src/cli/test_telemetry.py`                            |
| Telemetry old paths removed | n/a                              | `forge activity` / `forge provider trace` / `forge proxy costs` exit 2 "No such command"; `%provider trace` produces no hook output and `%help` no longer advertises it                                                                            | `tests/src/cli/test_telemetry.py`                            |
| Single-leaf debt shrinks    | full command tree                | `SINGLE_LEAF_GROUP_ALLOWLIST` no longer lists `forge provider` (+ `forge memory report` if D4)                                                                                                                                                     | `test_command_tree_invariants.py`                            |
| `search query` inverted     | indexed transcript               | bare `query` prints human table on stdout; `--json` emits documented array; `--json` round-trips old shape                                                                                                                                         | `tests/src/cli/test_search.py`                               |
| `--json` missing drained    | each read leaf                   | every `JSON_MISSING_ALLOWLIST` leaf + `authentication profiles` + `transfer diff` emits valid JSON; ledger `{}`                                                                                                                                    | `test_command_tree_invariants.py`                            |
| `--json` dest normalized    | full tree                        | no leaf binds `json_output`; `JSON_DEST_ALLOWLIST` `{}`                                                                                                                                                                                            | `test_command_tree_invariants.py`                            |
| Stream ownership            | `proxy costs`/`audit` (or moved) | `--json` mode: valid JSON on stdout, empty stderr; human mode on stdout                                                                                                                                                                            | `tests/src/cli/test_output_streams.py` (plain `CliRunner()`) |
| Supervisor split            | session with supervisor          | `forge policy supervisor {status,set,off,on,remove,reload,cascade,evaluate}` work; `supervise` + bare `supervisor -f` exit 2; `status --json` shapes pinned; `LEAF_NAMING_ALLOWLIST` `{}`                                                          | `tests/src/cli/test_policy_supervisor.py`                    |
| `session context` removed   | n/a                              | `forge session context` exits 2 "No such command"; `test_session_context.py` deleted                                                                                                                                                               | (removal)                                                    |
| Error markup drained        | CLI source scan                  | `CLI_ERROR_MARKUP_ALLOWLIST` `{}`; all 10 terminal tips routed (incl. 2 `ClickException`); `proxy_costs.py:132` + `session_fork.py:467` reworded; tip guard fails on `Tip:` in CLI source, allowlist = exactly the 3 `direct_commands.py` payloads | `tests/src/cli/test_output.py`                               |
| Aliases clean break (D6)    | full command tree                | `forge authentication`/`forge extensions` (bare + leaf) exit 2 "No such command"; `forge auth`/`forge extension` resolve; `_ALIASES`/`_DISPLAY_ALIASES` = `{ext,sess,mem,cfg}`                                                                     | `tests/src/cli/test_command_tree_invariants.py`              |

## Docs and verification

- [x] Fix debt-ledger breadcrumb rot: provenance comment at `tests/src/cli/test_command_tree_invariants.py:7` now points
  at `docs/board/doing/forge_cli_cleanup/card.md` (was `proposed/`). `test_output.py:142` carries no path, so it needed
  no change. (Two stale cross-links remain in `docs/board/proposed/rewind_resume_strategy/card.md:27,260` — a different
  card's content; tracked separately, not fixed here.)
- [x] Update `docs/cli_reference.md` for every moved/removed/added surface (`session context` note dropped in Slice 06;
  alias sentence + `forge auth` table rows re-documented per D6 in Slice 05).
- [x] Update relevant `docs/end-user/*` guides (`hook.md` already in the D5 state — `forge extension enable` is the
  primary path, `forge hook enable|disable` kept as the lower-level advanced option; `proxy.md`/`session.md`/`memory.md`
  synced in their moves; `authentication.md`/`README.md`/`config.md` updated for D6 in Slice 05).
- [x] Update `docs/developer/cli_style_guidelines.md`: record the config-object verb vocabulary (D7), the stream guard
  once wired, the alias rule (D6), and remove "settled in the forge_cli_cleanup card" placeholders as each lands. (D7
  config-object vocab Slice 08; stream guard Slice 07; **D6 alias rule recorded in Slice 05** — deliberate aliases only
  / new nouns get none / rename shims are temporary.)
- [x] Update `docs/design.md`/`cli_reference.md` ownership tables if command ownership changes (telemetry, memory
  split). Done for both shipped moves: design.md §4.0/§3.x and cli_reference reflect `forge session memory` +
  `forge session transfer`; verified no stale `forge memory enable|disable|status|report` / bare `forge transfer <verb>`
  in the four normative docs (one intentional "(former `forge memory report show`)" breadcrumb kept).
- [x] Add a `change_log.md` entry per shipped slice naming the moved live commands (`forge activity` →
  `forge telemetry activity`, etc.).
- [x] Run targeted CLI tests for old/new paths, help text, `--json` shape, and stream behavior after each slice. (Slice
  05: 2314 cli+install unit tests + new clean-break/canonical guards pass; manual smoke confirms exit 2/2/0/0.)
- [x] `make pre-commit` before closeout (clean — see change log). Durable taxonomy/alias decisions are queued for
  human-gated promotion to `impl_notes.md` (the D6 alias rule + the "symbol != CLI alias" reconciliation lesson).

## Open decisions carried from the card

Phase 1 decisions are now folded into D1-D9. Remaining unchecked items are execution details, not unresolved taxonomy
decisions:

- [ ] Exact shared scope flags for `telemetry activity|costs|trace` (`--session` vs optional positional `[session]`,
  `--scope`, `--period`) — instantiate the F11 session-selector rule, not a per-command guess.
- [x] Final placement of `proxy audit` (D2) — RESOLVED 2026-06-23: stays under `forge proxy audit`.
- [x] Backend namespace + churn budget (D3) — RESOLVED + shipped (Slice 04): `forge model backend ...` plus
  `forge model catalog`.
- [x] Memory placement (D4) — RESOLVED + shipped (Slice 02): `enable`/`disable`/`status`/`report` live under
  `forge session memory`; passport verbs stay top-level `forge memory`.
- [x] Hook-management visibility (D5) — RESOLVED 2026-06-23: end users go through `forge extension enable|disable`;
  hidden `forge hook enable|disable` stays lower-level and de-documented as the user path.
- [x] Whether workspace-level telemetry waits for `workspace_scope` (D9) — RESOLVED 2026-06-23: wait for the separate
  `workspace_scope` card.
- [x] Whether any `--json` dest intentionally stays `json_output` (D8) — RESOLVED 2026-06-23: normalize all to
  `as_json`.
- [ ] Human read-output stdout/stderr rule + any documented exceptions (slice 07).
- [x] Canonical `auth` vs `authentication` and the alias-eligibility rule (D6) — RESOLVED 2026-06-23: `auth` canonical;
  new nouns get no alias; `extensions` shim removed; `ext`/`sess`/`mem`/`cfg` kept. See D6.
