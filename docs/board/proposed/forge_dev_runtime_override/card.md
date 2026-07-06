# Dev-mode runtime override (checkout-local Forge)

**Epic**: [`docs/board/doing/epic_global_forge_runtime/card.md`](../../doing/epic_global_forge_runtime/card.md)

**Lane**: `proposed/`. Off the critical path; pairs with `forge_hook_dispatcher` (the override is honored in the same
resolution contract).

## Goal

A first-class way for **Forge contributors** to make the dispatcher run a checkout-local `forge`, so hooks invoke the
code under development -- not the released global tool.

## Why

The original card omitted this (surfaced in the 2026-07-02 review). After the migration, a contributor editing Forge
would have their hooks silently run the **global** `forge`, not their branch -- a daily-loop regression for maintainers,
who are the people most likely to run unreleased Forge in a real session.

## Design

Decide between:

- **`FORGE_DEV` override**: point the dispatcher (`forge_hook_dispatcher`) at a checkout-local `forge` instead of the
  recorded global path. **Which checkout must be explicit** -- `FORGE_DEV=1` is ambiguous when the hook fires inside a
  *different* enrolled project (whose `.venv` is not the Forge checkout). Prefer `FORGE_DEV=/path/to/forge/checkout`
  (resolve to `<path>/.venv/bin/forge` or `uv run --project <path> forge`), so the override names the Forge source
  regardless of the cwd the hook runs in.
- **`uv run forge`-only**: no override; contributors never rely on hooks using their checkout, and test unreleased hook
  behavior through explicit `uv run` invocations.

The override, if chosen, must have well-defined precedence over the recorded global path (`forge_hook_dispatcher`) and
must never activate outside an explicit opt-in. Interacts with `forge_project_compat`: decide whether the dev override
bypasses the `required_forge` guardrail.

## Grounding (verified 2026-07-02)

- Contributors currently rely on `.venv/bin/forge` via `uv sync` (`CLAUDE.md:14`); the global-dispatcher model removes
  that implicit path from hooks unless this override exists.

## Risks

- An override that leaks into non-dev environments would silently run the wrong Forge in production hooks -- opt-in must
  be explicit and unambiguous.
- Precedence collisions with the dispatcher's recorded global-path resolution.

## Open questions

- `FORGE_DEV=/path` (checkout-pointing) vs `uv run forge`-only (the epic's dev-workflow open question, owned here).
- Does the dev override bypass the `forge_project_compat` `required_forge` guardrail?

## Acceptance tests

| Test                           | Fixture                                                         | Assertion                                                                    | Test File                                   |
| ------------------------------ | --------------------------------------------------------------- | ---------------------------------------------------------------------------- | ------------------------------------------- |
| Dev override resolves checkout | override set in a Forge checkout                                | dispatcher resolves to the checkout `forge`, not the global tool             | `tests/src/install/test_hook_dispatcher.py` |
| Override names the checkout    | `FORGE_DEV=/path`, hook fires in a *different* enrolled project | dispatcher resolves the named checkout's `forge`, not that project's `.venv` | same                                        |
| No override -> global          | override unset                                                  | dispatcher resolves to the recorded global `forge`                           | same                                        |
| Override never implicit        | override unset in a Forge checkout                              | no accidental checkout resolution (opt-in only)                              | same                                        |
