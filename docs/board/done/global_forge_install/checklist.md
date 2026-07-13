# Checklist: global_forge_install (T1)

Epic: [`epic_global_forge_runtime`](../../done/epic_global_forge_runtime/card.md) -- first member ("Ship first"). Card:
[`card.md`](card.md). Branch: `global-forge-install`.

## Current focus

Make **global tool install** the documented Day-1 path and add **`forge extension doctor`** to report install kind +
PATH reachability. Read-only reporting plus docs; **no** hook-scope, dispatcher, or registry changes (later members).

## Scope guardrails (from card)

- **IN:** Day-1 docs for `uv tool install multi-forge` / `pipx install multi-forge`; keep the contributor `uv sync` path
  documented and distinct; `forge extension doctor` reporting install kind, resolved `forge` path, PATH reachability.
- **OUT:** hook scope changes (T5), dispatcher (T4), registry (T3), removing PyPI, a version manager (D1). Cross-upgrade
  staleness of a *recorded* direct absolute path was assigned to T2 at activation; T2 was later skipped and retired.
- **CLI placement:** `doctor` attaches to the existing **`forge extension`** group (epic CLI-surface decision -- no new
  `install` group; `forge info` stays the top-level dashboard). Support `--json` (list/show convention).

## Phase 0 -- Grounding (verify landing points before coding)

- [x] Confirm the `forge extension` group and how leaves register (`src/forge/cli/extensions.py`); confirm
  `enable/sync/disable/status` are today's leaves. Verified: `extensions()` group, leaves via
  `@extensions.command(...)`; `status_cmd` is the `--json` template (`click.echo(json.dumps(...))`).
- [x] Define the install-kind detection rule with no guessing. Documented in `src/forge/install/doctor.py`: **editable**
  (PEP 610 `direct_url.json` `dir_info.editable`) > **global** (launcher parent in `~/.local/bin` / `UV_TOOL_BIN_DIR` /
  `XDG_BIN_HOME` / `PIPX_BIN_DIR`) > **venv** (`bin`/`Scripts` dir with sibling `pyvenv.cfg`) > **unknown**. Launcher
  path is the on-PATH symlink a user sees (not its target), so `uv tool`'s `~/.local/bin` link classifies as global.
- [x] Confirm `uv tool` (`~/.local/bin`) vs `pipx` layouts so `doctor` resolves both. `_global_bin_dirs` honors
  `~/.local/bin` + `UV_TOOL_BIN_DIR` + `XDG_BIN_HOME` + `PIPX_BIN_DIR`; `test_global_tool_layouts_resolve_global`
  parametrizes all four.
- Note: keep `doctor` distinct from `forge info` -- it answers "how was Forge installed and is it globally reachable?",
  not the general dashboard.

## Phase 1 -- `forge extension doctor`

- [x] Add the `doctor` leaf under `forge extension` (`extensions.py` `doctor_cmd`): reports install kind, resolved
  `forge` path, on-PATH-in-plain-shell boolean, and advice. Detection logic lives in `src/forge/install/doctor.py`
  (`diagnose_install`, injectable seams), keeping the CLI leaf thin.
- [x] **Minimal-PATH probe (feeds epic D2):** `on_path_minimal` probes `PATH=/usr/bin:/bin:/usr/sbin:/sbin`. Verified on
  the real editable dev install: `on_path=true`, `on_path_minimal=false` -- the mechanical GUI/launchd gap. Advice is
  keyed on `on_path`/kind (user-actionable), **not** `on_path_minimal` (a bare-command/statusLine signal, not host
  dispatcher health), so a correct global install is not nagged.
- [x] `--json` emits the stable shape (`install_kind`, `forge_path`, `on_path`, `on_path_minimal`, `advice`) via
  `click.echo(json.dumps(...))`; human advice routes through `print_tip` (no hand-rolled `Tip:` / `[red]Error:[/red]`).
- [x] Unit tests `tests/src/install/test_doctor.py` (new) -- 14 tests, all install kinds + both probe outcomes +
  off-PATH-global advice + CLI JSON shape/human smoke.
- **Assertion (met):** global install -> `install_kind="global"` + launcher path + `on_path=true`
  (`test_global_install_on_local_bin`); editable/venv-not-on-PATH -> venv path + `on_path=false` + advice
  (`test_venv_only_not_on_path_advises_global`). `uv run pytest tests/src/install/test_doctor.py -q` -> 14 passed.

## Phase 2 -- Day-1 docs

- [x] `README.md`: Quick Start leads with `uv tool install multi-forge` / `pipx install multi-forge` +
  `forge extension doctor`; dev sub-note switched `pip install -e .` -> `uv sync` (matches CONTRIBUTING/CLAUDE);
  uninstall -> `uv tool uninstall` / `pipx uninstall`; added an "Installer: uv or pipx" line to Requirements.
- [x] `docs/end-user/README.md`: added an **"Install Forge (once)"** prerequisite ahead of the lettered A--F session
  steps (the workflow previously assumed `forge` was already on PATH). Shows both installers + `forge extension doctor`;
  points contributors to CONTRIBUTING.md `uv sync`. No renumbering churn (install is a one-time prereq, not a step).
- **Assertion (met):** `grep` confirms both docs show `uv tool install` and `pipx install multi-forge`; contributor
  `uv sync` present and labeled distinctly (README dev note + end-user "Contributors ... use an editable install").

## Phase 3 -- Design-doc sync (required: CLI + installer + Day-1 behavior change)

- [x] `docs/cli_reference.md`: added `forge extension doctor` to the Installation table (`--json`).
- [x] `docs/design.md` §5.1: new opening paragraph frames the two install layers -- the `forge` tool (global-tool
  install, prerequisite) vs extensions into `.claude/`; names `forge extension doctor`. `docs/design_appendix.md` §C:
  lead-in documents the tool distribution, the four install kinds + detection rules, the minimal-PATH probe semantics,
  and the `--json` shape (anchor-safe -- no §C.1--C.6 renumbering).
- [x] `docs/end-user/README.md` install guide reflects the Day-1 global install (done in Phase 2).
- **Assertion (met):** cli_reference + design.md §5.1 + appendix §C name `forge extension doctor` and the global-install
  Day-1 path; board_contract "Design Doc Sync" satisfied (CLI + installer + Day-1 behavior all covered).

## Phase 4 -- Verify + closeout

- [x] `uv run pytest tests/src/install/test_doctor.py -q` -> 14 passed. Touched suites green:
  `tests/src/install/ tests/src/cli/ -m "not integration"` -> 2586 passed, 10 deselected.
- [x] `make pre-commit` clean (isort/ruff/black/mypy/pyright/mdformat all Passed; mypy + pyright cover the new
  `doctor.py` + `extensions.py`).
- [x] Integration consideration -- **explicit skip rationale.** `doctor` is a read-only diagnostic appended as a new
  `forge extension` leaf; it does **not** touch the installer write path (`enable`/`disable`/`sync` -> `.claude/`) that
  CLAUDE.md's "run installer integration" mandate targets, and the existing `test_installer.py` integration exercises
  that write path, not `doctor`. Environment-sensitive detection is covered two ways: unit tests across all four kinds +
  both probe outcomes + uv-tool/pipx/XDG/UV_TOOL_BIN_DIR layouts + off-PATH-global advice (14 tests), **and** a
  real-environment smoke -- `forge extension doctor` run against the actual editable dev install correctly reported
  `editable`, the real launcher path, `on_path=true`, `on_path_minimal=false` (exercises the real `importlib.metadata`
  read, `shutil.which`, and PATH). Residual gap: the `global` kind against a real wheel/`uv tool` install is
  unit-covered (faithful seams) but not container-verified; low-risk (it is the "no editable marker" default branch). No
  Docker run warranted for this change.
- [x] `docs/board/change_log.md` entry added (Goal / Key changes / Verification).
- [x] impl_notes candidate recorded (see below); promoted to `impl_notes.md` at closeout (human-reviewed).
- [x] Move `doing/global_forge_install -> done/` (post-merge #89); repointed the 5 cross-lane links (T1 \<-> epic); epic
  checklist updated (T1 shipped, no active member, D2 now actionable). Closeout entry added to `change_log.md`.

### impl_notes candidate (promoted to `impl_notes.md` at closeout)

- **Install-kind detection rule** (`src/forge/install/doctor.py`): editable (PEP 610 `direct_url.json`
  `dir_info.editable`) is checked *first* -- a dev checkout's launcher lives in a venv `bin`, but "editable" is the more
  actionable label than "venv". Global is keyed on the launcher's *parent dir* (`~/.local/bin` / `UV_TOOL_BIN_DIR` /
  `XDG_BIN_HOME` / `PIPX_BIN_DIR`), using the on-PATH symlink a user sees -- **not** its realpath target (realpath would
  resolve a `uv tool` launcher into its tool-venv and mis-classify it). The minimal-PATH probe reads
  `on_path_minimal=false` for a *healthy* global install (`~/.local/bin` is not on launchd's PATH); it is a reported
  fact feeding epic D2, never a fault, so `advice` is keyed on `on_path`/kind, not on `on_path_minimal`. Advice is
  state-aware: a global install that is merely off PATH is told to wire PATH (`uv tool update-shell` /
  `pipx ensurepath`) rather than reinstall -- distinguishing "not installed" from "installed, not on PATH".

## Acceptance tests

| Test                            | Fixture                                                      | Assertion                                                                                                                            | Test File                          |
| ------------------------------- | ------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------ | ---------------------------------- |
| Docs show global install        | rendered README + end-user setup                             | `uv tool install` and `pipx install multi-forge` both present; contributor `uv sync` kept distinct                                   | doc check (Phase 2)                |
| Doctor reports global kind      | global-tool install, launcher on PATH                        | names resolved launcher path + `on_path=true`; `--json install_kind="global"`                                                        | `tests/src/install/test_doctor.py` |
| Doctor flags venv-only          | editable/venv install, not on PATH                           | reports the venv `forge` path + `on_path=false` + advises global install                                                             | `tests/src/install/test_doctor.py` |
| Doctor: global off PATH         | global install, `~/.local/bin` not on PATH                   | `install_kind="global"`, `on_path=false`; advice names the path + PATH setup (not reinstall); `advice_commands`=PATH-setup           | `tests/src/install/test_doctor.py` |
| Doctor resolves uv-tool vs pipx | `forge` under uv-tool / pipx / `UV_TOOL_BIN_DIR` dir         | all resolve to `install_kind="global"` with the correct path                                                                         | `tests/src/install/test_doctor.py` |
| Doctor minimal-PATH probe (D2)  | `forge` on user PATH, not in `/usr/bin:/bin:/usr/sbin:/sbin` | `--json` reports `on_path=true`, `on_path_minimal=false` -- the GUI/launchd gap that decides D2                                      | `tests/src/install/test_doctor.py` |
| Doctor JSON shape stable        | any install                                                  | `--json` keys = {install_kind, forge_path, on_path, on_path_minimal, advice} (advice nullable, always present); parse-safe on stdout | `tests/src/install/test_doctor.py` |

## Blockers / deferred

- None blocking (card: "Open questions: None blocking").
- Deferred at activation to sibling members: recorded direct-absolute-path planning (retired T2), dispatcher
  reachability (T4), hook-scope move (T5), sidecar path form (T10).

## Post-review hardening

Fixes applied from review (verified by `test_doctor.py`):

- **Off-PATH global advice** (Finding 1, fixed): `_advice` gained a `global && not on_path` branch -- names the launcher
  path and points to PATH setup, not reinstall. `advice_commands` selects `PATH_SETUP_COMMANDS` for this state,
  `GLOBAL_INSTALL_COMMANDS` otherwise.
- **`UV_TOOL_BIN_DIR`** (Finding 3, fixed): added to `_global_bin_dirs` (uv honors it before `XDG_BIN_HOME`).
- **Hook-reachability overclaim** (2nd review, fixed): five strings said a global install makes `forge` resolve "from
  hooks" unqualified, contradicting the PR's own model (a healthy `~/.local/bin` global install reads
  `on_path_minimal=false`). Caveated to shell-inherited/terminal-launched hooks in `doctor.py` (3 advice strings),
  `design.md §5.1`, and `end-user/README.md`; the GUI/launchd minimal-PATH gap now points at `on_path_minimal` (docs)
  and the then-open T2/T4 hook-reachability decision (epic D2 row). The epic closeout later corrected those surfaces for
  the shipped absolute host dispatcher and bare project statusLine split.
- **Test name** (Nit 1, fixed): `test_install_doctor.py -> test_doctor.py` (1:1 mirror); refs repointed in card,
  checklist, and the T2 card (`forge_hook_absolute_command`).
- **JSON key wording** (Nit 2, fixed): `advice` is always present (nullable), not optional.

Deferred by design (recorded, not fixed):

- **kind-vs-path mixed-install seam** (Finding 2 -> **T8** `forge_dev_runtime_override`): `install_kind` reads the
  running interpreter's metadata while `forge_path`/`on_path` read PATH resolution, so a directly-invoked dev
  `.venv/bin/forge` (venv off PATH) beside a global install reports `kind=editable` + a global `forge_path`. Documented
  in the `diagnose_install` docstring; flagged in the T8 card. Editable-wins precedence is correct for common cases.
- **Exit code always 0** (Nit 3): doctor is a diagnostic -- health lives in the payload, not the exit code (noted in
  `doctor_cmd`). A non-zero-on-unhealthy mode remains a separate future operator-interface question.
