# Execution checklist: T7 `forge_project_compat`

Epic: [`epic_global_forge_runtime`](../epic_global_forge_runtime/card.md). Card: [`card.md`](card.md).

## Current focus

**Implementation pass underway.** The `.forge/project.toml` reader/enforcer, extension/session command-path guard set,
and doctor surface are implemented on `forge-project-registry`. The remaining risk is the broader mutation-family sweep
named below; do not close T7 until that sweep is either wired or split to a follow-up card.

## Scope boundary (what is NOT in T7)

- **Authoring `.forge/project.toml` -> hand-edit for v1 (no tooling to build).** T7 only *reads and enforces*
  `required_forge`; **v1 authoring is a human hand-editing the file** (fully consistent with the opt-in framing -- the
  guardrail activates only when a project explicitly declares `required_forge`). T7 Phase 3 documents the file format
  for humans. An "author this file for me" convenience is deferred and, if ever built, attaches to T3's enrollment
  surface -- it is not scheduled here or in T3.
- **Dev-override interaction -> T8.** Whether a contributor's checkout-local `forge` (`forge_dev_runtime_override`)
  bypasses the guardrail is a T8-coupled decision; T7 records it as owed, does not implement bypass logic on its own.

## Accepted framing (epic D1 -- do not relitigate)

`required_forge` is a **fail-clear guardrail, not a version manager.** One global binary couples all enrolled projects
to one Forge version (D1 accepts this). The guardrail makes an incompatible pin produce an actionable error ("upgrade
the global Forge" or "reset project state"), never silent corruption or a silently-ignored project. Multi-version
isolation is out of scope.

## Phase 0 -- Semantics, chokepoint, module home + owed decision (the review checkpoint)

- [x] **Confirm the backward-compat invariant against current `main`:** project identity today is exactly `.claude/` +
  `.forge/` (design.md §3 identity model), so **every existing Forge project lacks `.forge/project.toml`.** Re-verify no
  reader of that file exists yet (T3's greenfield sweep already confirmed zero `project.toml` refs in `src`/`tests` on
  2026-07-07).
- [x] **Pin the three input states** so they are not conflated (each has a distinct posture):
  - **Missing file -> compatible / unconstrained.** No error, no warning, no blocked mutation; the file is **opt-in**
    and **no auto-create** (that invents a `required_forge` value nobody chose and churns every existing project).
  - **Malformed / unsupported-schema file -> strict on the command path, lenient on the hook path** (the same split T3's
    registry uses): a CLI/command read **fails clear** with a fix hint; a session/context hook reader degrades to
    unconstrained with a diagnostic reason and `doctor` is the authoritative surfacing point (do not brick a coding
    session for a config typo).
  - **Valid file, incompatible `required_forge` -> the D-T7-a matrix** (below).
- [x] **Enumerate the mutation entry points + choose the chokepoint layer.** "Every state-mutating command/hook calls
  it" is unverifiable until the set is named. Enumerated set: `forge extension enable/sync/disable`, `disable --all`,
  session lifecycle commands that pass through `require_repo_root()` / `require_main_repo_root()` (`start`, `fork`,
  `resume`, `incognito`, Codex lifecycle entry), hook `confirmed`-state writes, memory-writer doc writes, and
  proxy/backend global registry writes. Chosen layer is a small named guard set, not one universal chokepoint. First
  implementation slice covers extension lifecycle plus shared session repo-root guards. Remaining explicitly uncovered:
  hook confirmed-state writes, memory-writer doc writes, and proxy/backend registry mutations.
- [x] **Decide the module home** (mirror rule): read+enforce guardrail lives in `src/forge/install/project_compat.py`;
  test mirror is `tests/src/install/test_project_compatibility.py`.
- [x] **DECISION D-T7-a (fail-open/closed matrix) -- RESOLVED 2026-07-07:** command paths fail closed; session/context
  hook readers fail open with a degraded diagnostic; policy hook blocking stays governed by existing policy fail-mode
  settings unless a future project strictness flag is explicitly added.

## Phase 1 -- Schema `.forge/project.toml`

- [x] **Schema**: `schema_version` (durable state, strictly read -- unsupported version handled per the three-state
  rule)
  - `required_forge` = a **PEP 440 version specifier** (`packaging.specifiers.SpecifierSet`) compared against the
    running `multi-forge` version. Live **beside `install/version.py`**, which already imports
    `from packaging.version import ...` and does `Version` comparisons in `check_minimum_version` -- reuse it; **no
    hand-rolled version comparison** (`packaging>=21.0` is already a dependency).
- [x] **Missing / absent file** returns a "compatible, unconstrained" result object -- never raises, never warns (the
  Phase 0 invariant, enforced in code).

## Phase 2 -- Enforcement chokepoint

- [x] **First named guard set called before mutating.** Covered now: extension `enable`/`sync`/`disable`/`disable --all`
  and shared session repo-root guards. The broader mutation sweep remains open below.
- [x] **Incompatible-pin behavior for the implemented command paths** applied per D-T7-a. A mismatch on a command/CLI
  path produces an actionable error naming the upgrade/reset path; a compatible pin is a silent no-op. The lenient hook
  helper is implemented, but live hook warning/wiring is part of the remaining sweep.
- [x] **Doctor strict-read surface:** extend `forge extension doctor` to strict-read `.forge/project.toml` and report
  malformed/unsupported-schema or incompatible state with the same fix hint. Missing file remains compatible and should
  not warn.
- [ ] **Remaining mutator sweep:** wire or explicitly split follow-up coverage for hook confirmed-state writes,
  memory-writer doc writes, and proxy/backend registry mutations. This is the remaining condition before claiming every
  state-mutating path observes `.forge/project.toml`. If the sweep splits to a follow-up card before release, move the
  lenient hook helper with its first production caller rather than shipping unused contract code indefinitely.

Acceptance (Phases 1--2):

| Test                        | Fixture                                         | Assertion                                                          | Test File                                               |
| --------------------------- | ----------------------------------------------- | ------------------------------------------------------------------ | ------------------------------------------------------- |
| Missing file is compatible  | existing project, no `.forge/project.toml`      | no error, no warning; state mutates normally                       | `tests/src/install/test_project_compatibility.py` (new) |
| Malformed fails clear (CLI) | `project.toml` with a garbled body on a command | CLI read fails clear with a fix hint (not silent-degrade)          | same                                                    |
| Malformed degrades (hook)   | same file read by the lenient hook helper       | helper treats as unconstrained with `degraded`; doctor surfaces it | same                                                    |
| Incompatible pin blocks     | `required_forge` incompatible with global Forge | actionable error naming the upgrade/reset path (command path)      | same                                                    |
| Fail-open honored (hook)    | lenient hook helper, incompatible pin           | helper allows with `degraded` (does not block the session)         | same                                                    |
| Compatible is a no-op       | `required_forge` (SpecifierSet) satisfied       | no error, state mutates normally                                   | same                                                    |
| Strict schema (command)     | `project.toml` with unknown `schema_version`    | clear unsupported-version error on the command path                | same                                                    |

## Phase 3 -- Design-doc sync

- [x] `design.md` §3 project-identity model: document `.forge/project.toml` as the **opt-in** compatibility guardrail
  (missing-file = compatible default; not part of project identity, which stays `.claude/` + `.forge/`), and the
  three-state posture.
- [x] **Disambiguate the lookalike files:** `.forge/project.toml` (repo-local, user-authored compat pin) vs
  `~/.forge/projects.json` (user-global, machine-written trust registry) -- one line, since both arrive in this epic and
  differ by one character in prose.
- [x] Note D1 (version coupling accepted) where the guardrail is described, so future readers see the trade, not a gap.

## Closeout

- [ ] All Phase 1--3 assertions verified; acceptance tests green.
- [ ] `make pre-commit` clean; integration run if a hook path enforces the guardrail.
- [ ] `change_log.md` entry; durable lessons proposed for `impl_notes.md` if any (chokepoint enumeration pattern,
  three-state posture, SpecifierSet reuse).
- [ ] Epic checklist: note T7 shipped (off-path member).
- [ ] Move `doing/forge_project_compat/ -> done/`; repoint inbound epic/member links.
