# Dev-mode runtime override (checkout-local Forge)

**Epic**: [`docs/board/doing/epic_global_forge_runtime/card.md`](../../doing/epic_global_forge_runtime/card.md)

**Lane**: `done/` -- shipped via PR #97 (`46ff9ef6`) and closed out on `main`; verification is preserved in
[`checklist.md`](checklist.md). Off the critical path; pairs with `forge_hook_dispatcher` (the override is honored in
the same resolution contract).

## Goal

A first-class way for **Forge contributors** to make the dispatcher run a checkout-local `forge`, so hooks invoke the
code under development -- not the released global tool.

## Why

The original card omitted this (surfaced in the 2026-07-02 review). After the migration, a contributor editing Forge
would have their hooks silently run the **global** `forge`, not their branch -- a daily-loop regression for maintainers,
who are the people most likely to run unreleased Forge in a real session.

## Design

Resolved 2026-07-11 (maintainer review, two rounds; decision record in [`checklist.md`](checklist.md) Phase 0):

- **Mechanism (D1)**: `FORGE_DEV=/path/to/forge/checkout` env override -- explicit, process-scoped, reversible runtime
  selection that mutates no global runtime metadata. Managed launches inherit it (the session environment builders copy
  `os.environ`). The `uv run forge`-only alternative was rejected.
- **Target form (D3)**: the value names the checkout root -- a non-empty **absolute** path after `~` expansion -- and
  the dispatcher execs `<path>/.venv/bin/forge`. No boolean form (`FORGE_DEV=1` is ambiguous when the hook fires inside
  a *different* enrolled project) and no `uv run --project` form (one unambiguous exec target).
- **Precedence (D4)**: a separate hard branch after the no-op gate and missing-handler validation. When `FORGE_DEV` is
  present (including empty = present-and-invalid) the dispatcher uses exactly the named target or fails loud (exit 127
  naming the variable); it never falls through to the recorded/global resolution.
- **Recording (D2)**: implicit sticky dev selection is removed via a deterministic transition table -- a discovered venv
  launcher never replaces a stable recorded launcher, and classification is lexical (never resolve a global symlink into
  its tool venv). `FORGE_DEV` is the only first-class *transient* checkout override; the persistent dev path is the
  deliberate global editable install (`scripts/setup.sh`).
- **Guardrail (D5)**: no `required_forge` bypass -- T8 left the compatibility posture unchanged; hook-path pin
  enforcement later shipped in the [`forge_project_compat_mutator_sweep`](../forge_project_compat_mutator_sweep/card.md)
  follow-up via PR #98.
- **Classification (D6)**: `FORGE_DEV` is a **Public** env var (§A.7b), documented in the end-user hook guide and
  developer docs; a running session must be relaunched to pick up a changed value.

## Grounding (verified 2026-07-02)

- Contributors currently rely on `.venv/bin/forge` via `uv sync` (`CLAUDE.md:14`); the global-dispatcher model removes
  that implicit path from hooks unless this override exists.
- **Correction (2026-07-11, Phase 0):** the "removes that implicit path" claim above is only partially true against the
  shipped dispatcher -- `find_current_forge_binary` records whatever `forge` is on PATH when *any* installer scope
  rewrites `~/.forge/runtime.json` (`installer.py:935` calls `_ensure_hook_dispatcher()` unconditionally), so a
  dev-shell enable/sync sticky-points ALL hook dispatch at `.venv/bin/forge` by accident. T8's D2 removes that implicit
  selection; `FORGE_DEV` becomes the only first-class *transient* checkout override, while the deliberate persistent dev
  path is the global editable install (`scripts/setup.sh` runs `uv tool install -e --force .`). Decision record:
  [`checklist.md`](checklist.md) Phase 0.
- `forge extension doctor` (T1) already exposes this seam: `install_kind` reads the *running* interpreter's metadata
  while `forge_path`/`on_path` read PATH resolution, so a contributor with both a dev checkout and a global install can
  see `kind=editable` beside a global `forge_path` (documented in `diagnose_install`'s docstring). T8 owns making the
  dev runtime authoritative for hooks; doctor's reporting should stay consistent with whatever precedence T8 defines.

## Risks

- An override that leaks into non-dev environments would silently run the wrong Forge in production hooks -- opt-in must
  be explicit and unambiguous.
- Precedence collisions with the dispatcher's recorded global-path resolution.

## Open questions

Both resolved in maintainer review 2026-07-11; outcomes recorded in [`checklist.md`](checklist.md) Phase 0.

- ~~`FORGE_DEV=/path` (checkout-pointing) vs `uv run forge`-only~~ -- **resolved: `FORGE_DEV` env override** (D1), with
  the D2 recording fix ending today's implicit sticky dev selection.
- ~~Does the dev override bypass the `forge_project_compat` `required_forge` guardrail?~~ -- **resolved: T8 adds no
  special bypass** (D5). At T8 closeout, hooks did not enforce the pin; the later
  [`forge_project_compat_mutator_sweep`](../forge_project_compat_mutator_sweep/card.md) follow-up shipped that
  enforcement via PR #98.

## Acceptance tests

| Test                           | Fixture                                                         | Assertion                                                                     | Test File                                   |
| ------------------------------ | --------------------------------------------------------------- | ----------------------------------------------------------------------------- | ------------------------------------------- |
| Dev override resolves checkout | override set in a Forge checkout                                | dispatcher resolves to the checkout `forge`, not the global tool              | `tests/src/install/test_hook_dispatcher.py` |
| Override names the checkout    | `FORGE_DEV=/path`, hook fires in a *different* enrolled project | dispatcher resolves the named checkout's `forge`, not that project's `.venv`  | same                                        |
| No override -> normal resolver | override unset; valid recorded global launcher                  | recorded launcher wins; invalid/missing records fall through to known globals | same                                        |
| Cwd venv never implicit        | override unset; cwd checkout has its own `.venv/bin/forge`      | cwd alone never selects that launcher; recorded/known resolution wins         | same                                        |
