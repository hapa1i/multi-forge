# Global Forge install + Day-1 docs

**Epic**: [`docs/board/done/epic_global_forge_runtime/card.md`](../../done/epic_global_forge_runtime/card.md)

**Lane**: `done/` -- shipped via PR #89 and closed 2026-07-06. Foundational member (no dependencies); execution record
in [`checklist.md`](checklist.md). Ships global-tool Day-1 docs + `forge extension doctor`.

## Goal

Make **global tool install** the recommended, documented Day-1 path (`uv tool install multi-forge` /
`pipx install multi-forge`), keeping PyPI as the release channel. Add `forge extension doctor` to report how Forge was
installed and whether it is globally reachable.

## Why

The exit-127 root cause is the per-project runtime model: `forge` lives in a project `.venv`, so a bare `forge hook`
command is unreachable outside an activated venv. A global `forge` on `PATH` fixes the common interactive-shell case and
removes the "neither clearly project-local nor clearly global" ambiguity. This is the smaller half of the epic's D2
split (bug fix, not migration).

## Scope

**In:**

- Document `uv tool install multi-forge` / `pipx install multi-forge` as the recommended install; update `README.md`,
  `docs/end-user/` setup, and any quickstart.
- Keep the Forge-contributor path (`uv sync` / `pip install -e .`) documented and distinct from end-user install.
- `forge extension doctor`: report install kind (global tool vs. editable/venv vs. unknown), the resolved `forge` path,
  and whether it is on `PATH` in a plain shell.

**Out:** hook scope changes (`user_scope_hook_ownership`), the dispatcher (`forge_hook_dispatcher`), removing PyPI, a
version manager (D1).

## Grounding (verified 2026-07-02)

- End-user `README.md:99` currently says `pip install multi-forge`; uninstall `pip uninstall` (`:211`).
- Contributor workflow uses per-project venv via `uv sync` (`CLAUDE.md:14`, `CONTRIBUTING.md:12`) -> `.venv/bin/forge`.
- `uv tool install` / `pipx install` appear only in the epic today, in no shipped doc.

## Risks

- Users with an existing editable/venv install: `forge extension doctor` should detect it and advise the global-tool
  path without breaking their current setup.
- `uv tool` vs `pipx` place the real script in different locations (`~/.local/bin`, etc.); doctor must resolve both.

## Open questions

None blocking. (The dispatcher's cross-upgrade reachability lives in `forge_hook_dispatcher`, not here.)

## Acceptance tests

| Test                        | Fixture                            | Assertion                                                                  | Test File                                |
| --------------------------- | ---------------------------------- | -------------------------------------------------------------------------- | ---------------------------------------- |
| Docs show global install    | rendered end-user docs             | `uv tool install` / `pipx install` present; contributor path kept distinct | doc check                                |
| Doctor reports install kind | global-tool install                | `forge extension doctor` names the resolved path + PATH reachability       | `tests/src/install/test_doctor.py` (new) |
| Doctor flags venv-only      | editable/venv install, not on PATH | doctor reports "not globally reachable" + advises global install           | same                                     |
