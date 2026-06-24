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
shim is removed; `ext`/`sess`/`mem`/`cfg` kept. Slice 05 (runs last) implements. **Remaining slices (05 runs last;
07-12) are parked pending direction.**

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
| `SINGLE_LEAF_GROUP_ALLOWLIST` (`:75`)                        | `forge provider` (→ **delete**; `trace` moves to `telemetry trace` per D1), `forge policy shadow` (→ `show`; `run` hidden), `forge memory report` (→ flatten)                                                                                                                                     | 03 / 12      |
| `LEAF_NAMING_ALLOWLIST` (`:110`)                             | `forge policy: supervise\|supervisor` (confusable; `supervise` is a prefix of `supervisor`)                                                                                                                                                                                                       | 10           |
| `CLI_ERROR_MARKUP_ALLOWLIST` (`test_output.py`)              | 18 files with hand-rolled `[red]Error:` (244 raw occurrences outside `output.py`)                                                                                                                                                                                                                 | 11           |

### Guard gaps (rules with no mechanical enforcement yet)

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
- **Tip guard scope (F9):** only `[dim]Tip:` Rich markup — misses the 8 plain `click.echo("Tip: …")` sites **and** the 2
  `ClickException`-embedded tips (`session.py:111,126`, `msg += "\nTip: …"`). A literal `Tip:` source scan also hits the
  3 assistant-facing `hooks/direct_commands.py` payloads (the only legitimate exemption), plus a Click **help
  docstring** (`proxy_costs.py:132` — user-visible terminal help, not "non-terminal") and a convention comment
  (`session_fork.py:467`); the latter two are reworded in slice 11 so the final allowlist is just the payloads.

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
- [ ] **Slice 09 - Destructive consistency (F3).** `clean` verbs preview by default + mutate on `--yes`: fix
  `forge session clean` (`session_manage.py:570`, mutates by default today) and `forge proxy clean` (`proxy.py:1288`, no
  flags today). `delete`/`reset` keep prompt + a single `--yes` bypass name. Decide F14a (is `proxy clean` redundant
  with list/create pruning?) — remove only if behavior is fully covered. Tests assert each command's default and
  `--yes`/`--dry-run` behavior.
- [ ] **Slice 10 - Policy supervisor cleanup (F7).** Split `forge policy supervise` (12+ flags) into
  `forge policy supervisor {status,set,off,on,reload,evaluate}`; `evaluate` (not `check`) is the one-shot file-vs-plan
  eval; `forge policy check` keeps bundle-engine eval. Removing the collision drops `forge policy: supervise|supervisor`
  from `LEAF_NAMING_ALLOWLIST`. Old `forge policy supervise` returns `No such command`. Update `%policy supervise`
  direct command + docs.
- [ ] **Slice 11 - Recovery-output cleanup (F9).** Route **all** terminal/user-visible `Tip:` output through
  `print_tip`/`print_error_with_tip`, **including tips embedded in `ClickException` messages**: the 8 plain
  `click.echo("Tip: …")` sites (auth.py ×4, claude.py ×2, hooks/install.py ×2) and the 2 `ClickException`-embedded tips
  (`session.py:111,126`). Policy (per card finding #9): a `ClickException` body is plain error text only — no embedded
  `Tip:`; route the tip via `print_error_with_tip` then exit. **Explicitly exempt assistant-facing direct-command JSON
  payloads** (`hooks/direct_commands.py:79,162,705`) — they are not terminal output.
  - Migrate the 18 `CLI_ERROR_MARKUP_ALLOWLIST` files to `print_error*` until that ledger is `{}`.
  - Reword the two non-recovery `Tip:` sites so neither leaves a literal `Tip:`: the `proxy_costs.py:132` Click help
    docstring (user-visible help, not recovery — drop the `Tip:` prefix, keep the guidance) and the
    `session_fork.py:467` convention comment. After rewording, the final guard allowlist is **exactly** the three
    `direct_commands.py` assistant payloads — nothing else.
  - Extend the guard to fail on a literal `Tip:` anywhere in `src/forge/cli/**` except `output.py` and that
    direct-command-payload allowlist. Mirror the shrink-only `CLI_ERROR_MARKUP_ALLOWLIST` ledger style — a source scan,
    not AST-only, since the `session.py` `msg += Tip:` → `ClickException` pattern has no `click.echo` to match.
- [ ] **Slice 12 - Non-leaf + small surfaces.** Normalize `forge config`/`forge search` to `no_args_is_help=True` (F13
  stands). Resolve remaining `SINGLE_LEAF_GROUP_ALLOWLIST` entries (`forge policy shadow`). Audit the F14 candidates:
  `proxy metrics --all` (redundant with no-arg aggregate — remove or document), `memory track` naming, `extension sync`
  vs `enable` naming, `resume-mode` value divergence (`resume {native,transfer}` vs `fork {transfer,native-relocate}` —
  document the intentional asymmetry at the call site). F14f is a **no-op** (proxy-overlay wording is canonical).
- [ ] **Slice 05 - Alias + canonical pass (D6, finalized).** Apply the D6 alias set. Run **last** so new nouns from
  D1-D4 are settled. Verified blast radius (map+verify workflow, 2026-06-23):
  - `src/forge/cli/main.py`: `_ALIASES` (50-57) remove `"auth": "authentication"` (51) and `"extensions": "extension"`
    (53); `_DISPLAY_ALIASES` (59-65) remove `"authentication": "auth"` (60). **Load-bearing:** flip the registration
    `main.add_command(auth, name="authentication")` (~381) to `name="auth"` — removing the alias is only coherent once
    `auth` is the registered canonical. `main.add_command(extensions, name="extension")` (393) is unchanged (the Python
    symbol `extensions` is the command object, unrelated to the removed CLI string).
  - `docs/cli_reference.md`: rewrite the alias sentence (10-11) — drop the `authentication`/`auth` clause (auth is now
    canonical, not an alias) and the `extensions` clause; reword the command table (240-241)
    `forge authentication login|status` -> `forge auth ...`.
  - `docs/developer/cli_style_guidelines.md`: update the enumerated alias set (45) to `ext`/`sess`/`mem`/`cfg` only;
    drop the `extensions` shim mention (47); record the D6 alias rule; clear the alias placeholder.
  - `tests/src/cli/test_command_tree_invariants.py:135`: `JSON_MISSING_ALLOWLIST` entry `forge authentication status` ->
    `forge auth status` (canonical-path keyed; otherwise `test_read_leaves_expose_json` fails). Slice 07 also drains
    this entry's `--json` debt — coordinate the two touches.
  - Shim removal in tests: `tests/src/cli/test_startup_queue.py` (44,112,132,175,188,208) and
    `tests/integration/cli/test_startup_queue_integration.py` (60,72,148) change CLI string `"extensions"` ->
    `"extension"`. **Do NOT touch** `tests/src/install/test_version.py`'s `from forge.cli.extensions import extensions`
    — that is the Python module/symbol path, not the CLI alias string. `tests/src/cli/test_auth.py` already invokes the
    (soon-canonical) `auth` form and should stay green; `tests/src/cli/test_memory.py:836` `mem` alias test stays.
  - QA checklist: `src/skills/qa/resources/checklist/3-authentication.md` (~15 `forge authentication ...` ->
    `forge auth ...`) and `src/skills/qa/resources/checklist.md:44,46`.
  - Old `forge authentication ...` and `forge extensions ...` paths return Click `No such command` (clean break, no
    tombstone). Update `_ALIASES`, `_DISPLAY_ALIASES`, `cli_reference.md`, and the style guide alias section together.

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
| Supervisor split            | session with supervisor          | `forge policy supervisor {status,set,off,on,reload,evaluate}` work; `supervise` exits 2; `LEAF_NAMING_ALLOWLIST` `{}`                                                                                                                              | `tests/src/cli/test_policy.py`                               |
| `session context` removed   | n/a                              | `forge session context` exits 2 "No such command"; `test_session_context.py` deleted                                                                                                                                                               | (removal)                                                    |
| Error markup drained        | CLI source scan                  | `CLI_ERROR_MARKUP_ALLOWLIST` `{}`; all 10 terminal tips routed (incl. 2 `ClickException`); `proxy_costs.py:132` + `session_fork.py:467` reworded; tip guard fails on `Tip:` in CLI source, allowlist = exactly the 3 `direct_commands.py` payloads | `tests/src/cli/test_output.py`                               |

## Docs and verification

- [x] Fix debt-ledger breadcrumb rot: provenance comment at `tests/src/cli/test_command_tree_invariants.py:7` now points
  at `docs/board/doing/forge_cli_cleanup/card.md` (was `proposed/`). `test_output.py:142` carries no path, so it needed
  no change. (Two stale cross-links remain in `docs/board/proposed/rewind_resume_strategy/card.md:27,260` — a different
  card's content; tracked separately, not fixed here.)
- [ ] Update `docs/cli_reference.md` for every moved/removed/added surface (drop the `session context` note; re-document
  aliases per D6).
- [ ] Update relevant `docs/end-user/*` guides (`hook.md` per D5, `proxy.md`/`session.md`/`memory.md` for moves).
- [ ] Update `docs/developer/cli_style_guidelines.md`: record the config-object verb vocabulary (D7), the stream guard
  once wired, the alias rule (D6), and remove "settled in the forge_cli_cleanup card" placeholders as each lands. (D7
  config-object vocab done 2026-06-23, Slice 08; stream guard done Slice 07; **D6 alias rule still pending Slice 05** —
  box stays unchecked until D6 lands.)
- [x] Update `docs/design.md`/`cli_reference.md` ownership tables if command ownership changes (telemetry, memory
  split). Done for both shipped moves: design.md §4.0/§3.x and cli_reference reflect `forge session memory` +
  `forge session transfer`; verified no stale `forge memory enable|disable|status|report` / bare `forge transfer <verb>`
  in the four normative docs (one intentional "(former `forge memory report show`)" breadcrumb kept).
- [x] Add a `change_log.md` entry per shipped slice naming the moved live commands (`forge activity` →
  `forge telemetry activity`, etc.).
- [ ] Run targeted CLI tests for old/new paths, help text, `--json` shape, and stream behavior after each slice.
- [ ] `make pre-commit` before closeout; promote durable taxonomy/alias decisions to `impl_notes.md` after review.

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
