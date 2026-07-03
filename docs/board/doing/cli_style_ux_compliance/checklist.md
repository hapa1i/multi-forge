# Checklist -- cli_style_ux_compliance Step 3

**Branch**: `feat/cli-style-ux-compliance` - **Card**: [`card.md`](card.md)

**Current focus**: This card is the **Step 3 coordinator/index**, not one code change. A1 (PR #70) and the B1 backend
slice (PR #71) already shipped; what remains is **A2-A5, B2-B5, C1-C3**, executed as **focused slices grouped by review
concern** (card [Sequencing & coupling](card.md#sequencing--coupling)). Slices graduate out individually; this checklist
stays the durable index. **Status: PLAN FOR REVIEW (re-grounded on `main` 2026-07-03; no code written yet).**

**Guiding rules**: `docs/developer/cli_style_guidelines.md` is the CLI shape authority (Output Streams, destructive-verb
shape, read-leaf `--json`, `Use --flag` / `Run '<cmd>'` tip forms); `docs/developer/coding_standards.md` §5 governs
research-preview clean breaks (removed flags rely on Click's native "No such option", named in the changelog);
`docs/developer/board_contract.md` governs lane semantics.

## Grounded base (re-verified on `main`, 2026-07-03 -- the card's line numbers predate PR #69/#70/#71 and have drifted)

| Item | Site (verified now)                                                                                                                  | Card's stale ref        | Current behavior -> intended fix                                                                                                                                                                                                                                |
| ---- | ------------------------------------------------------------------------------------------------------------------------------------ | ----------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| A2   | `session_lifecycle.py:909`                                                                                                           | `:1189`                 | `--model` help literal ends `...claude-sonnet-4-6[1m])` (stray ANSI) -> delete `[1m]`                                                                                                                                                                           |
| A3   | `policy.py:282` (`enable`), warn `:291`, `return` `:293`                                                                             | `:275-278`              | bare `enable` prints `[yellow]Warning:[/yellow] No bundles specified` then `return` (exit 0) -> fail loud OR restore-from-intent (**gated**)                                                                                                                    |
| A4   | `search.py:383` (`clean_cmd(yes)`), preview `:401-402`, tip `:408`                                                                   | `:381`                  | no `as_json`; `find_missing()` preview + `print_tip("Use --yes to prune.")` -> add `--json` (dest `as_json`), shape matching `forge clean`                                                                                                                      |
| A5   | `logs.py:260` (`logs_cmd(clean, older_than)`); `--clean` `:252`; `_clean_logs` `:280`; `_show_logs` `:283`                           | `:247,265,270,275`      | `--clean` is_flag deletes immediately (no `--yes`, no preview); no `--json` on the read surface -> split into `logs show [--json]` + `logs clean [--older-than N] --yes`                                                                                        |
| B5   | `session_lane.py` `--runtime` `:122` / `--backend` `:123`, `set_cmd` `:125`, raw re-print `:144`; origin `consumer_lanes.py:115,137` | `:100,115,141` / `:102` | `--runtime`/`--backend` are free `default=None` strings (no `Choice`, no enum, no discovery); invalid **lane** re-prints raw `LaneError` while invalid **consumer** gets a tip (`:65`) -> enumerate `valid_lanes(consumer)` (default + allowed) in help + error |
| C1   | `activity.py:37` `--days`/`-d` default 30; `--all` `:38`; `activity_cmd` `:39`                                                       | (card)                  | `--days` diverges from sibling telemetry `--period` -> align to `--period [today\|week\|month\|all]`                                                                                                                                                            |

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
- [ ] Commit the board activation (rename + this expanded checklist) separately before the first code slice.

## Phase 1 -- Slice plan (execute by review concern, not as one change)

| Slice  | Items          | Review concern                                     | Ships / gating                                                       |
| ------ | -------------- | -------------------------------------------------- | -------------------------------------------------------------------- |
| **S1** | A2, A4         | Trivial CLI correctness (2 single-file edits)      | Ship first; lowest risk                                              |
| **S2** | A5             | `logs` group redesign (behavior + clean break)     | After S1; needs docs + changelog                                     |
| **S3** | A3             | `policy enable` fail-loud / restore-from-intent    | **BLOCKED on OQ-1**; coordinate with `accidental_complexity_cleanup` |
| **S4** | B2, B3, B4, B5 | Help & error-message pass (+1 machine-output item) | Ship anytime; mostly help-snapshot; B4-json updates a pinning test   |
| **S5** | C1, C2, C3     | Research-preview clean breaks                      | Batch separately; changelog per break; C2 gated on OQ-2, C3 on OQ-3  |

- [ ] Confirm the slice split with the maintainer (or proceed S1 -> S2 -> S4, holding S3/S5 on their gates).

## Phase 2 -- Slice S1: A2 + A4 (trivial correctness)

- [ ] **A2** -- delete `[1m]` from the `--model` help string (`session_lifecycle.py:909`). **Assertion:**
  `forge session start --help` renders `...claude-sonnet-4-6)` with no `[1m]`; a help-render test asserts `[1m]` absent.
  **Coupling:** `session_op_layer_extraction` will refactor this file -- land A2 first as a one-char fix; do not block
  on that card (card [Sequencing](card.md#sequencing--coupling)).
- [ ] **A4** -- add `--json` (dest `as_json`) to `search clean_cmd` (`search.py:383`); emit a stable
  preview/pruned-count shape matching `forge clean --json`, human path unchanged. **Assertion:** `search clean --json`
  prints parseable JSON on **stdout**, diagnostics on **stderr**, and a preview run reports the orphan count without
  pruning; new stable-shape test added (no guard forces this -- see A4 gap above).
- [ ] S1 verification: `uv run pytest tests/src/cli/test_search.py tests/src/cli/test_command_tree_invariants.py -q`;
  `make pre-commit` clean.

## Phase 3 -- Slice S2: A5 (`logs` group redesign)

- [ ] Promote `logs` to a group with `no_args_is_help=True` (Slice-12 F13 pattern) exposing two leaves:
  `forge logs show [--json]` (read/status) and `forge logs clean [--older-than N] --yes` (destructive, preview-default).
  **Assertion:** `forge logs` prints help + exits 2 (group); both leaves resolve.
- [ ] `logs show --json`: stable shape over locations/retention/counts (from `_show_logs`). **Assertion:**
  `test_read_leaves_expose_json` passes with `show` present; `--json` is valid JSON on stdout, stderr empty.
- [ ] **Add a preview/count capability first** -- `_remove_files` (`logs.py:181`) only deletes (`f.unlink()`, `:210`);
  it has no dry mode. Add a `preview: bool` param (or a sibling counter) that runs the same `older_than` + active-skip
  filters as `_try_remove` (`:202-213`) but skips `unlink`, returning the would-remove count. **Assertion:** the preview
  count equals what a real clean removes; no file is unlinked in preview.
- [ ] `logs clean`: preview by default (report the would-remove count via the new preview helper), `--yes` mutates; keep
  `--older-than N` (>=1 validation) as a leaf option. **Assertion:** `test_clean_verbs_preview_by_default` passes;
  `logs clean` without `--yes` deletes nothing; `logs clean --yes` removes files.
- [ ] Clean break: the bare-leaf `--clean` / `--older-than` flags are removed. **Assertion:** `forge logs --clean` and
  `forge logs --older-than 7` exit 2 (Click "No such option"); clean-break guard test added.
- [ ] Keep the `main.py` cleanup exemption: move `logs` in `_EXEMPT_SUBCOMMANDS` / `_SESSION_CLEANUP_EXEMPT` to cover
  the **group**. **Assertion:** session-cleanup invariants still pass.
- [ ] **Absorb B4's logs tip here**: `logs clean --older-than` validation failure prints a recovery tip via
  `forge.cli.output` (`Use --older-than <days>` form). **Assertion:** invalid `--older-than 0` errors with a tip on
  stderr.
- [ ] Docs sync: `cli_reference.md` System table (`forge logs` -> group rows), `end-user/*` if `logs` usage documented.
- [ ] Changelog entry (feature + clean break naming the removed bare flags).

## Phase 4 -- Slice S3: A3 (`policy enable` fail-loud) -- **BLOCKED on OQ-1**

- [ ] Resolve **OQ-1** first: make `--bundle` **required** (fail non-zero), OR implement the `design_workflows.md §3.6`
  "restore configured bundles from intent" behavior. Coordinate with `accidental_complexity_cleanup`'s
  WorkflowPolicy-boundary item (both touch `policy enable`; an A3 "require --bundle" fix must not preempt that card's
  demote-vs-graduate decision -- card [Sequencing](card.md#sequencing--coupling)).
- [ ] Implement the resolved behavior at `policy.py:291-293`. **Assertion:** no missing-input path warns-and-exits-0;
  bare `policy enable` either errors non-zero with a tip, or restores intent bundles and reports what it enabled.
- [ ] Verification: add coverage in `tests/src/cli/test_policy_status.py` or a focused policy-enable test -- there is
  **no** existing `policy enable` CLI invocation today (the file's `enable` hits are all `PolicyIntent(enabled=True)`
  constructions, not CLI calls); `make pre-commit` clean.

## Phase 5 -- Slice S4: Batch B (help & error-message pass; one machine-output exception)

> Mostly `help=` / docstring / error-message edits (help-render + snapshot acceptance). **One exception:** the
> `telemetry activity --json` tip (B4-json below) touches machine output and its pinning test -- it is *not* help-only.
> The card's B2/B3/B4 tables are already file:line-cited -- re-confirm each anchor at edit time.

- [ ] **B2** -- normalize wording drift where the format genuinely matches: one canonical `--json` help form (>=5
  variants today); unify `workflow --check` verdict terminology; add the missing `(alternative to positional)` on
  `workflow panel --prompt` (`workflow.py`); align `codex start` vs `session start` `--sandbox` wording; unify
  `memory shadows` scope help; reuse the detailed `--scope` text on `extension sync/disable/status`; reword the
  `model backend reconcile` tip to `Use --flag` form; document `config show --json` shape. **Assertion:** each edited
  `--help` renders the canonical text; help-snapshot tests updated.
- [ ] **B3** -- fill thin one-liners / hidden enums / undocumented options: `model backend start/stop` `--port`
  source-vs-adapter hint; `search query` phrase-syntax note; `config set` nested-key examples
  (`statusline.cost_mode=...`); `session lane set` required-ness; `memory shadows --for` format;
  `workflow list-models --available` "ready" definition; `runtime preflight` enum + `runtime list` cross-ref;
  `memory track --writers/--intent` format. **Assertion:** each option's semantics are visible in `--help`.
- [ ] **B4** -- add examples + next-step tips (help-only): `model backend start/stop`, `search query` (phrase),
  `workflow panel --context resume:<uuid>` (Forge name vs Claude UUID), `session lane set/clear`. (The
  `telemetry activity --json` tip is split into B4-json below; the `logs --older-than` tip moved to S2.) **Assertion:**
  each cited leaf shows a valid example in `--help`.
- [ ] **B4-json (machine-output, NOT help-only)** -- `telemetry activity --json` drops the human-mode
  `Run 'forge session list'` tip. The error object is `{"error": str(e)}` on **stderr** (already `err=True`,
  `activity.py:58`), pinned by `test_activity.py::test_not_found_json`. Restoring the tip is a machine-output decision:
  add a `tip` field to the JSON object (shape change) vs a separate stderr line (risks mixing non-JSON into a stderr
  JSON reader). **Either way, update `test_not_found_json`.** Couples with C1 (same `activity.py` output) -- sequence
  together. **Assertion:** the tip is reachable in `--json` mode; stdout stays clean for a `jq` consumer; the pinning
  test reflects the chosen shape.
- [ ] **B5** -- `session lane set` lane discovery + actionable invalid-lane error. Enumerate `valid_lanes(consumer)`
  (`core/lanes.py:111` -- `default_lane` + `allowed_lanes`, gate-filtered; **not** bare `allowed_lanes`, which drops the
  default lane the user is most likely on) in the `set` help (or a `--list`); make the `LaneError` say
  `valid lanes for <consumer>: <runtime/backend/model>, ...`. `session_lane.py` already imports from `forge.core.lanes`,
  so add `valid_lanes` to that import. **Assertion:** `session lane set --consumer team_supervisor --runtime codex` (no
  codex lane) errors on stderr naming the valid lanes **including the default**, not a raw `LaneError`; streams
  unchanged (still `err_console`).
- [ ] S4 verification: `tests/src/cli/test_session_lane.py` + touched help tests; `make pre-commit` clean.

## Phase 6 -- Slice S5: Batch C (research-preview clean breaks) -- C2/C3 gated

- [ ] **C1** -- align `telemetry activity` `--days` -> `--period [today|week|month|all]` (`activity.py:37`), copying the
  `trace list`/`costs show` `Choice`. **Decision: clean break** (remove `--days`), per `coding_standards.md §5`
  (research preview, no default shims) and to match the sibling clean-break pattern -- not a deprecation window.
  **Assertion:** `--period week` works; removed `--days` exits 2 (Click "No such option"); changelog entry names the
  replacement.
- [ ] **C2** -- backend metavar standardization -- **BLOCKED on OQ-2**. The B1 *definitions* already shipped (PR #71);
  the open question is whether to rename `SOURCE_ID`/`BACKEND_ID`/`SOURCE_OR_ADAPTER` metavars at all, given the
  variance encodes a real source/adapter/instance distinction (`impl_notes.md` "Unified backend"). A blind rename erases
  a value-space split. **Assertion (if actioned):** metavars communicate their id-space; changelog entry; no semantic
  merge.
- [ ] **C3** -- `--scope` value-set/ordering canonicalization -- **BLOCKED on OQ-3** (classify semantic vs cosmetic
  first). Lowest value; do last. **Assertion:** only *arbitrary ordering* is normalized; documented divergences
  (workspace vs user scope) preserved.
- [ ] Changelog entry per shipped break (`coding_standards.md §5`).

## Open questions (need human input -- from card)

- **OQ-1 (gates S3/A3):** make `policy enable --bundle` required (fail loud), or implement the
  `design_workflows.md §3.6` "restore configured bundles from intent" behavior? Resolve against
  `accidental_complexity_cleanup`'s WorkflowPolicy decision.
- **OQ-2 (gates C2):** is the `model backend` metavar variance worth a rename, given it encodes a real
  source/adapter/instance distinction? (Likely help-only; B1 definitions already shipped.)
- **OQ-3 (gates C3):** which `--scope` divergences are semantic (user vs workspace) vs cosmetic ordering?

## Acceptance tests

| Test                       | Fixture                                               | Assertion                                                                       | Test File                                       |
| -------------------------- | ----------------------------------------------------- | ------------------------------------------------------------------------------- | ----------------------------------------------- |
| A2 help artifact gone      | `session start --help`                                | rendered help contains no `[1m]`                                                | `tests/src/cli/test_session_commands.py`        |
| A4 search clean `--json`   | index with orphaned docs                              | `search clean --json` -> parseable JSON on stdout; preview only                 | `tests/src/cli/test_search.py`                  |
| A5 logs read `--json`      | logs dir populated                                    | `logs show --json` valid JSON on stdout; stderr empty                           | `tests/src/cli/test_logs_command.py`            |
| A5 logs clean preview      | logs dir populated                                    | `logs clean` deletes nothing; `logs clean --yes` removes files                  | `tests/src/cli/test_logs_command.py`            |
| A5 old flags clean break   | `logs --clean` / `logs --older-than 7`                | exit 2 (Click "No such option")                                                 | `tests/src/cli/test_logs_command.py`            |
| A5 tree invariants         | full command tree                                     | `logs show` guarded-read-JSON; `logs clean` `--yes`-preview                     | `tests/src/cli/test_command_tree_invariants.py` |
| A3 no warn-and-exit-0      | bare `policy enable`                                  | resolved behavior: fail non-zero + tip, or restore-from-intent                  | `tests/src/cli/test_policy_status.py`           |
| B5 invalid lane enumerates | `lane set --consumer team_supervisor --runtime codex` | stderr names valid lanes for the consumer, not raw `LaneError`                  | `tests/src/cli/test_session_lane.py`            |
| C1 `--period` clean break  | `telemetry activity --days 7`                         | `--period week` works; `--days` exits 2                                         | `tests/src/cli/test_activity.py`                |
| B4-json activity tip       | `telemetry activity ghost --json` (missing)           | tip reachable in `--json`; stdout clean for `jq`; `test_not_found_json` updated | `tests/src/cli/test_activity.py`                |
| Help wording (B2/B3/B4)    | `forge <cmd> --help`                                  | canonical wording/examples appear; no internal vocab leak                       | help-render / snapshot tests                    |

## Closeout items

- [ ] All selected slices ticked with verification recorded (each slice: focused suite + `make pre-commit` clean).
- [ ] Integration: none expected (host CLI + help rendering; no `claude -p`/Docker path). Confirm and record.
- [ ] Docs synced for behavior changes: `cli_reference.md` (A5 logs group, C1 `--period`), `design_appendix.md` /
  `end-user/*` where the changed surface is documented.
- [ ] `docs/board/change_log.md` updated per shipped slice (S2/S3/S5 name their clean breaks; B pass is one polish
  entry).
- [ ] cli_style index (this card) annotated per shipped slice; refuted-candidate list in `card.md` preserved.
- [ ] Durable lessons promoted to `docs/board/impl_notes.md` only after human review.
- [ ] Move card `doing/ -> done/` when the resumed cli_style scope ships or is deliberately split into new active cards.
