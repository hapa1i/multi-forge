# Checklist -- cli_style_ux_compliance Step 3

**Branch**: `feat/cli-style-ux-compliance` - **Card**: [`card.md`](card.md)

**Current focus**: This card is the **Step 3 coordinator/index**, not one code change. A1 (PR #70), the B1 backend slice
(PR #71), **S1/A2+A4**, **S2/A5**, **S4/B2-B5**, **S5/C1**, and **S3/A3** are done. **C2/OQ-2** and **C3/OQ-3** now have
draft decisions recorded for maintainer review: C2 is a public terminology cleanup only, with the deeper backend
instance identity migration split to
[`todo/backend_instance_identity_model`](../../todo/backend_instance_identity_model/card.md). **C2 still needs an exit
before this card closes:** either ship the narrow public wording pass here, or explicitly defer that wording pass to its
own follow-up. C3 is a record-only "do not globally normalize scope order" decision. Slices graduate out individually;
this checklist stays the durable index. **Status: C2/C3 DECISIONS DRAFTED FOR REVIEW (docs only; no implementation in
this stop).**

**Guiding rules**: `docs/developer/cli_style_guidelines.md` is the CLI shape authority (Output Streams, destructive-verb
shape, read-leaf `--json`, `Use --flag` / `Run '<cmd>'` tip forms); `docs/developer/coding_standards.md` §5 governs
research-preview clean breaks (removed flags rely on Click's native "No such option", named in the changelog);
`docs/developer/board_contract.md` governs lane semantics.

## Grounded Base

Re-verified on `main`, 2026-07-03 -- the card's original line numbers predate PR #69/#70/#71 and have drifted. S1
resolved A2/A4; S2 resolved A5; S4 resolved B5; S5/C1 resolved C1; S3 resolved A3. Every A/B anchor and C1 is shipped;
C2/C3 are now decision-recorded for review.

| Item | Site (verified now)                                                                                                                  | Card's stale ref        | Current behavior -> intended fix                                                                                                                                                                     |
| ---- | ------------------------------------------------------------------------------------------------------------------------------------ | ----------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| A2   | `session_lifecycle.py:909`                                                                                                           | `:1189`                 | `--model` help literal ends `...claude-sonnet-4-6[1m])` (stray ANSI) -> delete `[1m]`                                                                                                                |
| A3   | `policy.py:282` (`enable`), warn `:291`, `return` `:293`                                                                             | `:275-278`              | **Resolved in S3**: bare `enable` fails loud (`print_error_with_tip` -> stderr, exit 1); `--bundle` required. Restore-from-intent deferred to the `%policy enable` dispatcher (design_workflows.md). |
| A4   | `search.py:383` (`clean_cmd(yes)`), preview `:401-402`, tip `:408`                                                                   | `:381`                  | no `as_json`; `find_missing()` preview + `print_tip("Use --yes to prune.")` -> add `--json` (dest `as_json`), shape matching `forge clean`                                                           |
| A5   | `logs.py:260` (`logs_cmd(clean, older_than)`); `--clean` `:252`; `_clean_logs` `:280`; `_show_logs` `:283`                           | `:247,265,270,275`      | `--clean` is_flag deletes immediately (no `--yes`, no preview); no `--json` on the read surface -> split into `logs show [--json]` + `logs clean [--older-than N] --yes`                             |
| B5   | `session_lane.py` `--runtime` `:122` / `--backend` `:123`, `set_cmd` `:125`, raw re-print `:144`; origin `consumer_lanes.py:115,137` | `:100,115,141` / `:102` | **Resolved in S4**: `session lane set --help` and invalid-lane errors enumerate `valid_lanes(consumer)` (default + allowed, gate-filtered), including the default lane.                              |
| C1   | `activity.py:37` `--days`/`-d` default 30; `--all` `:38`; `activity_cmd` `:39`                                                       | (card)                  | **Resolved in S5/C1**: `--period today\|week\|month\|all` replaces `--days`/`--all`; old flags exit 2 via Click "No such option".                                                                    |

**Streams already correct** (do not touch): B5's routing goes through `err_console` (`session_lane.py:144`); the A1
sweep (PR #70) already flipped the systemic stdout leaks. Batch B is help/message quality only, zero stream change.

## Precedents to mirror

- **A4 `--json`**: `forge clean --json` shape + the Slice-07 read-JSON pattern (`_output_results(..., as_json=)` already
  in `search.py:243`). Reuse `find_missing()` (already called at `search.py:401-402`) for the preview count.
- **A5 logs group**: forge_cli_cleanup **Slice 09** (`session clean`/`search clean` -> preview-default + `--yes`) and
  **Slice 12** (F13 `no_args_is_help=True` groups; the `shadow` single-leaf -> 2-leaf drain). Keep `logs` in `main.py`
  `_EXEMPT_SUBCOMMANDS` / `_SESSION_CLEANUP_EXEMPT` -- move the exemption to the **group**.
- **C1 `--period`**: `trace list`, `costs show`, `proxy audit` already take `--period` -- copy that `click.Choice`.
- **B5 error quality**: the file's own consumer-error already models the target (`Unknown consumer {raw!r}` + a valid
  list at `:65`); make the lane-error path symmetric.

## Guard tests each slice must satisfy or extend (`tests/src/cli/test_command_tree_invariants.py`)

- `test_read_leaves_expose_json` (`:127`) -- `_READ_LEAVES = {catalog, list, report, show, status, profiles, diff}`,
  `JSON_MISSING_ALLOWLIST = set()` (**empty**). Adding leaf `logs show` (A5) **forces** `--json` on it.
- `test_clean_verbs_preview_by_default` (`:176`) -- every leaf named `clean` carries `--yes`, never `--dry-run`. Adding
  `logs clean` (A5) is **forced** into this shape. (Note: A4's `search clean` already complies; the guard keys on the
  leaf *name*, not the `--json` add.)
- `test_no_single_leaf_groups` (`:70`) -- the new `logs` group needs >=2 leaves (`show` + `clean`) -> satisfied.
- `test_json_option_dest_is_as_json` (`:53`) -- every `--json` binds dest `as_json` (A4, A5, C1 outputs).
- **A4 gap (record it):** `clean` is **not** in `_READ_LEAVES`, so no guard forces `search clean --json`; the slice must
  add its own stable-shape test or a regression re-slips silently.

## Phase 0 -- Board activation

- [x] Create branch `feat/cli-style-ux-compliance` from current `main`.
- [x] Move card directory `proposed/cli_style_ux_compliance -> doing/cli_style_ux_compliance`.
- [x] Update card status from proposed index to active Step 3 coordinator.
- [x] Update stale board links that still pointed at `proposed/cli_style_ux_compliance`.
- [x] Commit the board activation (rename + this expanded checklist) separately before the first code slice.

## Phase 1 -- Slice plan (execute by review concern, not as one change)

| Slice  | Items          | Review concern                                     | Ships / gating                                                        |
| ------ | -------------- | -------------------------------------------------- | --------------------------------------------------------------------- |
| **S1** | A2, A4         | Trivial CLI correctness (2 single-file edits)      | Ship first; lowest risk                                               |
| **S2** | A5             | `logs` group redesign (behavior + clean break)     | After S1; needs docs + changelog                                      |
| **S3** | A3             | `policy enable` fail-loud (clean break)            | **Done** -- OQ-1 resolved: fail loud; `%` dispatcher restore deferred |
| **S4** | B2, B3, B4, B5 | Help & error-message pass (+1 machine-output item) | Ship anytime; mostly help-snapshot; B4-json updates a pinning test    |
| **S5** | C1, C2, C3     | Research-preview clean breaks                      | C1 shipped; C2/C3 decisions drafted for review before any more code   |

- [ ] Confirm the slice split with the maintainer (or proceed S1 -> S2 -> S4, holding S3/S5 on their gates).

## Phase 2 -- Slice S1: A2 + A4 (trivial correctness)

- [x] **A2** -- delete `[1m]` from the `--model` help string (`session_lifecycle.py:909`). **Assertion:**
  `forge session start --help` renders `...claude-sonnet-4-6)` with no `[1m]`; a help-render test asserts `[1m]` absent.
  **Coupling:** `session_op_layer_extraction` will refactor this file -- land A2 first as a one-char fix; do not block
  on that card (card [Sequencing](card.md#sequencing--coupling)).
- [x] **A4** -- add `--json` (dest `as_json`) to `search clean_cmd` (`search.py:383`); emit a stable
  preview/pruned-count shape matching `forge clean --json`, human path unchanged. **Assertion:** `search clean --json`
  prints parseable JSON on **stdout**, diagnostics on **stderr**, and a preview run reports the orphan count without
  pruning; new stable-shape test added (no guard forces this -- see A4 gap above).
- [x] S1 verification:
  `uv run pytest tests/src/cli/test_search.py tests/src/cli/test_command_tree_invariants.py tests/src/cli/test_session_commands.py::TestSessionStart::test_start_help_shows_optional_name -q`
  passed (39 tests, including `search clean --json` error-to-stderr coverage); `make pre-commit` passed. The first
  pre-commit run surfaced and fixed a narrow mypy package-export issue for `forge.core.runtime.codex_preflight_cache`
  (committed separately as `152a053a`); `docs/cli_reference.md` + `docs/end-user/search.md` synced for
  `search clean --json`; mdformat also reflowed board prose.

## Phase 3 -- Slice S2: A5 (`logs` group redesign)

- [x] Promote `logs` to a group with `no_args_is_help=True` (Slice-12 F13 pattern) exposing two leaves:
  `forge logs show [--json]` (read/status) and `forge logs clean [--older-than N] --yes` (destructive, preview-default).
  **Assertion:** `forge logs` prints help + exits 2 (group); both leaves resolve.
- [x] `logs show --json`: stable shape over locations/retention/counts (from `_show_logs`). **Assertion:**
  `test_read_leaves_expose_json` passes with `show` present; `--json` is valid JSON on stdout, stderr empty.
- [x] **Add a preview/count capability first** -- `_remove_files` (`logs.py:181`) only deletes (`f.unlink()`, `:210`);
  it has no dry mode. Add a `preview: bool` param (or a sibling counter) that runs the same `older_than` + active-skip
  filters as `_try_remove` (`:202-213`) but skips `unlink`, returning the would-remove count. **Assertion:** the preview
  count equals what a real clean removes; no file is unlinked in preview.
- [x] `logs clean`: preview by default (report the would-remove count via the new preview helper), `--yes` mutates; keep
  `--older-than N` (>=1 validation) as a leaf option. **Assertion:** `test_clean_verbs_preview_by_default` passes;
  `logs clean` without `--yes` deletes nothing; `logs clean --yes` removes files.
- [x] Clean break: the bare-leaf `--clean` / `--older-than` flags are removed. **Assertion:** `forge logs --clean` and
  `forge logs --older-than 7` exit 2 (Click "No such option"); clean-break guard test added.
- [x] Keep the `main.py` cleanup exemption: move `logs` in `_EXEMPT_SUBCOMMANDS` / `_SESSION_CLEANUP_EXEMPT` to cover
  the **group**. **Assertion:** session-cleanup invariants still pass.
- [x] **Absorb B4's logs tip here**: `logs clean --older-than` validation failure prints a recovery tip via
  `forge.cli.output` (`Use --older-than <days>` form). **Assertion:** invalid `--older-than 0` errors with a tip on
  stderr.
- [x] Docs sync: `cli_reference.md` System table (`forge logs` -> group rows), `end-user/*` if `logs` usage documented;
  bundled QA/walkthrough skill guidance also moved to `logs show` / `logs clean --yes`.
- [x] Changelog entry (feature + clean break naming the removed bare flags).
- [x] S2 verification:
  `uv run pytest tests/src/cli/test_logs_command.py tests/src/cli/test_command_tree_invariants.py tests/src/cli/test_output_streams.py -q`
  passed (99 tests); `make pre-commit` passed.
- **S2 follow-up observation:** `logs clean` intentionally remains human-only; unlike `logs show`, no guard currently
  requires `--json` on clean leaves. If scriptable log cleanup becomes useful, mirror the `forge clean --json` /
  `search clean --json` shape in a later slice.

## Phase 4 -- Slice S3: A3 (`policy enable` fail-loud) -- **DONE** (OQ-1 resolved: fail loud)

- [x] **OQ-1 resolved: fail loud** (not restore-from-intent). Rationale: the CLI is the explicit/scriptable surface, so
  it requires `--bundle`; restore-from-intent belongs on the interactive `%policy enable` shortcut -- a *separate*
  parser (`hooks/direct_commands.py` writes `overrides`; the CLI writes `intent`) where it is still `(planned)`. This
  does not preempt `accidental_complexity_cleanup`'s WorkflowPolicy decision: that card owns the `%` dispatcher restore
  path, not the CLI's require-a-bundle guard.
- [x] Implemented at `policy.py:290-300`: replaced the stdout warn + `return` (exit 0) with `print_error_with_tip` on
  **stderr** + `sys.exit(1)`. **Assertion:** bare `policy enable` prints `Error:` + `Tip:` naming
  `tdd`/`coding_standards` and exits 1; stdout is empty (verified with `2>/dev/null`).
- [x] Doc split: `design_workflows.md` "Re-enable enforcement" now says terminal `forge policy enable` requires an
  explicit `--bundle`, scoping restore-from-intent to the `%policy enable` shortcut (previously implied CLI parity).
- [x] Verification: new `tests/src/cli/test_policy_enable.py` (fail-loud names both bundles + help choices); happy-path
  `enable --bundle tdd` and the `%` dispatcher/M7 regression suites unaffected. Repro:
  `uv run pytest tests/src/cli/test_policy_enable.py tests/regression/test_bug_policy_ambiguous_session.py tests/src/cli/test_user_prompt_dispatcher.py tests/regression/test_bug_m7_policy_overrides.py`
  -> 94 passed. CLI tip/error guards pass. `make pre-commit` at commit.

## Phase 5 -- Slice S4: Batch B (help & error-message pass; one machine-output exception)

> Mostly `help=` / docstring / error-message edits (help-render + snapshot acceptance). **One exception:** the
> `telemetry activity --json` tip (B4-json below) touches machine output and its pinning test -- it is *not* help-only.
> The card's B2/B3/B4 tables are already file:line-cited -- re-confirm each anchor at edit time.

- [x] **B2** -- normalize wording drift where the format genuinely matches: one canonical `--json` help form (>=5
  variants today); unify `workflow --check` verdict terminology; add the missing `(alternative to positional)` on
  `workflow panel --prompt` (`workflow.py`); align `codex start` vs `session start` `--sandbox` wording; unify
  `memory shadows` scope help; reuse the detailed `--scope` text on `extension sync/disable/status`; reword the
  `model backend reconcile` tip to `Use --flag` form; document `config show --json` shape. **Assertion:** each edited
  `--help` renders the canonical text; help-snapshot tests updated.
- [x] **B3** -- fill thin one-liners / hidden enums / undocumented options: `model backend start --port`
  source-vs-adapter hint plus `model backend stop` runtime-id discovery note; `search query` phrase-syntax note;
  `config set` nested-key examples (`statusline.cost_mode=...`); `session lane set` required-ness;
  `memory shadows --for` format; `workflow list-models --available` "ready" definition; `runtime preflight` enum +
  `runtime list` cross-ref; `memory track --writers/--intent` format. **Assertion:** each option's semantics are visible
  in `--help`.
- [x] **B4** -- add examples + next-step tips (help-only): `model backend start/stop`, `search query` (phrase),
  `workflow panel --context resume:<uuid>` (Forge name vs Claude UUID), `session lane set/clear`. (The
  `telemetry activity --json` tip is split into B4-json below; the `logs --older-than` tip moved to S2.) **Assertion:**
  each cited leaf shows a valid example in `--help`.
- [x] **B4-json (machine-output, NOT help-only)** -- `telemetry activity --json` drops the human-mode
  `Run 'forge session list'` tip. The error object is `{"error": str(e)}` on **stderr** (already `err=True`,
  `activity.py:58`), pinned by `test_activity.py::test_not_found_json`. Restoring the tip is a machine-output decision:
  add a `tip` field to the JSON object (shape change) vs a separate stderr line (risks mixing non-JSON into a stderr
  JSON reader). **Either way, update `test_not_found_json`.** Couples with C1 (same `activity.py` output) -- sequence
  together. **Assertion:** the tip is reachable in `--json` mode; stdout stays clean for a `jq` consumer; the pinning
  test reflects the chosen shape.
- [x] **B5** -- `session lane set` lane discovery + actionable invalid-lane error. Enumerate `valid_lanes(consumer)`
  (`core/lanes.py:111` -- `default_lane` + `allowed_lanes`, gate-filtered; **not** bare `allowed_lanes`, which drops the
  default lane the user is most likely on) in the `set` help (or a `--list`); make the `LaneError` say
  `valid lanes for <consumer>: <runtime/backend/model>, ...`. `session_lane.py` already imports from `forge.core.lanes`,
  so add `valid_lanes` to that import. **Assertion:** `session lane set --consumer team_supervisor --runtime codex` (no
  codex lane) errors on stderr naming the valid lanes **including the default**, not a raw `LaneError`; streams
  unchanged (still `err_console`).
- [x] S4 verification: focused CLI suite passed (171 tests) on 2026-07-03; `make pre-commit` passed.
- **S4 review decisions:** keep `telemetry activity --json`'s `tip` field activity-specific for now; promoting
  machine-readable recovery tips would be a separate convention/doc sweep across JSON error surfaces. Leave command
  references in help prose as existing Click docstring literals; recovery tips still follow the `Run '<cmd>'`
  convention.

## Phase 6 -- Slice S5: Batch C (research-preview clean breaks) -- C2/C3 review

- [x] **C1** -- align `telemetry activity` `--days` -> `--period [today|week|month|all]` (`activity.py:37`), copying the
  `trace list`/`costs show` `Choice`. **Decision: clean break** (remove `--days`), per `coding_standards.md §5`
  (research preview, no default shims) and to match the sibling clean-break pattern -- not a deprecation window.
  **Assertion:** `--period week` works; removed `--days` exits 2 (Click "No such option"); changelog entry names the
  replacement.
- [ ] **C2** -- backend metavar standardization -- **OQ-2 draft decision recorded; awaiting review before
  implementation**. Public CLI terminology should use first-class CLI nouns: `backend` for the configured inference
  target users see under `forge model backend`, `backend instance` for a concrete usable endpoint/process, and `adapter`
  for implementation/config families such as `litellm`. Avoid user-facing `source id` and avoid `runtime instance` under
  `forge model backend` because `runtime` already means the agent/frontend runtime (`codex`, `claude_code`).
  **Boundary:** leave internal/storage/JSON names (`ModelSource.id`, `source_id`, `runtime_instance`,
  `BackendInstance.backend_id`) unchanged in this UX slice; the real domain/schema migration is split to
  [`todo/backend_instance_identity_model`](../../todo/backend_instance_identity_model/card.md), but that domain card
  does **not** close C2's public wording pass. **Exit:** after review, either ship the help/metavar/table/prose wording
  pass in this card with verification, or create/link a separate public-wording follow-up and mark C2 explicitly
  deferred. **Assertion (if actioned):** help/metavars/tables communicate accepted values as backend/backend-instance
  concepts; no storage or JSON contract rename sneaks in.
- [ ] **C3** -- `--scope` value-set/ordering canonicalization -- **OQ-3 draft decision recorded; likely no code**. Do
  not globally canonicalize scope value order. The observed families are semantic: session/cleanup uses
  `workspace|project|all`; memory/shadows/session-memory uses `project|workspace|all`; search has no workspace scope
  (`project|all`); extension install uses `local|project|user`; Codex status reports `user|project|local` to mirror
  runtime-install reporting. **Assertion (if actioned):** only local help drift inside a semantic family is normalized;
  no arbitrary cross-family reorder.
- [x] C2/C3 decision split recorded in this checklist and in [`card.md`](card.md); follow-up domain card created in
  `todo/`.
- [x] Changelog entry per shipped break (`coding_standards.md §5`).
- [x] S5/C1 verification: focused activity/stream tests passed (23 tests), command-tree invariants passed (9 tests),
  targeted activity integration passed (1 test), and `make pre-commit` passed on 2026-07-03.

## Decisions from open questions

- **OQ-1 (S3/A3) -- RESOLVED 2026-07-03: fail loud.** `policy enable` requires `--bundle` (bare invocation errors
  non-zero with a tip). Restore-from-intent is deferred to the `%policy enable` dispatcher -- a separate parser, still
  `(planned)` in `design_workflows.md` -- so it does not preempt `accidental_complexity_cleanup`'s WorkflowPolicy work.
- **OQ-2 (gates C2) -- DRAFT RESOLUTION 2026-07-03:** yes, rename public CLI wording where it leaks `source` or
  overloads `runtime`, but keep this slice help/metavar/table-only. The desired long-term abstraction is all model
  backends as backend instances (remote singleton names may be instance ids for now; managed local LiteLLM instances
  already have ids like `litellm-4000`), and that migration is split to
  [`todo/backend_instance_identity_model`](../../todo/backend_instance_identity_model/card.md).
- **OQ-3 (gates C3) -- DRAFT RESOLUTION 2026-07-03:** the observed `--scope` divergences are semantic families, not one
  accidental enum. Do not globally reorder; only normalize local drift inside a family.

## Acceptance tests

| Test                       | Fixture                                               | Assertion                                                                       | Test File                                       |
| -------------------------- | ----------------------------------------------------- | ------------------------------------------------------------------------------- | ----------------------------------------------- |
| A2 help artifact gone      | `session start --help`                                | rendered help contains no `[1m]`                                                | `tests/src/cli/test_session_commands.py`        |
| A4 search clean `--json`   | index with orphaned docs                              | `search clean --json` -> parseable JSON on stdout; preview only                 | `tests/src/cli/test_search.py`                  |
| A5 logs read `--json`      | logs dir populated                                    | `logs show --json` valid JSON on stdout; stderr empty                           | `tests/src/cli/test_logs_command.py`            |
| A5 logs clean preview      | logs dir populated                                    | `logs clean` deletes nothing; `logs clean --yes` removes files                  | `tests/src/cli/test_logs_command.py`            |
| A5 old flags clean break   | `logs --clean` / `logs --older-than 7`                | exit 2 (Click "No such option")                                                 | `tests/src/cli/test_logs_command.py`            |
| A5 tree invariants         | full command tree                                     | `logs show` guarded-read-JSON; `logs clean` `--yes`-preview                     | `tests/src/cli/test_command_tree_invariants.py` |
| A3 no warn-and-exit-0      | bare `policy enable`                                  | fail loud: `Error`+`Tip` on stderr, exit 1, stdout empty                        | `tests/src/cli/test_policy_enable.py`           |
| B5 invalid lane enumerates | `lane set --consumer team_supervisor --runtime codex` | stderr names valid lanes for the consumer, not raw `LaneError`                  | `tests/src/cli/test_session_lane.py`            |
| C1 `--period` clean break  | `telemetry activity --days 7`                         | `--period week` works; `--days` exits 2                                         | `tests/src/cli/test_activity.py`                |
| B4-json activity tip       | `telemetry activity ghost --json` (missing)           | tip reachable in `--json`; stdout clean for `jq`; `test_not_found_json` updated | `tests/src/cli/test_activity.py`                |
| Help wording (B2/B3/B4)    | `forge <cmd> --help`                                  | canonical wording/examples appear; no internal vocab leak                       | help-render / snapshot tests                    |

## Closeout items

- [ ] All selected slices ticked with verification recorded (each slice: focused suite + `make pre-commit` clean).
- [ ] C2 has a closure state before moving this card to `done/`: either the public wording pass shipped here, or it was
  explicitly deferred to a named follow-up separate from `backend_instance_identity_model`.
- [ ] Integration: none expected (host CLI + help rendering; no `claude -p`/Docker path). Confirm and record.
- [ ] Docs synced for behavior changes: `cli_reference.md` (A5 logs group, C1 `--period`), `design_appendix.md` /
  `end-user/*` where the changed surface is documented.
- [ ] `docs/board/change_log.md` updated per shipped slice (S2/S3/S5 name their clean breaks; B pass is one polish
  entry).
- [ ] cli_style index (this card) annotated per shipped slice; refuted-candidate list in `card.md` preserved.
- [ ] Durable lessons promoted to `docs/board/impl_notes.md` only after human review.
- [ ] Move card `doing/ -> done/` when the resumed cli_style scope ships or is deliberately split into new active cards.
