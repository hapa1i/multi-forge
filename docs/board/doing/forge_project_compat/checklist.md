# Execution checklist: T7 `forge_project_compat`

Epic: [`epic_global_forge_runtime`](../epic_global_forge_runtime/card.md). Card: [`card.md`](card.md).

## Current focus

**Pre-implementation review checkpoint.** Card picked up (`proposed/ -> doing/`); **no code yet**. T7 is fully
independent -- a `required_forge` compatibility guardrail layered on project state -- so it can land any time and does
**not** block on T3. It ships its own branch/PR at implementation (currently activated alongside T3 on
`forge-project-registry` for review only). Two Phase-0 decisions are owed before Phase 2: the fail-open/closed matrix
(D-T7-a) and the chokepoint layer + module home.

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

- [ ] **Confirm the backward-compat invariant against current `main`:** project identity today is exactly `.claude/` +
  `.forge/` (design.md §3 identity model), so **every existing Forge project lacks `.forge/project.toml`.** Re-verify no
  reader of that file exists yet (T3's greenfield sweep already confirmed zero `project.toml` refs in `src`/`tests` on
  2026-07-07).
- [ ] **Pin the three input states** so they are not conflated (each has a distinct posture):
  - **Missing file -> compatible / unconstrained.** No error, no warning, no blocked mutation; the file is **opt-in**
    and **no auto-create** (that invents a `required_forge` value nobody chose and churns every existing project).
  - **Malformed / unsupported-schema file -> strict on the command path, lenient on the hook path** (the same split T3's
    registry uses): a CLI/command read **fails clear** with a fix hint; a session/context *hook* warns + degrades to
    unconstrained + is surfaced by `doctor` (do not brick a coding session for a config typo).
  - **Valid file, incompatible `required_forge` -> the D-T7-a matrix** (below).
- [ ] **Enumerate the mutation entry points + choose the chokepoint layer.** "Every state-mutating command/hook calls
  it" is unverifiable until the set is named. Enumerate at least: `forge extension enable/sync/disable`; session
  `start`/`fork`/`resume` manifest writes; hook `confirmed`-state writes; memory-writer doc writes; proxy/backend
  registry writes. Then decide whether **one chokepoint function** is feasible or it is a **small named set of guards**
  -- the acceptance table cannot cover a set that was never named.
- [ ] **Decide the module home** (mirror rule): a read+enforce guardrail likely lives in `install/` or `core/`, **not**
  `cli/`. Name the test file from the module once decided -- the acceptance paths below are **provisional** on this.
- [ ] **DECISION D-T7-a (fail-open/closed matrix per hook type, owed):** candidate -- session/context hooks fail
  **open** with a warning (never block the coding session); policy hooks obey a project strictness flag. Consistent with
  the policy fail-open posture (design_workflows §1.2). Resolve before Phase 2 wires enforcement into hook paths.

## Phase 1 -- Schema `.forge/project.toml`

- [ ] **Schema**: `schema_version` (durable state, strictly read -- unsupported version handled per the three-state
  rule)
  - `required_forge` = a **PEP 440 version specifier** (`packaging.specifiers.SpecifierSet`) compared against the
    running `multi-forge` version. Live **beside `install/version.py`**, which already imports
    `from packaging.version import ...` and does `Version` comparisons in `check_minimum_version` -- reuse it; **no
    hand-rolled version comparison** (`packaging>=21.0` is already a dependency).
- [ ] **Missing / absent file** returns a "compatible, unconstrained" result object -- never raises, never warns (the
  Phase 0 invariant, enforced in code).

## Phase 2 -- Enforcement chokepoint

- [ ] **The chokepoint layer chosen in Phase 0** -- one function, or the named guard set -- called before mutating.
  Whichever it is, the *enumeration* from Phase 0 is what makes "every mutation is covered" verifiable.
- [ ] **Incompatible-pin behavior per hook type** applied per D-T7-a. A mismatch on a command/CLI path produces an
  **actionable** error naming the upgrade/reset path; a session/context hook warns and allows (fail-open); a compatible
  pin is a silent no-op.
- [ ] **Doctor strict-read surface:** extend `forge extension doctor` to strict-read `.forge/project.toml` and report
  malformed/unsupported-schema or incompatible state with the same fix hint. Missing file remains compatible and should
  not warn.

Acceptance (Phases 1--2) -- test file provisional on the Phase-0 module-home decision:

| Test                        | Fixture                                         | Assertion                                                     | Test File (provisional)                                |
| --------------------------- | ----------------------------------------------- | ------------------------------------------------------------- | ------------------------------------------------------ |
| Missing file is compatible  | existing project, no `.forge/project.toml`      | no error, no warning; state mutates normally                  | `tests/src/<home>/test_project_compatibility.py` (new) |
| Malformed fails clear (CLI) | `project.toml` with a garbled body on a command | CLI read fails clear with a fix hint (not silent-degrade)     | same                                                   |
| Malformed degrades (hook)   | same file read on a session/context hook        | hook warns + treats as unconstrained; `doctor` surfaces it    | same                                                   |
| Incompatible pin blocks     | `required_forge` incompatible with global Forge | actionable error naming the upgrade/reset path (command path) | same                                                   |
| Fail-open honored (hook)    | session/context hook, incompatible pin          | hook warns and allows (does not block the session)            | same                                                   |
| Compatible is a no-op       | `required_forge` (SpecifierSet) satisfied       | no error, state mutates normally                              | same                                                   |
| Strict schema (command)     | `project.toml` with unknown `schema_version`    | clear unsupported-version error on the command path           | same                                                   |

## Phase 3 -- Design-doc sync

- [ ] `design.md` §3 project-identity model: document `.forge/project.toml` as the **opt-in** compatibility guardrail
  (missing-file = compatible default; not part of project identity, which stays `.claude/` + `.forge/`), and the
  three-state posture.
- [ ] **Disambiguate the lookalike files:** `.forge/project.toml` (repo-local, user-authored compat pin) vs
  `~/.forge/projects.json` (user-global, machine-written trust registry) -- one line, since both arrive in this epic and
  differ by one character in prose.
- [ ] Note D1 (version coupling accepted) where the guardrail is described, so future readers see the trade, not a gap.

## Closeout

- [ ] All Phase 1--3 assertions verified; acceptance tests green.
- [ ] `make pre-commit` clean; integration run if a hook path enforces the guardrail.
- [ ] `change_log.md` entry; durable lessons proposed for `impl_notes.md` if any (chokepoint enumeration pattern,
  three-state posture, SpecifierSet reuse).
- [ ] Epic checklist: note T7 shipped (off-path member).
- [ ] Move `doing/forge_project_compat/ -> done/`; repoint inbound epic/member links.
