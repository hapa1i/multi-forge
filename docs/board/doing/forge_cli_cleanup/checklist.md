# Checklist: Forge CLI Cleanup And Taxonomy

**Card**: [card.md](card.md) - **Branch**: `forge_cli_cleanup` - **Lane**: doing

Accepted 2026-06-23 at user request and moved `proposed/ -> doing/` directly. Phase 0 (board start) is the only work
landed; no command surface has changed yet.

Deepened 2026-06-23 from a read-only verification pass over the live CLI (every card finding checked at file:line,
corrections adversarially refuted). The reconciliation below is the basis for the concrete assertions in Phases 1-2 —
read it before starting a slice.

## Current focus

Phase 1 is a **decision gate**, not code. The card is a large clean break; the cheapest way to de-risk it is to settle
the taxonomy and the open questions first, then drain the five debt ledgers the test suite already tracks. Do not rename
a live surface before the matching decision is recorded here.

**Progress (2026-06-23):** Slice 06 shipped (`forge session context` removed). Decision gate: **D1, D2, D3, D5, D7
decided** (see Phase 1) — D1 = move to `forge telemetry` + delete emptied `provider`; D2 = keep `proxy audit` under
`proxy`; D3 = build `forge model` namespace (backend moves under it); D5 = route hook install through `extension`
(de-document `hook enable|disable`); D7 = tiered config-object verbs, `backend` excluded. Still open: **D4, D6, D8,
D9**. D1/D3 both reshape `main.py` top-level groups, so they should land before D6 (aliases) settles new nouns.

## Audit reconciliation (verified 2026-06-23)

### Corrections to the card (verify before trusting the card text)

| #                                     | Card framing                                                                    | Verified reality                                                                                                                                                                                                                                                                                                                                             | Action                                                                                                                                                              |
| ------------------------------------- | ------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| F13                                   | `forge config`/`forge search` hand-roll `invoke_without_command` "for a reason" | Both **only echo help**; `subcommand_metavar`/`help_option_names` work fine with `no_args_is_help=True` (adversarially confirmed). The card's normalization point **stands**.                                                                                                                                                                                | Normalize both to `no_args_is_help=True` (slice 12).                                                                                                                |
| F14f                                  | `forge proxy edit` "proxy overlay" wording may be stale                         | "Proxy overlay" is **canonical** terminology (design_appendix §A.1 title; `proxy_orchestrator.py:134 _get_proxy_overlay_dir`). Not stale.                                                                                                                                                                                                                    | **No-op.** Drop this bullet; do not "fix" the wording.                                                                                                              |
| F3                                    | Table lists per-command cleanup defaults                                        | All six rows confirmed; `forge proxy clean` (`proxy.py:1288`) has **zero** safety flags and prunes immediately — the most dangerous.                                                                                                                                                                                                                         | Standardize `clean` verbs (slice 09).                                                                                                                               |
| `forge model backend` (slice 04 / Q3) | Proposed nesting                                                                | `forge model` with a single child `backend` is a **single-child group nest** the guide forbids and `test_no_single_leaf_groups` would flag.                                                                                                                                                                                                                  | Keep top-level `forge backend`, **or** only introduce `forge model` with ≥2 children. Decide in Phase 1.                                                            |
| F4                                    | "11 read surfaces lack `--json`"                                                | Confirmed; but the guard only inspects leaves named `list/show/status`, so `forge authentication profiles` and `forge transfer diff` are **invisible** to it (not in `JSON_MISSING_ALLOWLIST`).                                                                                                                                                              | Add `--json` to all; extend the guard to cover `profiles`/`diff` (slice 07).                                                                                        |
| F9                                    | Hand-rolled tips/errors bypass helpers                                          | `test_cli_rich_tips_*` only catches Rich `[dim]Tip:`; **10 terminal tips** slip through — 8 plain `click.echo("Tip: …")` (auth ×4, claude ×2, install ×2) **plus 2 `ClickException`-embedded** (`session.py:111,126`, my prior row wrongly said session.py has only errors). 3 assistant-facing payloads (`direct_commands.py:79,162,705`) must stay exempt. | Migrate all 10; `ClickException` bodies become plain-error-only; reword the 2 non-recovery sites; guard allowlist = the 3 `direct_commands.py` payloads (slice 11). |

### Debt ledgers already tracking this card (drain, never grow)

Each `*_ALLOWLIST` is a pre-existing-violation ledger; `_assert_ledger` fails on a *new* violation **and** on an
allowlisted entry that was fixed-without-removal. "Done" for these slices = the entry is gone from the ledger.

| Ledger (file)                                                | Entries                                                                                                                                                                                                   | Owning slice |
| ------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------ |
| `JSON_DEST_ALLOWLIST` (`test_command_tree_invariants.py:49`) | `proxy create`, `proxy metrics`, `policy check`, `policy supervisor`, `workflow {list-models,panel,analyze,debate,consensus}` — 9 using `json_output` not `as_json`                                       | 07           |
| `JSON_MISSING_ALLOWLIST` (`:134`)                            | `authentication status`, `backend show`, `proxy template {list,show}`, `claude preset show`, `config show`, `memory shadows show`, `memory report show`, `search status` — 9 read leaves with no `--json` | 07           |
| `SINGLE_LEAF_GROUP_ALLOWLIST` (`:75`)                        | `forge provider` (→ **delete**; `trace` moves to `telemetry trace` per D1), `forge policy shadow` (→ `show`; `run` hidden), `forge memory report` (→ flatten)                                             | 03 / 12      |
| `LEAF_NAMING_ALLOWLIST` (`:110`)                             | `forge policy: supervise\|supervisor` (confusable; `supervise` is a prefix of `supervisor`)                                                                                                               | 10           |
| `CLI_ERROR_MARKUP_ALLOWLIST` (`test_output.py`)              | 18 files with hand-rolled `[red]Error:` (244 raw occurrences outside `output.py`)                                                                                                                         | 11           |

### Guard gaps (rules with no mechanical enforcement yet)

- **Stream ownership (F10):** `_(review)_` only; no stdout/stderr capture test. `proxy_costs.py:20` and
  `proxy_audit.py:17` render human tables to `Console(stderr=True)` while `--json` goes to stdout —
  `activity.py`/`provider.py` are already compliant (stdout for both). Adding the guard needs
  `CliRunner(mix_stderr=False)` (slice 07).
- **Session selectors (F11):** `_(review)_`; rule is written (style guide §Command Shape) but unguarded.
- **Config-object verbs (F5):** D7 decided (tiered core `{show,edit,reset}` + optional `{set,validate}`, `backend`
  excluded); slice 08 adds the parity guard on the three pure-config objects.
- **`--json` guard scope (F4):** only `list/show/status` leaves are checked (`_READ_LEAVES`).
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
- [ ] **D4 Memory split (Q4/Q5).** Does `memory enable|disable|status|report` move under `forge session memory`, leaving
  top-level `forge memory` for project-doc passports (`track`/`list`/`passport`/`shadows`)? _Recommend: yes_ — also
  resolves the `forge memory report` single-leaf debt.
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
- [ ] **D6 Alias + canonical names (F12/Q10/Q11).** Make `auth` canonical (style-guide rule: canonical = user
  vocabulary)? Decide which moved/new groups (`telemetry`, `model`) earn aliases; decide whether the
  `extensions -> extension` shim survives. _Recommend: `auth` canonical; minimal alias set; drop the `extensions` shim
  (clean break)._ Do this **after** D1-D4 so new nouns are known.
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
- [ ] **D8 `--json` destination policy (Q8).** Normalize all `json_output` → `as_json`, or document the 9-entry
  exception? _Recommend: normalize_ (user-facing `--json` unchanged; drains `JSON_DEST_ALLOWLIST`).
- [ ] **D9 Workspace-scope coordination (Q7).** Does `forge telemetry … --scope workspace` wait for the
  `workspace_scope` proposal, or reserve the flag now? _Recommend: reserve the flag name, defer the aggregation._
- [ ] Record every D1-D9 outcome inline here (with date) before starting the matching Phase 2 slice.

## Phase 2 - Implementation slices

Each slice's assertion names an observable behavior and the test that proves it. Tick only when the test passes and the
verification is recorded.

- [ ] **Slice 03 - Telemetry move (D1, D2).** `forge telemetry activity|trace|costs` exist and work; old paths
  (`forge activity`, `forge provider trace`, `forge proxy costs`) return Click `No such command` (clean break, no
  tombstone). `forge proxy audit show|diff` **stays under `proxy`** (D2). **Delete the emptied `forge provider` group**
  \+ its `main.py:384` registration and **remove** its `SINGLE_LEAF_GROUP_ALLOWLIST` entry (the 3-leaf subgroup is
  `telemetry trace`, not provider; `forge memory report` leaves too if D4 lands). **Tighten `test_no_single_leaf_groups`
  to flag `len<=1`** so the emptied group can't pass silently. Human + `--json` of each telemetry leaf share **stdout**
  (fix `proxy_costs.py:20` stderr→stdout here; `proxy_audit.py:17` is slice 07 since audit doesn't move). Tests:
  `tests/src/cli/test_telemetry.py` (new) + old-path-removal cases.
  - **Direct-command mirror (D1 decision = retire):** **delete** `%provider trace list|show|explain` (advertised
    `direct_commands.py:71`, handled `:356`) with no `%telemetry` replacement — clean break, don't grow the surface.
    Drop the `%help` advert string and **delete** `tests/src/cli/hooks/test_direct_commands_provider.py` (removed
    surface → delete test). It is the **only** moving surface with a `%` mirror — there is no `%activity` or
    `%proxy costs`.
- [ ] **Slice 02 - Session-scope move (D4).** `forge session transfer show|regenerate|edit|diff` exist; if D4 lands,
  `forge session memory …` exists and top-level `forge memory` keeps only passport/doc verbs. Old `forge transfer …`
  paths removed. Tests assert new paths + `No such command` on old.
- [ ] **Slice 04 - Model namespace (D3 = build).** Create a `forge model` group; move all 8 backend verbs to
  `forge model backend` (`list/show/test-auth/create/start/stop/delete/reconcile`, preserved verbatim); add a real
  sibling leaf `forge model catalog` (or `list`) wiring `core/models/catalog.py` (zero CLI today, must do real work +
  expose `--json`). Old `forge backend …` paths return Click `No such command` (clean break; update every test/doc/
  example call site in the same change). Tests: `forge model` has ≥2 visible children (no `SINGLE_LEAF_GROUP_ALLOWLIST`
  entry); `forge model backend` retains all 8 verbs; catalog leaf works. Changelog names the
  `forge backend → forge model backend` move. Note interplay: `backend show` is in `JSON_MISSING_ALLOWLIST` (slice 07) —
  the move changes its path to `forge model backend show`; update that allowlist entry in whichever slice lands second.
- [x] **Slice 06 - Clean-break removals.** Deleted `forge session context` (was `session_manage.py:857`, `hidden=True`)
  and its now-dead `_print_session_context` helper + both `__all__` exports; **deleted**
  `tests/src/cli/test_session_context.py` (removed code → delete test). The ops module `forge.core.ops.session_context`
  is kept — used by `session show`/`activity`/`policy`/direct commands — and its
  `tests/src/core/ops/test_session_context.py` stays; corrected its "Used by" docstring and two mis-attributed comments
  in `session_manage.py`. Dropped the `cli_reference.md` note; fixed the stale "deprecated" `impl_notes.md` reference.
  Verified `forge session context` exits 2 with Click `No such command` (no tombstone). **Tombstone sweep:** `context`
  was the only deprecated-alias `hidden=True` command; `hook`/`memory-writer`/`status-line`/`policy shadow run` are live
  internals, left intact. 267 affected tests pass.
- [ ] **Slice 07 - Read-output consistency.**
  - `forge search query <terms>` prints a human table by default and emits the documented JSON shape only under `--json`
    (`search.py:76` currently always `json.dumps`); `forge search query --json` round-trips the prior structure.
  - Add `--json` (dest `as_json`) to the 9 `JSON_MISSING_ALLOWLIST` leaves **plus** `forge authentication profiles` and
    `forge transfer diff`; extend `_READ_LEAVES`/the guard so `profiles`/`diff` are covered; `JSON_MISSING_ALLOWLIST` →
    `{}`.
  - Normalize the 9 `json_output` dests to `as_json` (D8); `JSON_DEST_ALLOWLIST` → `{}`.
  - Make `proxy audit` human output go to stdout (`proxy_audit.py:17`; `proxy costs` → `telemetry costs` is fixed in
    slice 03). Add the planned stdout/stderr guard with `CliRunner(mix_stderr=False)` covering the telemetry leaves +
    `proxy audit` (asserts `--json` mode is valid JSON on stdout, empty stderr).
- [ ] **Slice 08 - Config-object parity (D7 = tiered).** Record the tiered vocab in the style guide: core
  `{show, edit, reset}` (already met by `config`/`proxy template`/`claude preset`), optional `{set, validate}` where
  meaningful; `proxy` documented as a partial-lifecycle exception (`clean`/`delete`, no `reset`); **`backend` excluded**
  from the editable-config rule and documented under the lifecycle-sibling rule (L79-81). Fix the false proxy-parity
  docstring at `config_cmd.py:6-9` (config has 4 verbs, not proxy's 11). Add a parity guard test asserting the core set
  on the three pure-config objects. No net-new commands required.
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
- [ ] **Slice 05 - Alias + canonical pass (D6).** Apply canonical/alias decisions; update `_ALIASES`, `_DISPLAY_ALIASES`
  (`main.py:49-72`), `cli_reference.md`, and the style guide alias section together. Run **last** so new nouns from
  D1-D4 are settled.

### Acceptance table (risky / multi-file moves)

| Test                        | Fixture                          | Assertion                                                                                                                                                                                                                                          | Test File                                                 |
| --------------------------- | -------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------- |
| Telemetry new paths         | proxy + session with telemetry   | `forge telemetry {activity,trace,costs}` exit 0; shapes match old `--json`                                                                                                                                                                         | `tests/src/cli/test_telemetry.py`                         |
| Telemetry old paths removed | n/a                              | `forge activity` / `forge provider trace` / `forge proxy costs` exit 2 "No such command"; `%provider trace` → `%telemetry trace` (or retained alias) + `%help` advert updated                                                                      | `tests/src/cli/test_telemetry.py`                         |
| Single-leaf debt shrinks    | full command tree                | `SINGLE_LEAF_GROUP_ALLOWLIST` no longer lists `forge provider` (+ `forge memory report` if D4)                                                                                                                                                     | `test_command_tree_invariants.py`                         |
| `search query` inverted     | indexed transcript               | bare `query` prints human table on stdout; `--json` emits documented array; `--json` round-trips old shape                                                                                                                                         | `tests/src/cli/test_search.py`                            |
| `--json` missing drained    | each read leaf                   | every `JSON_MISSING_ALLOWLIST` leaf + `authentication profiles` + `transfer diff` emits valid JSON; ledger `{}`                                                                                                                                    | `test_command_tree_invariants.py`                         |
| `--json` dest normalized    | full tree                        | no leaf binds `json_output`; `JSON_DEST_ALLOWLIST` `{}`                                                                                                                                                                                            | `test_command_tree_invariants.py`                         |
| Stream ownership            | `proxy costs`/`audit` (or moved) | `--json` mode: valid JSON on stdout, empty stderr; human mode on stdout                                                                                                                                                                            | `tests/src/cli/test_*` with `CliRunner(mix_stderr=False)` |
| Supervisor split            | session with supervisor          | `forge policy supervisor {status,set,off,on,reload,evaluate}` work; `supervise` exits 2; `LEAF_NAMING_ALLOWLIST` `{}`                                                                                                                              | `tests/src/cli/test_policy.py`                            |
| `session context` removed   | n/a                              | `forge session context` exits 2 "No such command"; `test_session_context.py` deleted                                                                                                                                                               | (removal)                                                 |
| Error markup drained        | CLI source scan                  | `CLI_ERROR_MARKUP_ALLOWLIST` `{}`; all 10 terminal tips routed (incl. 2 `ClickException`); `proxy_costs.py:132` + `session_fork.py:467` reworded; tip guard fails on `Tip:` in CLI source, allowlist = exactly the 3 `direct_commands.py` payloads | `tests/src/cli/test_output.py`                            |

## Docs and verification

- [x] Fix debt-ledger breadcrumb rot: provenance comment at `tests/src/cli/test_command_tree_invariants.py:7` now points
  at `docs/board/doing/forge_cli_cleanup/card.md` (was `proposed/`). `test_output.py:142` carries no path, so it needed
  no change. (Two stale cross-links remain in `docs/board/proposed/rewind_resume_strategy/card.md:27,260` — a different
  card's content; tracked separately, not fixed here.)
- [ ] Update `docs/cli_reference.md` for every moved/removed/added surface (drop the `session context` note; re-document
  aliases per D6).
- [ ] Update relevant `docs/end-user/*` guides (`hook.md` per D5, `proxy.md`/`session.md`/`memory.md` for moves).
- [ ] Update `docs/developer/cli_style_guidelines.md`: record the config-object verb vocabulary (D7), the stream guard
  once wired, the alias rule (D6), and remove "settled in the forge_cli_cleanup card" placeholders as each lands.
- [ ] Update `docs/design.md`/`cli_reference.md` ownership tables if command ownership changes (telemetry, memory
  split).
- [ ] Add a `change_log.md` entry per shipped slice naming the moved live commands (`forge activity` →
  `forge telemetry activity`, etc.).
- [ ] Run targeted CLI tests for old/new paths, help text, `--json` shape, and stream behavior after each slice.
- [ ] `make pre-commit` before closeout; promote durable taxonomy/alias decisions to `impl_notes.md` after review.

## Open decisions carried from the card

Most are now folded into Phase 1 (D1-D9). Remaining specifics to settle during execution:

- [ ] Exact shared scope flags for `telemetry activity|costs|trace` (`--session` vs optional positional `[session]`,
  `--scope`, `--period`) — instantiate the F11 session-selector rule, not a per-command guess.
- [ ] Final placement of `proxy audit` (D2).
- [ ] Backend namespace + churn budget (D3).
- [ ] Memory `report`/`enable`/`disable`/`status` placement (D4).
- [ ] Hook-management visibility (D5).
- [ ] Whether workspace-level telemetry waits for `workspace_scope` (D9).
- [ ] Whether any `--json` dest intentionally stays `json_output` (D8) — default is normalize.
- [ ] Human read-output stdout/stderr rule + any documented exceptions (slice 07).
- [ ] Canonical `auth` vs `authentication` and the alias-eligibility rule (D6).
