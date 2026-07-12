# Execution checklist: forge_dev_runtime_override (T8)

**Branch**: `forge-dev-runtime-override`. Card: [`card.md`](card.md). Epic:
[`epic_global_forge_runtime`](../../doing/epic_global_forge_runtime/card.md) -- T8 was the epic's last live member (T2
stays `proposed/` as superseded-not-abandoned; the split T7 sweep was reclassified a standalone non-member follow-up,
2026-07-11), so this closeout makes epic closeout actionable (epic-owned, not done here).

## Current focus

Shipped via PR #97 (`46ff9ef6`) after the focused suite, Docker installer integration, wheel/clean-install flow, live
dev-loop smoke, and `make pre-commit` all passed. The card is closed in `done/`; the epic remains in `doing/` for its
own seam verification and lane closeout.

## Grounding (verified against code, 2026-07-11; extended across both review rounds)

File refs are the 2026-07-11 snapshot.

- **Resolver order today** (`hook_dispatcher.py::_RESOLVER_SOURCE::_candidate_forge_paths`): recorded
  `runtime.json.forge_binary_path` first, then `~/.local/bin/forge`, then `$UV_TOOL_BIN_DIR` / `$XDG_BIN_HOME` /
  `$PIPX_BIN_DIR`. **`_resolve_forge` returns the first *executable* candidate and silently skips invalid ones** --
  which is why the override cannot be a prepended candidate (D4): an invalid entry would fall through to the global
  launcher instead of failing.
- **Dispatcher `main()` order is gate -> missing-handler check (exit 2) -> resolve -> execv.** The override branch slots
  at the resolve stage, after both prior checks, so `FORGE_DEV` set + no handler still exits 2 without exec.
- **`os.execv` raises `OSError` on failure** (e.g. `ENOENT` for a stale/missing shebang interpreter, `ENOEXEC` for an
  invalid executable format); the shim's `return 127` after `execv` is unreachable on that path today. Validation can
  also raise: `Path.expanduser()` raises `RuntimeError` on an unresolvable `~user`. The override branch wraps both.
- **The no-op gate is a separate source block** (`_GATE_SOURCE`): `FORGE_SESSION` short-circuit, else enrolled-root
  registry check. The override belongs to the *resolution* stage only -- it must never change what dispatches.
- **A shim-source change is self-surfacing.** `dispatcher_source_sha256()` covers the rendered blocks, so every
  installed dispatcher reports `stale` in `forge extension doctor` until `forge extension sync` re-renders
  (`diagnose_hook_dispatcher`). Upgrade surface already exists; no silent skew.
- **Hook command bytes do NOT change.** Registration invokes `<forge-home>/bin/forge-hook <handler>`
  (`render_dispatcher_command`). T8 edits script *content*, not registered commands, so there is no unmerge-before-merge
  and **no Codex re-trust** (trust hashes the command definition, not script bytes -- impl_notes, codex_frontend).
- **Pre-T8 sticky behavior was characterized at every installer scope.** `Installer.init()` calls
  `_ensure_hook_dispatcher()` unconditionally (`installer.py:935` -> `install_hook_dispatcher()` ->
  `write_runtime_metadata`), and the old implementation directly recorded whatever `forge` the `which`-then-`argv0`
  discovery found. A dev-shell enable/sync (any scope, not just user) therefore recorded `<checkout>/.venv/bin/forge`
  into `runtime.json`, sticky-pointing all hook dispatch at the checkout. The implemented D2 selector now filters that
  implicit venv discovery.
- **Launcher classification must be lexical.** Resolving the `~/.local/bin/forge` symlink lands inside the uv tool-venv
  (beside a `pyvenv.cfg`), which would misclassify every healthy global install as a venv launcher (impl_notes,
  global_forge_install: "launcher-symlink-not-realpath"). `find_current_forge_binary` already avoids `resolve()`
  (`_absolute_without_resolving`); the D2 venv test inspects the discovered path's own directory, never its realpath
  target.
- **The persistent dev path is the deliberate global editable install.** `scripts/setup.sh` runs
  `uv tool install -e --force .` (~:353), landing an editable launcher at `~/.local/bin/forge` -- a stable location the
  resolver legitimately records. `FORGE_DEV` is therefore the only *first-class transient checkout override*, not "the
  only dev path".
- **Current hooks do not enforce the `required_forge` pin.** `check_project_compatibility_for_hook`
  (`project_compat.py:138`) has no production caller; strict enforcement lives on command paths via `cli/guards.py`
  **and directly in `cli/extensions.py`** (5 call sites). Hook-path enforcement is owned by
  `todo/forge_project_compat_mutator_sweep/` (a standalone follow-up, not an epic member).
- **`FORGE_DEV` propagates into managed launches.** The managed-session environment builders copy `os.environ`
  (`core/reactive/env.py:240`, `session/codex_invoke.py:152`, `core/invoker/codex.py:134`), so a value exported in the
  launch shell reaches hook subprocesses for both runtimes. (`forge codex start`'s bare-launch scrub drops only listed
  vars; `FORGE_DEV` is unaffected.)
- **`FORGE_DEV`'s class was pre-decided**: the accepted `done/env_var_interface_boundary/card.md` classification table
  lists "T8's planned dev override" under **Public** -- and §A.7b requires a Public var to be documented in the relevant
  **end-user guide** before help text or normal docs teach it (`docs/end-user/hook.md` is the home).
- **Sidecar is out of scope by construction.** Sidecars register bare image-PATH `forge hook <handler>` (seam 5, T10)
  and never run the host dispatcher, so there is no override surface to design for.

## Phase 0: Decisions (ratified 2026-07-11; hardened same day, round 2)

- [x] **D1 -- Mechanism: `FORGE_DEV` env override. RATIFIED with corrected rationale.** `FORGE_DEV` provides explicit,
  process-scoped, reversible runtime selection **without mutating global runtime metadata**, and managed launches
  inherit it because both runtimes' environment builders copy `os.environ` (grounding). The draft's "`uv run`-only can
  never exercise live hooks" rationale was wrong against today's code -- the sticky-sync accident already routes hooks
  at `.venv/bin/forge` after a dev-shell sync -- and is retired.
- [x] **D2 -- No implicit sticky dev selection. RATIFIED; mechanism is a deterministic transition table (round 2).** NOT
  a global-bin-only allowlist (would regress custom on-PATH launchers; every installer scope rewrites metadata at
  `installer.py:935`). Recording selection at each enable/sync, in precedence order:
  1. discovered executable **non-venv** launcher -> **record it** (first-time custom installs are recorded; a deliberate
     A->B launcher migration records B);
  2. discovered **venv**, missing, or unusable launcher -> **preserve** a valid recorded non-venv target (absolute,
     executable file, classified lexically); this keeps a healthy target when discovery returns `None` or an unusable
     `argv0`;
  3. no usable recorded target -> first executable **known-global fallback**;
  4. otherwise -> **null** (no guessed paths); doctor advises. Classification is **lexical** -- the venv test
     (`pyvenv.cfg` sibling) inspects the discovered path's own directory and never resolves a symlink into its tool-venv
     target (grounding). An explicit `forge_binary_path=` argument remains authoritative over discovery. Legacy
     `.venv/bin/forge` metadata is replaced or cleared by the same table at the next enable/sync.
     `known_forge_launcher_paths()` stays the static fallback-list helper; a higher-level recording/diagnostic
     **selector** owns this stateful choice. `which` AND `argv0` discovery covered, across project/local enable and user
     sync. Wording: `FORGE_DEV` is the only **first-class transient checkout override**; the persistent dev path remains
     the deliberate global editable install (`setup.sh`).
- [x] **D3 -- Target form: checkout root, non-empty ABSOLUTE path. RATIFIED.** `FORGE_DEV` names the checkout root; the
  shim execs `<path>/.venv/bin/forge`. Validation after `~` expansion: empty, boolean-like, and **relative** values are
  invalid (a relative path would resolve against the hook's cwd -- the target project -- violating the cross-project
  invariant). Paths containing spaces are tested. No direct-binary-path or `uv run --project` form.
- [x] **D4 -- Failure posture: fail loud, as a SEPARATE hard override branch. RATIFIED; placement and presence semantics
  pinned (round 2).** Presence is `"FORGE_DEV" in os.environ` -- an empty value is *present and invalid*, never silently
  treated as unset (`os.environ.get()` truthiness would fall through). The branch sits after the gate AND the
  missing-handler validation, so `FORGE_DEV` set + no handler still exits 2 with no exec. When present, the shim uses
  exactly the named target or exits 127 with stderr naming `FORGE_DEV` and the checked path -- it never enters the
  normal candidate loop (whose first-executable-wins scan would silently skip an invalid override). Expansion/validation
  errors (`Path.expanduser()` `RuntimeError`) and exec errors (`OSError`: `ENOENT` stale shebang interpreter, `ENOEXEC`
  invalid format) all fail the same loud way.
- [x] **D5 -- `required_forge`: "T8 adds no special bypass." RATIFIED as reworded.** Current hooks do not enforce the
  pin at all (`check_project_compatibility_for_hook` has no production caller; strict enforcement is `cli/guards.py`
  plus direct `cli/extensions.py` command paths); the existing compatibility posture is unchanged by T8, and hook-path
  enforcement stays owned by the mutator sweep. Outcome written back to
  `todo/forge_project_compat_mutator_sweep/card.md` (Design Rules).
- [x] **D6 -- Classification: Public. RATIFIED (pre-decided); doc surface corrected (round 2).** The accepted
  `env_var_interface_boundary` card classifies T8's dev override as **Public**, and the §A.7b contract requires
  end-user-guide documentation for Public vars -- developer docs alone are insufficient. Surfaces:
  `docs/end-user/hook.md` (user-facing), developer docs with the command-scoped example
  (`FORGE_DEV="$PWD" uv run forge session start ...`) and the relaunch-required note, §A.7b row, and the
  `test_env_vocabulary.py` mapping -- all in the same change as the first user-facing string naming it.

## Phase 1: Shim override branch + recording fix

Override branch (D3/D4):

- [x] Add the `FORGE_DEV` branch to the shim source as its own resolution path -- after the gate and the missing-handler
  check, replacing the normal candidate loop when present: presence via `"FORGE_DEV" in os.environ`; validate non-empty
  absolute checkout root after `~` expansion; target `<root>/.venv/bin/forge` must be an executable file; expansion +
  `os.execv` wrapped (`RuntimeError`/`OSError`). Any failure -> exit 127, stderr names `FORGE_DEV`
  - the checked target; the recorded/global candidates are NEVER tried. `_GATE_SOURCE` stays byte-identical. Assertions:
  * override set + valid -> execs `<checkout>/.venv/bin/forge` regardless of the cwd project's own `.venv`;
  * override unset -> **same ordered resolution behavior** as the shipped shim (recorded -> global bins), asserted
    behaviorally, not on the internal candidate list;
  * override set + missing/non-executable/relative/empty/unexpandable target -> exit 127, stderr names `FORGE_DEV`, no
    fallback; empty value is present-and-invalid;
  * override set + no handler argv -> exit 2, no exec (handler validation precedes the override branch);
  * override set + executable whose execv fails (stale shebang interpreter) -> `OSError` caught -> same loud exit 127;
  * non-enrolled cwd, no session, `FORGE_DEV` set -> exit 0 before any resolution (gate untouched);
  * absolute checkout path containing spaces resolves and execs correctly. Implemented in the rendered stdlib source
    with subprocess fixtures for valid cross-project/spaced paths, every invalid-value class, failed `execv`, handler
    ordering, and the unchanged no-op gate.

Recording fix (D2):

- [x] Characterize the sticky path through the injectable `install_hook_dispatcher(environ=..., which=..., argv0=...)`
  seams, then pin the replacement behavior: dev-shell venv discovery no longer records `.venv/bin/forge`, while stable
  non-venv metadata survives unusable discovery.
- [x] Implement the D2 selector: a new higher-level recording function owning the four-step transition table
  (`known_forge_launcher_paths()` unchanged as the static fallback-list helper), lexical venv classification,
  explicit-`forge_binary_path=` authority, legacy `.venv` metadata replace-or-clear. Fixture matrix: first-time custom
  install; A->B global launcher migration; global symlink whose realpath is a tool venv (stays non-venv); venv discovery
  against valid / stale / venv recorded targets; `which` vs `argv0` parity; project/local enable AND user sync entry
  points. `tests/src/install/test_hook_dispatcher.py` covers the selector matrix;
  `tests/src/cli/test_extension_enable.py` covers project/local enable and user sync.
- [x] Package-side parity: doctor-facing candidate/selection reporting uses the same selector, so doctor never describes
  a different resolution or recording decision than the shim/installer performs.
- [x] Tests extend the existing rendered-shim execution suite in `tests/src/install/test_hook_dispatcher.py` (render
  script -> run via `python3` subprocess with a controlled env), not source-string asserts.
- [x] Execute the byte-stability guard: implementation leaves `render_dispatcher_command()` and
  `tests/src/install/test_registered_commands_contract.py` unchanged; the golden contract passed in the 308-test focused
  command, so no registered byte moved and no Codex re-trust is triggered.

## Phase 2: Doctor + docs

- [x] `forge extension doctor` surfaces the override under `hook_dispatcher.dev_override` (human + `--json`) with a
  defined contract:
  `{present: bool, value: string|null, target: string|null, valid: bool, effective: bool, advice: string|null}`. `valid`
  = the D3/D4 target checks pass; `effective` = `valid` AND the installed shim status is `current` AND the shim is
  executable -- a stale pre-T8 or mode-drifted shim cannot honor the override, and doctor must report that split rather
  than imply activity (advice names `forge extension sync` for stale source and permission repair for mode drift). Label
  it env-derived state: doctor sees its own environment, which may differ from a hook's launch environment. Human output
  escapes env-derived values; JSON fixtures cover set/unset and valid/invalid states.
- [x] Stale-shim surfacing is covered as the upgrade path: the doctor fixture pins source-hash drift independently of
  the version stamp, and sync retains the existing re-render path. The fixture passed in the Phase 3 focused command.
- [x] Docs: `design.md` §3.10 deployment-model paragraph (the resolver narrative names the override); `design_appendix`
  §C.4 (override branch precedence + the D2 recording table) and §A.7b row (**Public**, per D6);
  **`docs/end-user/hook.md`** (Public-contract user surface); developer docs (`CLAUDE.md` / `docs/developer/`) with the
  command-scoped example and the relaunch-required note. `docs/cli_reference.md` also defines the doctor payload. All
  six changed doc surfaces passed mdformat; claims were checked against the rendered/package implementation.
- [x] `tests/src/cli/test_env_vocabulary.py` parity row matches the appendix table (Public class): targeted guard passed
  (`9 passed`).
- [x] D5 write-back: `todo/forge_project_compat_mutator_sweep/card.md` Design Rules records the resolved outcome ("T8
  adds no special bypass; sweep owns hook enforcement"). Done 2026-07-11; evidence wording corrected in round 2 (strict
  enforcement = `cli/guards.py` + `cli/extensions.py`).
- [x] Card kept consistent with the ratified decisions: Grounding correction (sticky-sync), Open questions resolved, and
  the Design section rewritten from "Decide between" to the resolved design (round 2). Done 2026-07-11.

## Phase 3: Verification

- [x] Focused units:
  `uv run pytest tests/src/install/test_hook_dispatcher.py tests/src/install/test_doctor.py tests/src/cli/test_env_vocabulary.py tests/src/install/test_registered_commands_contract.py tests/src/cli/test_extension_enable.py tests/src/core/reactive/test_env.py tests/src/session/test_codex_invoke.py tests/src/core/invoker/test_codex_invoker.py -q`
  -> **308 passed**. This includes the real local/project enable and user-sync entry points.
- [x] Targeted integration (installer/hooks touched; unit alone is not enough signal), extended with an actual T8 case
  -- the rendered dispatcher honors a valid `FORGE_DEV` and fails loud on an invalid one inside the container -- not
  only the pre-existing suite: `./scripts/test-integration.sh tests/integration/docker/test_installer.py -v` -> **17
  passed**.
- [x] Wheel/clean-install verification: `uv build` produced the sdist and wheel. Installing the wheel into an isolated
  `UV_TOOL_DIR`/`UV_TOOL_BIN_DIR`, then running `forge extension enable --scope user` **then** `forge extension sync` +
  `forge extension doctor` there confirmed that the rendered shim carries the override branch. Doctor reported
  `install_kind=global`, the isolated launcher recorded, and dispatcher `status=current`; the rendered artifact
  contained the `FORGE_DEV` validation/exec branch.
- [x] Live dev-loop smoke on this checkout: `forge extension sync --scope local` re-rendered the real user dispatcher.
  Command-scoped `FORGE_DEV="$PWD" ~/.forge/bin/forge-hook <name>` with stub stdin from an enrolled root confirmed that
  the checkout binary ran (`policy-check`, exit 0). The negative
  `FORGE_DEV=/nonexistent ~/.forge/bin/forge-hook policy-check` exited 127 and named both `FORGE_DEV` and
  `/nonexistent/.venv/bin/forge`.
- [x] `make pre-commit` clean after isort/mdformat normalization and the explicit optional-path type annotation.

## Acceptance tests

Override branch:

| Test                           | Fixture                                                            | Assertion                                                                 | Test File                                   |
| ------------------------------ | ------------------------------------------------------------------ | ------------------------------------------------------------------------- | ------------------------------------------- |
| Dev override resolves checkout | `FORGE_DEV=<checkout>`, enrolled cwd                               | shim execs `<checkout>/.venv/bin/forge`, not the recorded/global launcher | `tests/src/install/test_hook_dispatcher.py` |
| Override names the checkout    | `FORGE_DEV=<checkout>`, hook fires in a different enrolled project | named checkout's forge resolves, not that project's `.venv`               | same                                        |
| Unset -> unchanged resolution  | `FORGE_DEV` unset                                                  | same ordered resolution behavior as the shipped shim (recorded -> global) | same                                        |
| Cwd venv never implicit        | override unset; cwd checkout has its own `.venv/bin/forge`         | cwd alone never selects that launcher; recorded/known resolution wins     | same                                        |
| Invalid override fails loud    | `FORGE_DEV=/nonexistent`                                           | exit 127; stderr names `FORGE_DEV` + checked path; no fallback (D4)       | same                                        |
| Empty/relative rejected        | `FORGE_DEV=""` (present via `in`), `FORGE_DEV=rel/path`            | present-and-invalid -> loud 127; never treated as unset or cwd-relative   | same                                        |
| Unexpandable value rejected    | `FORGE_DEV=~nosuchuser/x`                                          | `RuntimeError` caught -> loud 127                                         | same                                        |
| Spaced path resolves           | absolute checkout root containing spaces                           | target resolves and execs correctly                                       | same                                        |
| Failed execv fails loud        | override target whose execv raises (stale shebang interpreter)     | `OSError` caught -> exit 127 naming `FORGE_DEV`                           | same                                        |
| Handler validation precedes    | `FORGE_DEV` set, missing hook name argv                            | exit 2, no exec                                                           | same                                        |
| Gate unaffected                | non-enrolled cwd, no session, `FORGE_DEV` set                      | exit 0 before resolution                                                  | same                                        |

Recording selector (D2 table):

| Test                            | Fixture                                                           | Assertion                                                                | Test File                                   |
| ------------------------------- | ----------------------------------------------------------------- | ------------------------------------------------------------------------ | ------------------------------------------- |
| First-time custom recorded      | no usable recorded target; `which` finds custom non-venv launcher | recorded (rule 1)                                                        | `tests/src/install/test_hook_dispatcher.py` |
| A->B migration records B        | recorded global A; discovery finds non-venv B                     | B replaces A (rule 1)                                                    | same                                        |
| Venv discovery preserves        | valid recorded non-venv target; discovery finds venv launcher     | recorded target preserved (rule 2)                                       | same                                        |
| Missing discovery preserves     | valid recorded non-venv target; discovery returns none/unusable   | recorded target preserved (rule 2), never cleared                        | same                                        |
| Venv never recorded             | venv discovery; no usable recorded target                         | known-global fallback or null -- never a `pyvenv.cfg`-sibling path (3-4) | same (regression)                           |
| Lexical classification          | `~/.local/bin/forge` symlink whose realpath is a uv tool venv     | classified non-venv from the symlink location; realpath never consulted  | same                                        |
| No-guess fallback               | rule-3 candidate missing or non-executable                        | records null (never an unverified path); doctor advises                  | same + `tests/src/install/test_doctor.py`   |
| Legacy sticky metadata migrated | existing `runtime.json` carrying `.venv/bin/forge`                | next enable/sync replaces or clears it per the table                     | same                                        |
| which vs argv0 parity           | same launcher discovered via `which` and via `argv0`              | identical classification and recording outcome                           | same                                        |

Doctor, env, and byte contracts:

| Test                            | Fixture                                             | Assertion                                                                  | Test File                                                      |
| ------------------------------- | --------------------------------------------------- | -------------------------------------------------------------------------- | -------------------------------------------------------------- |
| Doctor surfaces override        | env set/unset x valid/invalid target                | `dev_override` JSON contract (`present`/`value`/`target`/`valid`/`advice`) | `tests/src/install/test_doctor.py`                             |
| Validity vs effectiveness split | valid override + stale installed shim               | `valid=true, effective=false`; advice names `forge extension sync`         | same                                                           |
| Mode drift is ineffective       | valid override + source-current non-executable shim | `valid=true, effective=false`; advice names permission repair              | same                                                           |
| Stale-shim doctor effectiveness | installed pre-T8 shim, post-T8 package              | doctor reports `stale` (source-hash drift) until sync                      | same                                                           |
| Env propagation                 | `FORGE_DEV` exported, managed-session env builders  | value present in the built subprocess env for both runtimes                | `test_env.py`, `test_codex_invoke.py`, `test_codex_invoker.py` |
| No re-trust / byte stability    | rendered Claude + Codex registrations               | registered-commands golden byte-identical                                  | `tests/src/install/test_registered_commands_contract.py`       |
| Env vocab parity                | `FORGE_DEV` row in §A.7b (Public)                   | vocabulary guard passes with the new mapping                               | `tests/src/cli/test_env_vocabulary.py`                         |

## Blockers / deferred

- ~~Stop point: D1-D6 awaiting ratification~~ -- cleared 2026-07-11 (two review rounds; outcomes above).
- Sidecar override: non-goal by construction (no dispatcher in-container; seam 5). Recorded, not a gap.
- Multi-checkout / per-project dev mapping: out of scope; `FORGE_DEV` is one process-env value by design.
- Hook-path `required_forge` enforcement: not this card -- owned by `todo/forge_project_compat_mutator_sweep/` (D5;
  standalone follow-up, not an epic member).

## Closeout

- [x] `change_log.md` entry records the goal, key changes, and complete branch verification without claiming shipment.
- [x] Durable lessons -> `impl_notes.md` after two rounds of human review: resolution-vs-gate boundary, total D2
  transition table, lexical launcher classification, and the separate hard branch required by a fail-loud override.
- [x] `design.md` §3.10 / `design_appendix` §C.4 / §A.7b / `docs/end-user/hook.md` verified against the implemented
  behavior; no shipped-state claim is made before merge.
- [x] Card `doing/ -> done/`; inbound links repointed (epic card members table, epic checklist focus, the
  `proposed/statusline_gui_reachability` Related row).
- [x] Epic notified: T8 was the last live member -- epic closeout items (seam boxes, design-doc verification, epic lane
  move) become actionable.
