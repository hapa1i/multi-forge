# Project compatibility guardrail (`required_forge`)

**Epic**: [`docs/board/doing/epic_global_forge_runtime/card.md`](../epic_global_forge_runtime/card.md)

**Lane**: `doing/`. Independent -- a check layered on project state. Can land any time, even before the hook-ownership
tickets.

## Goal

`<repo>/.forge/project.toml` carrying `schema_version` + `required_forge`. Every command/hook that mutates project state
checks it and **fails clearly** on mismatch, naming the resolution path.

## Accepted decision (epic D1)

One global binary couples all enrolled projects to one Forge version. **We accept that this caps per-project version
flexibility.** `required_forge` is a **fail-clear guardrail, not a version manager.** Multi-version isolation is out of
scope. The guardrail exists so an incompatible pin produces an actionable error ("upgrade the global Forge" or "reset
project state"), never silent corruption or a silently-ignored project.

Rationale: it matches the git/gh/claude/codex model; Forge is a research preview that already clean-breaks durable state
(`coding_standards` §5), so per-project version pinning was never a stable guarantee. A deliberate trade of flexibility
for a single, legible runtime.

## Missing-file semantics (2026-07-02 finding)

Project identity today is exactly `.claude/` + `.forge/` (`design.md:82,92`) -- **no `project.toml`**. So **every
existing Forge project lacks the file.** The guardrail must therefore treat absence as the safe, non-breaking default:

- **Missing `project.toml` -> compatible / unconstrained.** No error, no warning, no blocked mutation. The file is
  **opt-in**: the guardrail activates only when a project explicitly declares `required_forge`.
- **No auto-create.** Do not write the file on first state mutation -- that would add churn to every existing project
  and invent a `required_forge` value nobody chose.
- **Absence is never an error.** This keeps the change backward-compatible with the current identity model, which does
  not require `project.toml`.

**v1 authoring is hand-edit only** (a human writes `required_forge`); T3 ships **no** authoring command for this file
(the `forge_project_registry` checklist scope-boundary confirms it). An opt-in "author this file for me" convenience is
**deferred** and, if ever built, would attach to T3's enrollment surface -- do not assume one here or plan T3/T7 work
around it.

## Design

- **`.forge/project.toml`**: `schema_version` (durable state, strictly read) + `required_forge` (a version range).
- **Single enforcement chokepoint**: one function that every state-mutating command/hook calls before mutating -- avoid
  sprinkling the check across dozens of call sites.
- **Fail-open/closed matrix per hook type** (decision owed): candidate -- session/context hooks fail **open** with a
  warning (never block the coding session); policy hooks obey a project strictness flag. Consistent with the fail-open
  posture for policy evaluations (`design_workflows` §1.2).

## Risks

- **Check-site sprawl** without a single chokepoint.
- **False-blocking during rapid iteration**: Forge clean-breaks state often; the guardrail must name the reset/upgrade
  path, and its fail-open default must not brick a coding session.
- Interaction with `forge_dev_runtime_override`: a contributor running a checkout `forge` against a project pinned to a
  released range -- decide whether the dev override bypasses the guardrail.

## Open questions

- Exact fail-open vs fail-closed matrix per hook type.
- Whether `required_forge` is enforced when a contributor runs checkout-local Forge (interacts with
  `forge_dev_runtime_override`).

## Acceptance tests

| Test                       | Fixture                                         | Assertion                                                      | Test File                                           |
| -------------------------- | ----------------------------------------------- | -------------------------------------------------------------- | --------------------------------------------------- |
| Missing file is compatible | existing project, no `.forge/project.toml`      | no error, no warning; state mutates normally                   | `tests/src/cli/test_project_compatibility.py` (new) |
| Version mismatch blocks    | `required_forge` incompatible with global Forge | actionable incompatibility error naming the upgrade/reset path | same                                                |
| Compatible is a no-op      | `required_forge` satisfied                      | no error, state mutates normally                               | same                                                |
| Fail-open honored          | session/context hook, incompatible pin          | hook warns and allows (does not block the session)             | same                                                |
| Strict schema              | `project.toml` with unknown `schema_version`    | clear unsupported-version error                                | same                                                |
