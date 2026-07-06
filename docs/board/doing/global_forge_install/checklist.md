# Checklist: global_forge_install (T1)

Epic: [`epic_global_forge_runtime`](../epic_global_forge_runtime/card.md) -- first member ("Ship first"). Card:
[`card.md`](card.md). Branch: `global-forge-install`.

## Current focus

Make **global tool install** the documented Day-1 path and add **`forge extension doctor`** to report install kind +
PATH reachability. Read-only reporting plus docs; **no** hook-scope, dispatcher, or registry changes (later members).

## Scope guardrails (from card)

- **IN:** Day-1 docs for `uv tool install multi-forge` / `pipx install multi-forge`; keep the contributor `uv sync` path
  documented and distinct; `forge extension doctor` reporting install kind, resolved `forge` path, PATH reachability.
- **OUT:** hook scope changes (T5), dispatcher (T4), registry (T3), removing PyPI, a version manager (D1). Cross-upgrade
  staleness of a *recorded* absolute path is **T2's** concern, not here.
- **CLI placement:** `doctor` attaches to the existing **`forge extension`** group (epic CLI-surface decision -- no new
  `install` group; `forge info` stays the top-level dashboard). Support `--json` (list/show convention).

## Phase 0 -- Grounding (verify landing points before coding)

- [ ] Confirm the `forge extension` group and how leaves register (`src/forge/cli/extensions.py`); confirm
  `enable/sync/disable/status` are today's leaves (cli_reference Installation table).
- [ ] Define the install-kind detection rule with no guessing: resolved `forge` path (`shutil.which`,
  `sys.argv[0]`/`sys.executable`), editable marker (PEP 610 `direct_url.json` `dir_info.editable`, `*.pth`,
  `__editable__`), and location (`~/.local/bin` launcher vs project `.venv/bin`). **Assertion:** a documented rule per
  kind -- `global` / `editable-or-venv` / `unknown`.
- [ ] Confirm `uv tool` (`~/.local/bin`) vs `pipx` layouts so `doctor` resolves both (card risk).
- Note: keep `doctor` distinct from `forge info` -- it answers "how was Forge installed and is it globally reachable?",
  not the general dashboard.

## Phase 1 -- `forge extension doctor`

- [ ] Add the `doctor` leaf under `forge extension`: report install kind, resolved `forge` path, on-PATH-in-plain-shell
  boolean, and (venv-only) advice to `uv tool install` / `pipx install`.
- [ ] **Minimal-PATH probe (feeds epic D2):** doctor also reports reachability under a GUI/launchd-like minimal PATH
  (`PATH=/usr/bin:/bin:/usr/sbin:/sbin`, which excludes `~/.local/bin`) as a second boolean `on_path_minimal`. This is
  the mechanical evidence for whether the interim T2 fix is still needed after T1 (terminal launch resolves `forge`;
  GUI/Dock launch may not).
- [ ] `--json` emits a stable shape (`install_kind`, `forge_path`, `on_path`, `on_path_minimal`, optional `advice`);
  human output routes through `forge.cli.output` helpers (no hand-rolled `Tip:` / `[red]Error:[/red]` -- CLI style
  guards scan for these).
- [ ] Unit tests `tests/src/install/test_install_doctor.py` (new).
- **Assertion:** `forge extension doctor --json` on a global install returns `install_kind="global"` + the resolved
  launcher path + `on_path=true`; on an editable/venv-not-on-PATH install returns the venv path + `on_path=false` +
  advice. Detection is asserted, never "works".

## Phase 2 -- Day-1 docs

- [ ] `README.md`: recommend `uv tool install multi-forge` / `pipx install multi-forge` (today `pip install`, ~`:99`);
  fix uninstall (~`:211`) to the tool form; keep the contributor `uv sync` path present and clearly labeled.
- [ ] `docs/end-user/` setup / quickstart updated to the global Day-1 path; contributor path (`CLAUDE.md` /
  `CONTRIBUTING.md` `uv sync`) stays distinct.
- **Assertion:** rendered end-user docs show both `uv tool install` and `pipx install multi-forge`; the contributor
  `uv sync` path is present and not conflated with the end-user path.

## Phase 3 -- Design-doc sync (required: CLI + installer + Day-1 behavior change)

- [ ] `docs/cli_reference.md`: add `forge extension doctor` to the Installation table.
- [ ] `docs/design_appendix.md` §C (install model) and/or `docs/design.md` §5.1: record global-tool as the recommended
  install target and `forge extension doctor` as the install-kind/PATH reporter (design docs describe shipped behavior).
- [ ] `docs/end-user/*` install guide reflects Day-1 global install.
- **Assertion:** cli_reference + install-model docs name `forge extension doctor` and the global-install Day-1 path;
  board_contract "Design Doc Sync" satisfied.

## Phase 4 -- Verify + closeout

- [ ] `uv run pytest tests/src/install/test_install_doctor.py -q` + touched CLI/install suites green.
- [ ] `make pre-commit` clean (ruff/black/isort/mypy/pyright/mdformat).
- [ ] Integration consideration: the installer is a "run integration tests" area (CLAUDE.md). `doctor` is read-only, but
  install-kind detection is environment-sensitive -- run a targeted installer integration
  (`./scripts/test-integration.sh tests/integration/docker/test_installer.py`) if detection reads real install layout;
  record the result or an explicit skip rationale.
- [ ] `docs/board/change_log.md` entry (Goal / Key changes / Verification).
- [ ] impl_notes candidate: the install-kind detection rule, if it proves non-obvious.
- [ ] Move `doing/global_forge_install -> done/`; update the epic checklist (tick T1; record the D2 next-member
  decision).

## Acceptance tests

| Test                            | Fixture                                                      | Assertion                                                                                           | Test File                                  |
| ------------------------------- | ------------------------------------------------------------ | --------------------------------------------------------------------------------------------------- | ------------------------------------------ |
| Docs show global install        | rendered README + end-user setup                             | `uv tool install` and `pipx install multi-forge` both present; contributor `uv sync` kept distinct  | doc check (Phase 2)                        |
| Doctor reports global kind      | global-tool install, launcher on PATH                        | names resolved launcher path + `on_path=true`; `--json install_kind="global"`                       | `tests/src/install/test_install_doctor.py` |
| Doctor flags venv-only          | editable/venv install, not on PATH                           | reports the venv `forge` path + `on_path=false` + advises global install                            | `tests/src/install/test_install_doctor.py` |
| Doctor resolves uv-tool vs pipx | `forge` under uv-tool dir; pipx dir                          | both resolve to `install_kind="global"` with the correct path                                       | `tests/src/install/test_install_doctor.py` |
| Doctor minimal-PATH probe (D2)  | `forge` on user PATH, not in `/usr/bin:/bin:/usr/sbin:/sbin` | `--json` reports `on_path=true`, `on_path_minimal=false` -- the GUI/launchd gap that decides D2     | `tests/src/install/test_install_doctor.py` |
| Doctor JSON shape stable        | any install                                                  | `--json` keys = {install_kind, forge_path, on_path, on_path_minimal, advice?}; parse-safe on stdout | `tests/src/install/test_install_doctor.py` |

## Blockers / deferred

- None blocking (card: "Open questions: None blocking").
- Deferred to sibling members: recorded-absolute-path staleness across upgrades (T2), dispatcher reachability (T4),
  hook-scope move (T5), sidecar path form (T10).
