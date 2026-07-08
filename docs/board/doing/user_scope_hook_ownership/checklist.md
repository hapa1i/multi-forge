# Execution checklist: T5 `user_scope_hook_ownership`

Execution plan for the user-scope-only hook registration flip. Coordination/contract lives in the epic
[`card.md`](../epic_global_forge_runtime/card.md); this member's problem framing is [`card.md`](card.md).

> **Drafted 2026-07-08**, **revised 2026-07-08 after review**. Refinements over the card's 2026-07-02 grounding:
> presence detection has **five** call sites (not two); T4 already ships `render_dispatcher_command()` as the
> registration seam; the scope gate lands on the **effective module set** after both normal resolution and sync/update
> overrides (not deep in settings-merge) so tracking/status/JSON stay truthful; and **sidecar is entirely T10-owned**
> (T5 only lands an exposure gate / documented interim-gap guard, not an injection path).

## Current focus

**Phase 0 complete — implementation not started; awaiting go.** Resolved decisions were mirrored into the epic card on
2026-07-08; Phases 1--7 are ready to begin once implementation is approved.

## Scope boundary (do not cross)

**In (T5 ships):**

- **Scope inversion at the module layer**: `forge extension enable --scope user` installs the `hooks` (+ `codex-hooks`)
  modules and **not** `status-line`; `--scope project`/`--scope local` install `status-line` (epic D3) and **not**
  `hooks`/`codex-hooks`. Gate the **effective module set** after every module source (`resolve_modules` output and
  sync/update `_modules_override`) so `plan.modules`, `Installation.modules_enabled`, dry-run, `extension status`,
  `--json`, and disable/unmerge are all truthful by construction — not a settings-merge-only gate that leaves the
  manifest claiming an unwritten module.
- **Command-byte cutover**: the (now user-scope) hook commands change from bare `forge hook <name>` to the dispatcher
  form `<home>/.forge/bin/forge-hook <name>` (absolute path, via T4's `render_dispatcher_command`), for both the Claude
  preset and the Codex managed block. Byte-identity + unmerge-before-merge (seam 1); Codex trust-byte golden + re-trust.
- **Presence-detection update (additive)**: `is_forge_hook_command`/`has_forge_hook`/`has_forge_hooks` + **all five
  callers** recognize the hyphenated `forge-hook` dispatcher form **while still** matching bare `forge hook` (T6
  migration window). Required — T4 chose the hyphen shim. **Do not** broaden back to substring detection.
- **Cross-scope double-fire detection**: `forge extension doctor` (and the status line) report when user-scope and
  project-scope Forge hooks both exist, and **name** the cleanup command (cleanup itself is T6).

**Out (owned elsewhere):**

- **Sidecar / in-container hook resolution → `forge_hook_sidecar_resolution` (T10), entirely.** T10 already owns the
  full mechanism (staging/injection without mutating the RW-mounted host config, both `settings.json` +
  `settings.local.json`, statusLine neutralization, and a "T5 world … still has working hooks" acceptance row). T5's
  byte/scope change is what *creates* the hookless-sidecar regression, so T5 owns only a **tested, documented
  interim-gap guard** (Phase 5) — no injection path. Reconciles the epic D2 "paired T10 sidecar exemption": *paired
  with* T10, implemented *by* T10.
- Migration of **existing** installs → `forge_hook_migration_cleanup` (T6). T5 changes **new** installs + adds the
  double-fire detection that makes the pre-T6 state legible. If `sync` sees pre-T5 project/local hook tracking, T5 must
  not re-author or convert those project hooks; it must preserve cleanup records solely so `disable`/T6 can still remove
  the physical legacy entries.
- Legacy standalone-writer removal → `forge_hook_legacy_writer` (T9, already `done/`).
- Team checked-in Codex hook policy → deferred (card open question).

## Grounding (verified 2026-07-08 on this branch)

Re-grep the symbol before relying on an exact line; these are the current snapshot.

- **Detection predicate + presence helpers** (`src/forge/install/hooks.py`): `is_forge_hook_command` (:49, shlex-token
  semantics: basename `forge`, second token `hook`, optional handler), `entry_is_forge_hook` (:70), `has_forge_hook`
  (:104), `has_forge_hooks` (:137 → `has_forge_hook(SessionStart)`). A dispatcher command
  `/abs/.forge/bin/forge-hook <name>` has basename **`forge-hook`** and the handler as the **second** token — so the
  current predicate returns `False` for it.
- **All five detection call sites** (must each still resolve True post-cutover — the card named only two):
  - `cli/session_manage.py:1075` — `has_forge_hook(..., "Stop")`
  - `cli/session.py:232` — `has_forge_hooks(parent_project_root)`
  - `cli/policy.py:323` — `has_forge_hook(cwd, "PreToolUse", handler="policy-check")`
  - `cli/session_lifecycle.py:253` — `has_forge_hooks(project_path)`
  - `cli/search.py:160` — `has_forge_hook(project_root, "Stop")`
- **Registration seam T4 already shipped**: `render_dispatcher_command(handler, forge_home=)`
  (`install/hook_dispatcher.py:330`) returns the exact byte form T5 registers
  (`shlex.quote(path) + " " + shlex.quote(handler)`); `normalize_dispatcher_command_home` (:337) is the
  `$HOME`-normalizer for goldens.
- **Module resolution + plan** (`install/installer.py`): `resolve_modules` (:349) computes the effective module set from
  profile + `--with`/`--without`; `update()` bypasses normal resolution by passing tracked modules through
  `_modules_override` (:1065--1071); the plan records `modules=sorted_modules` (:458); `Installation(...)` persists
  `modules_enabled` (:971, read back at :1065). Scope gating must therefore be a shared effective-module filter applied
  after **both** normal resolution and `_modules_override`.
- **Filtered-update cleanup trap** (`install/installer.py`): `update()` removes stale tracked **files** (:903--925), but
  settings removal happens only on `uninstall()` / disable (`smart_unmerge` at :1114). `init()` rebuilds
  `Installation.settings_entries` by appending existing entries not produced by the current merge (:951--956), but it
  also rewrites `.settings*.json.forge-added` from only the current merge entries (:892--894). Since disable prefers the
  `.forge-added` smart-unmerge payload, a filtered project/local sync must preserve legacy hook cleanup data in
  `installed.json` **and** in the `.forge-added` payload, or make disable fall back to `settings_entries` for omitted
  legacy hooks.
- **Status/JSON surfaces that must not lie** (`cli/extensions.py`): `_print_plan` shows `Modules: {plan.modules}`
  (dry-run + plan); `_warn_if_modules_have_no_files` (:115) keys off `plan.modules`; `extension status`/`--json` and
  `installed.json` report `modules_enabled`.
- **Claude registration** (`install/preset.py`): 13 event keys wiring `forge hook <name>` (:53--211, ~17 command
  entries) + the `statusLine` scalar `forge status-line` (:218--220).
- **Codex registration** (`install/codex_hooks.py`): entries `forge hook codex-session-start` /
  `forge hook codex-policy-check` (:84--85), rendered by `render_codex_block` (:127); command bytes are the
  `trusted_hash` surface (golden-pinned, :16--19,:66--67; `test_codex_hooks.py`).
- **Settings-merge machinery** (`install/settings_merge.py`): `merge_hooks` (:505) is **append + dedupe by full
  canonical entry** — a changed command string is a **coexisting new sibling** (double-fire), not an in-place update.
  `smart_unmerge` (:251) / `unmerge` (:733) remove tracked entries → unmerge-before-merge on the byte cutover.
- **Scope resolution** (`installer.py:231` `find_claude_root` → LOCAL for any `.claude` above home; `cli/extensions.py`
  `_detect_git_project_root` forces LOCAL in a git repo): today the in-repo default is project/local — inverted here for
  hooks.
- **Env-var vocabulary guard** (`tests/src/cli/test_env_vocabulary.py`): every new user-facing string (doctor/status
  double-fire message, changed enable next-steps) is scanned; internal `FORGE_*` mentions need a deliberate
  `forge-env-vocab: diagnostic` classification.

## Phase 0 — Decisions (complete 2026-07-08)

- [x] **Enable UX / naming — RESOLVED: keep `forge extension enable --scope user`** (no new verb; a new verb is extra
  surface for a scope/ownership change, and the epic forbids new top-level groups). **Pin the Day-1 UX:** in-repo
  auto-LOCAL enable no longer installs runtime hooks; the completion/next-steps output **must** tell the user to run the
  user-scope hook install once; docs + QA/walkthrough reflect it.
  - _Assertion:_ decision + Day-1 UX recorded in the epic card CLI-surface section (Phase 6 mirrors it).
- [x] **Sidecar — RESOLVED: entirely T10.** T5 does **not** grow an injection path. T5 lands an exposure gate plus a
  tested interim-gap assertion (Phase 5); T10 must land before T5's change reaches sidecar users unless the maintainer
  explicitly records a temporary hookless-sidecar waiver and the runtime warns/blocks before launch. Reconcile the epic
  D2 "paired T10 sidecar exemption" note to "implemented by T10."
- [x] **Detection posture — RESOLVED: additive.** Accept `forge-hook …` while preserving bare `forge hook …`; no
  substring detection.
- [x] **Explicit `--with hooks --scope project` — RESOLVED: hard-reject.** Implicit `standard` modules are filtered by
  scope, but an explicit module override that contradicts the ownership rule is rejected rather than silently dropped. A
  team-checked-in-policy path stays deferred (card open question).
  - _Assertion:_ explicit project/local `--with hooks` or `--with codex-hooks` exits with a clear ownership-rule error;
    no project hook block is written or recorded.
- [x] Mirror all resolved decisions into the epic card (seams 1/4/5, CLI-surface) and tick the seam notes.

**Blocker cleared:** Phase 1 can begin when implementation work is approved.

## Phase 1 — Presence-detection update (additive; lockstep with the byte cutover)

- [ ] Extend `is_forge_hook_command` (`install/hooks.py:49`) to recognize the dispatcher form (basename `forge-hook`,
  handler as the second token) **alongside** the existing `forge` + `hook` + handler form. Keep it the single predicate
  (`forge_hook_matcher_consolidation` single-sourced it — do not add a second matcher, do not revert to substring).
  - _Assertion:_ `is_forge_hook_command("/abs/.forge/bin/forge-hook policy-check", handler="policy-check")` True; legacy
    `forge hook policy-check` stays True; `echo forge-hook stop` (contains-only) stays False.
- [ ] Verify **all five** callers resolve True against a dispatcher-form install (no false "hooks not installed"
  warnings): `session_manage.py:1075`, `session.py:232`, `policy.py:323`, `session_lifecycle.py:253`, `search.py:160`.
  - _Assertion:_ launch/policy-enable smoke over each call site emits no false "not installed" warning (acceptance:
    "Detection recognizes dispatcher"); legacy form still matches (acceptance: "Detection still matches legacy").
- [ ] Extend the matcher golden/contract (`tests/src/install/test_registered_commands_contract.py`, `test_hooks.py`).

## Phase 2 — Scope-ownership at the module layer (seam 4) + tracking truthfulness

- [ ] Gate the **effective module set** by scope in a shared helper used by both `resolve_modules`/plan-build
  (`installer.py:349,:458`) and update/sync `_modules_override` (`installer.py:1065--1071`): drop `hooks` +
  `codex-hooks` for `project`/`local`; drop `status-line` for `user`. Everything else (commands/agents/skills/
  permissions) installs at every scope as today. The settings-merge writes then follow the module set.
  - _Assertion:_ `--scope local` → project `.claude/settings*.json` + `.codex/config.toml` get **no** Forge hook block,
    but the `statusLine` scalar **is** written (acceptance: "Project skips hooks" + "Project keeps statusLine").
  - _Assertion:_ `--scope user` → user `~/.claude/settings.json` carries the dispatcher hook entries and **no**
    `statusLine`; user scope **still** installs commands/agents/skills/permissions (acceptance: "User settings:
    dispatcher hooks only, still full extension install").
- [ ] **Tracking/status/JSON truthfulness** (the payoff of gating at the module layer): `plan.modules`, dry-run output,
  `Installation.modules_enabled`, `forge extension status`, `--json`, and `disable`/unmerge must reflect **actual**
  per-scope writes — project/local never claims `hooks`/`codex-hooks`; user never claims `status-line`.
  - _Assertion:_ dry-run `Modules:` line, `installed.json` `modules_enabled`, and `extension status --json` are truthful
    per scope (acceptance: "Tracking/status truthful per scope").
- [ ] Preserve migration boundaries on legacy sync: if a pre-T5 project/local install has tracked hook entries, `sync`
  filters `hooks`/`codex-hooks` out of the effective modules, does **not** rewrite them to dispatcher project hooks,
  records no hook module as enabled, and reports the cross-scope/legacy state instead of claiming it is clean. Cleanup
  tracking is distinct from enabled-module truthfulness: preserve the pre-existing hook cleanup records in both
  `Installation.settings_entries` and the `.settings*.json.forge-added` smart-unmerge payload, or update disable so it
  can fall back to `settings_entries` when a filtered sync omits those hooks from the added payload.
  - _Assertion:_ project/local `sync` over a real pre-T5 tracked install leaves the physical legacy hook entry in
    settings without adding a dispatcher sibling, filters `modules_enabled`, preserves cleanup tracking, and a
    subsequent `forge extension disable --scope local` still removes that legacy hook (acceptance: "Project sync
    preserves cleanup tracking").
- [ ] Enforce the Phase-0 explicit override decision: project/local `--with hooks` and `--with codex-hooks` hard-reject;
  no unwritten module is ever recorded as enabled.
- [ ] Emit the actionable enable next-steps line: in-repo project/local enable points to
  `forge extension enable --scope user` for runtime hooks. Must pass the env-var vocabulary guard.
  - _Assertion:_ project/local enable output names the user-scope hook install command (acceptance: "Day-1 next-steps").

## Phase 3 — Command-byte cutover + unmerge-before-merge + goldens (seam 1)

- [ ] Register hook commands via `render_dispatcher_command(handler)` (absolute `<home>/.forge/bin/forge-hook <name>`,
  never `~`) for the Claude preset hooks and the Codex block.
  - _Assertion:_ rendered Claude + Codex commands are literal absolute paths to `forge-hook` (acceptance: "Literal
    absolute path").
- [ ] **Unmerge-before-merge, user scope only**: user-scope `enable`/`sync` unmerge the previously-tracked hook entries
  (old `forge hook <name>` form, via `installed.json` tracking + `smart_unmerge`/`unmerge`) **before** merging the new
  dispatcher entries, so `merge_hooks`' append+dedupe leaves no coexisting old sibling. Project/local legacy hook
  entries are not converted to dispatcher project hooks by T5; T6 migrates/removes them.
  - _Assertion:_ a user-scope `sync` over a settings file holding the old form yields exactly the new dispatcher entries
    — no old+new sibling (acceptance: "User sync cutover leaves no double sibling").
- [ ] Update the Codex trust-byte golden to the dispatcher form with `$HOME` normalized (mirror T4: template golden + a
  separate real-home substitution assertion). A byte change fails the golden.
- [ ] Surface the **Codex re-trust** consequence: the byte change invalidates existing `trusted_hash` enrollment, so
  enable/sync next-steps + the changelog name the one-time re-trust ceremony (Forge cannot perform/verify it — design.md
  §3.9).

## Phase 4 — Cross-scope double-fire detection (report only; cleanup is T6)

- [ ] Add cross-scope detection to `forge extension doctor` (`cli/extensions.py`, alongside the existing
  `hook_dispatcher`/`project_registry`/`project_compatibility` diagnostics at :1147--1156) and the status line: report
  when user-scope **and** project-scope Forge hooks both exist, and **name** the T6 cleanup command.
  - _Assertion:_ legacy user + project Forge hooks present → `doctor` (+ `--json`) reports double-fire risk and names
    the cleanup command (acceptance: "Cross-scope double-fire warned"); the string passes the env-var vocabulary guard.
- [ ] No cleanup here (that is T6) — detection + naming only.

## Phase 5 — Sidecar exposure gate (T10-owned mechanism)

- [ ] Confirm T5 writes **no** host-absolute dead path into sidecar-read project config — true by construction for new
  project/local installs, since they write no hook block into `/workspace/.claude/settings*.json`. Do not test only
  `run_sidecar_session`; sidecar launch also mounts project `.claude` at `/workspace/.claude` and sidecar home at
  `/root/.claude`.
- [ ] Land the **operational exposure gate**: T5 cannot merge/release to sidecar users until T10 is merged, unless the
  maintainer records an explicit temporary hookless-sidecar waiver. If the waiver path is chosen, T5 must add a
  user-facing sidecar warning/block before launch that names T10 and the hookless state. Do **not** implement
  in-container injection here.
  - _Assertion:_ sidecar launch coverage asserts the chosen gate: T10-present path, or waiver + warning/block + no dead
    host path (acceptance: "Sidecar exposure gate enforced").
- [ ] Record the seam-5 sequencing in the epic: **T10 must land before T5's change reaches sidecar users** unless a
  named waiver is accepted; T10 owns the injection, both settings files, and statusLine neutralization.

## Phase 6 — Design-doc + QA sync

- [ ] `design.md §3.10` (Hook handlers / Deployment model): describe the **shipped** user-scope-only registration
  cutover in present tense; statusLine stays project-scoped (D3).
- [ ] `design_appendix §C` (install model): scope model + module inventory reflect hooks/codex-hooks → user-only,
  status-line → project/local; `§C.6` notes the Codex byte cutover + re-trust.
- [ ] `cli_reference.md`: `forge extension enable` scope semantics + the `doctor` double-fire report + changed
  next-steps.
- [ ] **Day-1 UX docs + QA/walkthrough**: end-user install guide teaches "install hooks once at user scope"; the
  `/forge:walkthrough` + `/forge:qa` checklists reflect that in-repo enable no longer installs hooks.
- [ ] Epic seams 1/4 + CLI-surface section reflect the shipped model; seam 5 records the T10 hand-off.

## Phase 7 — Closeout

- [ ] All acceptance rows green.
- [ ] `make pre-commit` clean.
- [ ] Install + hook integration run (testing_guidelines mandates it for installer/hook changes):
  `./scripts/test-integration.sh tests/integration/docker/test_installer.py`, plus real-Claude and real-Codex
  hook-firing coverage proving the **dispatcher command form actually fires** end-to-end.
- [ ] Epic seam bookkeeping updated; `change_log.md` entry (Goal / Key changes / Verification); durable lessons proposed
  for `impl_notes.md` (human review before promotion).
- [ ] Lane move `doing/ -> done/` deferred to **post-merge**; repoint inbound links on the move (epic forward-link,
  member back-link, `done/forge_hook_matcher_consolidation` inbound link).
- [ ] Verify the sidecar exposure gate is satisfied before merge/release (T10 landed, or explicit maintainer waiver +
  warning/block covered). Hand the epic cursor to **T10** (sidecar, if not already landed) and **T6** (migrate existing
  installs); **T8** (dev override) remains.

## Acceptance tests

Grounded on the card's contract, refined against the re-grepped seams + the 2026-07-08 review.

| Test                                       | Fixture                                                             | Assertion                                                                                                                                                              | Phase | Test File                                   |
| ------------------------------------------ | ------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----- | ------------------------------------------- |
| Detection recognizes dispatcher            | `forge-hook` dispatcher command installed                           | `is_forge_hook_command`/`has_forge_hook(s)` True; all five callers emit no false "not installed"                                                                       | 1     | `tests/src/install/test_hooks.py`           |
| Detection still matches legacy             | legacy `forge hook <name>` command                                  | additive predicate keeps the old form True (T6 migration-window safe); no substring broadening                                                                         | 1     | `tests/src/install/test_hooks.py`           |
| Project skips hooks                        | `forge extension enable --scope local`                              | project `.claude/settings*.json` + `.codex/config.toml` get **no** Forge hook block                                                                                    | 2     | `tests/src/install/test_installer.py`       |
| Project keeps statusLine                   | `forge extension enable --scope local`                              | project `.claude/settings*.json` **still** registers the `statusLine` scalar (D3)                                                                                      | 2     | `tests/src/install/test_installer.py`       |
| User settings: dispatcher hooks only       | `forge extension enable --scope user`                               | user `settings.json` carries only dispatcher hook entries, **no** statusLine; commands/agents/skills/permissions still install                                         | 2/3   | `tests/src/cli/test_extension_enable.py`    |
| Tracking/status truthful per scope         | enable at each scope                                                | dry-run `Modules:`, `installed.json` `modules_enabled`, `extension status --json` reflect actual writes (no unwritten module claimed)                                  | 2     | `tests/src/cli/test_extension_enable.py`    |
| Explicit `--with hooks --scope project`    | `enable --scope local --with hooks`                                 | hard-rejects with ownership-rule error; no project hook block; tracking not claiming hooks                                                                             | 2     | `tests/src/cli/test_extension_enable.py`    |
| Day-1 next-steps                           | in-repo `forge extension enable` (auto-LOCAL)                       | completion output names `forge extension enable --scope user` for runtime hooks; passes env guard                                                                      | 2     | `tests/src/cli/test_extension_enable.py`    |
| Literal absolute path                      | user hook install                                                   | rendered Claude + Codex commands contain `/abs/home/.forge/bin/forge-hook`, not `~`                                                                                    | 3     | `tests/src/cli/test_extension_enable.py`    |
| Project sync preserves cleanup tracking    | real filtered `sync` over pre-T5 tracked project/local hook install | filters forbidden modules, adds no dispatcher project sibling, preserves `settings_entries` + `.forge-added` cleanup data, and later `disable` removes the legacy hook | 2     | `tests/src/cli/test_extension_enable.py`    |
| User sync cutover leaves no double sibling | user settings holding old `forge hook` form                         | `sync` unmerges old, merges new → exactly the dispatcher entries, no coexisting sibling                                                                                | 3     | `tests/src/install/test_settings_merge.py`  |
| Codex golden + re-trust surfaced           | rendered Codex block (`$HOME`-normalized)                           | golden pins the dispatcher template; byte change fails; next-steps name the re-trust                                                                                   | 3     | `tests/src/install/test_codex_hooks.py`     |
| Cross-scope double-fire warned             | legacy user + project Forge hooks present                           | `doctor`/status reports double-fire risk and names the cleanup command                                                                                                 | 4     | `tests/src/cli/test_extension_enable.py`    |
| Sidecar exposure gate enforced             | sidecar launch under T5 user-scope model                            | T10 landed, or explicit waiver + warning/block before launch; no host-absolute dead path in `/workspace/.claude`                                                       | 5     | `tests/src/core/ops/test_claude_session.py` |
| New user-facing strings pass guard         | doctor/status/enable next-steps strings                             | `test_env_vocabulary.py` classification passes (no leaked internal `FORGE_*`)                                                                                          | 2/4   | `tests/src/cli/test_env_vocabulary.py`      |

## Open decisions

- None for T5 Phase 0. Resolved 2026-07-08 review: enable UX = keep `--scope user`; sidecar = entirely T10 with an
  exposure gate; detection = additive; explicit project/local `--with hooks` = hard-reject.

## Blockers / deferred (owned elsewhere)

- **Sidecar / in-container resolution** — T10 `forge_hook_sidecar_resolution` owns the full mechanism. T5 lands only the
  exposure gate / documented interim-gap guard; **T10 must land before T5's change reaches sidecar users** unless a
  maintainer records an explicit temporary waiver and T5 warns/blocks before sidecar launch.
- **Migration of existing installs** — T6 `forge_hook_migration_cleanup` (backfill + legacy cleanup). T5 changes new
  installs and adds the double-fire detection that surfaces the pre-T6 state.
- **Team checked-in Codex hook policy** — deferred (card open question); not the default install path for v1.
