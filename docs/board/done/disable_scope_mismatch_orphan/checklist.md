# Checklist: `disable` orphans the Codex hook block on a scope mismatch

**Card**: [card.md](card.md) **Branch**: `fix/disable-scope-mismatch-orphan` **Base**: `main` at `6d1b137f`

**Current focus**: Complete -- implementation, verification, documentation, and board closeout are finished.

---

## Planning findings (verified against source on this branch)

The defect lives in `_remove_codex_registration` (`src/forge/install/installer.py:2466-2490`):

```python
if not existing.codex_config_path:      # :2473  null is NOT a mismatch -- preserve this
    return
tracked = Path(existing.codex_config_path)
expected = get_codex_config_path(self._scope, self._project_root)
if tracked.resolve() != expected.resolve():
    logger.warning("tracked Codex config %s does not match ...")   # :2478  silent (log_level defaults to off)
    return                                                          # :2483  <-- the orphan
result = remove_codex_block(tracked, get_builtin_codex_entries())
```

`uninstall()` then calls `self._tracking.remove_installation(...)` unconditionally at `:2464`, so the managed block
survives with no owner.

Three of the card's acceptance criteria need **no production change beyond the validator itself** -- only tests.
Verified call sites:

| Criterion                                      | Why it already holds                                                                                            |
| ---------------------------------------------- | --------------------------------------------------------------------------------------------------------------- |
| Single-scope CLI prints an error and exits 1   | `disable_cmd` catches `ForgeInstallError` -> `print_error` -> `sys.exit(1)` (`cli/extensions.py:1314`)          |
| `--all` reports the scope and exits non-zero   | `_uninstall_all_installations` collects `errors.append(...)` and raises `Exit(1)` (`cli/extensions.py:656-729`) |
| `setup.sh --uninstall` preserves `$FORGE_HOME` | `scripts/setup.sh:550-551` runs `extension disable --all --yes` and `fatal`s on non-zero                        |

**Net production surface**: one exception class, one validator, two call sites. No change to CLI error rendering,
`--all` aggregation, or `setup.sh`.

### Decision: preflight before the prompt, backstop inside `uninstall()`

`disable_cmd` renders the removal plan -- including `remove managed block in <path>` -- and calls `click.confirm` at
`cli/extensions.py:1287` **before** `installer.uninstall()` at `:1292`. A check placed only inside `uninstall()` would
show a plan promising removal, take the confirmation, then fail. Nothing would be mutated, so it is safe but confusing.

Chosen shape: one validator, two call sites -- the CLI calls it before rendering the plan; `uninstall()` calls it at the
top as a backstop, so a non-CLI caller cannot orphan the block.

Precedent is inside the function being changed: `uninstall()` already validates **every** tracked file boundary
(`installer.py:2401-2405`) into a `removals` list before performing any deletion. It is already a
validate-all-then-mutate function; this check joins that phase.

### Explicit non-goals

- **`leftover_commands` silence.** `installer.py:2485-2490` warns through `logger` too, so it is equally invisible with
  `log_level: off`. Same shape, different condition (successful removal with user-owned residue). Not in scope -- this
  card must leave that branch byte-identical, not fix it.
- **Repairing an already-orphaned block.** Users who ran `disable` before this fix keep an orphaned block and no
  tracking row. Detection/repair of that state is not carded; record it in the change log as a known limitation.

---

## Phase 0 -- Reproduce (failing test first)

Per `testing_guidelines.md` "Regression Test Mandate": failing test -> fix -> verify pass.

- [x] Write `tests/regression/test_bug_disable_codex_scope_mismatch_orphan.py` with
  `pytestmark = pytest.mark.regression` and a docstring naming the root cause and the pre-fix
  `Installer._remove_codex_registration` site. **Assertion**: the test builds an installation whose tracked
  `codex_config_path` differs from `get_codex_config_path(scope, project_root)`, runs `uninstall()`, and **fails on
  current `main`** by observing both halves of the orphan -- managed block still on disk **and** tracking row gone.
- [x] Confirm the test relies on the autouse `isolate_codex_home` fixture (`tests/conftest.py:124`). **Assertion**: the
  config path under test resolves inside `tmp_path`; the real `~/.codex/config.toml` is never written. `impl_notes.md`
  records that a leak of exactly this kind shipped once before.
- [x] Record the pre-fix failure output in the Verification log below. **Assertion**: the recorded output shows tracking
  removed while the block survives -- not a generic assertion error that would also fire for an unrelated reason.

**Fixture model**: `tests/regression/test_bug_codex_tracking_lost_on_unavailable.py` already builds a codex config plus
tracking row and asserts on `codex_config_path` (helpers `_run` at `:53`, `_codex_config` at `:61`). Reuse that shape
instead of inventing a fixture.

## Phase 1 -- Exception and validator

- [x] Add `CodexConfigScopeMismatchError(ForgeInstallError)` to `src/forge/install/exceptions.py`. **Assertion**:
  carries tracked and expected paths as attributes; `str()` names both plus the two recovery paths (restore the original
  `CODEX_HOME` and retry, or remove the block by hand). Naming matches the existing family (`NotInstalledError`,
  `PathBoundaryViolationError`).
- [x] Extract the `:2477` comparison into a validator that raises instead of warning. **Assertion**: comparison logic is
  unchanged (`tracked.resolve() != expected.resolve()` against
  `get_codex_config_path(self._scope, self._project_root)`); only the outcome changes. `codex_config_path` falsy ->
  returns cleanly, never raises, matching the `:2473` guard.
- [x] Keep a `get_codex_config_path` failure distinguishable from a mismatch. **Assertion**: that function raises when a
  project/local scope has no `project_root` (`tests/src/install/test_codex_hooks.py:133`); the validator must let that
  propagate as-is rather than reporting it as a scope mismatch.
- [x] Confirm the error text passes the CLI style guards. **Assertion**: no hand-rolled `Tip:` or `[red]Error:[/red]`
  (they belong only in `output.py`); recovery phrasing follows `cli_style_guidelines.md` -- `Run '<full command>'`,
  single quotes, never backticks. `test_cli_rich_tips_go_through_output_helpers` and
  `test_cli_rich_errors_go_through_print_error` stay green.

## Phase 2 -- Wire both call sites

- [x] Call the validator in `uninstall()` between the `existing is None` check (`installer.py:2396-2397`) and the
  `base_dir` / `removals` computation (`:2399-2400`). **Assertion**: on mismatch it raises before the first
  managed-state mutation (`target.unlink()` at `:2420`) and before the first tracked payload / settings read
  (`find_backup_files` at `:2408`). Not "before the first filesystem read" -- tracking is already read at `:2395`, and
  `Path.resolve()` in the validator itself issues `readlink` syscalls. Verified by comparing tracked-file bytes, the
  settings file, backup files, and the tracking row before and after the raise.
- [x] Call the validator in `disable_cmd` before the removal plan is rendered (`cli/extensions.py:1236`). **Assertion**:
  on mismatch the command prints the error and exits 1 with no removal table in the output and without reaching
  `click.confirm` at `:1287`.
- [x] Leave the `leftover_commands` branch (`installer.py:2485-2490`) untouched. **Assertion**: `git diff` shows no
  change to those lines; a successful removal with user-owned residue still warns through `logger` and still exits 0.

## Phase 3 -- Composition coverage

- [x] `--all` with one mismatched scope. **Assertion**: other scopes are disabled, the refused scope appears in the
  error summary, exit 1 -- with no change to `_uninstall_all_installations`. Mirror the existing
  `test_disable_all_attempts_every_installation_and_exits_nonzero_on_failure`
  (`tests/src/cli/test_extension_enable.py:933`).
- [x] `--yes` does not bypass the preflight. **Assertion**: `--yes` suppresses only `click.confirm`; the mismatch still
  raises and exits 1.
- [x] Matching-path non-regression. **Assertion**: `test_disable_previews_and_removes_block`
  (`tests/src/cli/test_extension_enable.py:2072`) and the `TestRemoveBlock` cases in
  `tests/src/install/test_codex_hooks.py:293+` pass unchanged -- block removal, whitespace-only config deletion, and
  tracking-row removal all byte-identical to pre-fix behavior.
- [x] `setup.sh --uninstall` gating. **Assertion**: the exit contract `scripts/setup.sh:550-551` depends on holds;
  `$FORGE_HOME` and `installed.json` survive a refused disable.

## Phase 4 -- Docs

- [x] Correct `docs/design_appendix.md:1262`. **Assertion**: the clause currently reads "disable refuses a tracked path
  that no longer matches the scope mapping" -- refusing the *path*. Restate it as refusing the *operation* and
  preserving tracking. This compression is what made the defect read as intended behavior; the docstring at
  `installer.py:2469-2471` ("Forge refuses to edit the unexpected file") needs the same correction.
- [x] Add the `docs/board/change_log.md` entry (newest first: Goal / Key changes / Verification). **Assertion**: bug-fix
  sized per `board_contract.md` (5-10 lines); states the behavior change -- a previously silent success now exits
  non-zero -- and the known limitation for already-orphaned blocks.
- [x] Check `docs/end-user/hook.md` for disable behavior this changes. **Assertion**: lines 114-116 now explain the
  refusal, preservation, and both recovery paths next to the user-scope disable command.

## Acceptance tests

| Test                                     | Fixture                                                     | Assertion                                                            | Test File                                                           |
| ---------------------------------------- | ----------------------------------------------------------- | -------------------------------------------------------------------- | ------------------------------------------------------------------- |
| Mismatch preserves tracking and block    | tracked `codex_config_path` != scope mapping, block on disk | block present AND tracking row present; exit non-zero                | `tests/regression/test_bug_disable_codex_scope_mismatch_orphan.py`  |
| Mismatch mutates nothing                 | same, plus tracked files and settings entries present       | every tracked file and settings entry byte-identical after the raise | `tests/regression/test_bug_disable_codex_scope_mismatch_orphan.py`  |
| Mismatch never renders a plan            | same, invoked through `disable_cmd`                         | no removal table in output; `click.confirm` not reached; exit 1      | `tests/src/cli/test_extension_enable.py` (codex-hooks class, :2001) |
| `--yes` does not bypass preflight        | same, `--yes` passed                                        | exit 1; tracking row present                                         | `tests/src/cli/test_extension_enable.py`                            |
| `--all` aggregates the refusal           | two scopes, one mismatched                                  | good scope disabled, bad scope named in summary, exit 1              | `tests/src/cli/test_extension_enable.py`                            |
| Null `codex_config_path` is not mismatch | installation with `codex_config_path` falsy                 | disable completes, exit 0, no raise                                  | `tests/src/install/test_installer.py`                               |
| Matching path still removes              | tracked path == scope mapping                               | block removed, row removed, exit 0                                   | `tests/src/install/test_codex_hooks.py`                             |
| Leftover commands still only warn        | successful removal, Forge command outside the managed block | `logger` warning, block removed, exit 0                              | `tests/src/install/test_codex_hooks.py`                             |

New CLI cases go in the existing class at `tests/src/cli/test_extension_enable.py:2001` ("codex-hooks module surfaces on
enable/status/disable"), which already owns `test_disable_previews_and_removes_block`. No new CLI test file --
`tests/src/cli/test_extension_disable.py` does not exist and a thin new file would split disable coverage.

## Verification log

(record the pre-fix failure output, then each command and its result)

- Pre-fix regression: **failed as intended** at the orphan assertion with
  `block_present=True, tracking_present=False, error=None`; the captured warning showed the tracked config under the
  isolated `tmp_path/codex_home` and the new mapping under `tmp_path/moved_codex_home`.
- [x] `uv run pytest tests/regression/test_bug_disable_codex_scope_mismatch_orphan.py -v` -- 1 passed
- [x] `uv run pytest tests/src/install tests/src/cli/test_extension_enable.py -q` -- 808 passed, 1 skipped
- [x] `make test-unit` -- 8491 passed, 1 skipped, 117 deselected
- [x] `make test-regression` -- 550 passed
- [x] `./scripts/test-integration.sh tests/integration/docker/test_installer.py -v` -- 20 passed; required:
  `testing_guidelines.md` names installer changes as an integration trigger, and unit tests never exercise the real
  wheel-install path
- [x] `make pre-commit` -- clean after `mdformat` normalized the edited Markdown

Clean-wheel verification is **not** required: no install path, packaged asset, or module set changes. Deliberate scope
note, not an omission.

## Closeout

- [x] Every box above ticked with verification recorded.
- [x] `docs/board/change_log.md` entry added.
- [x] `docs/design_appendix.md:1262` and the `installer.py` docstring reflect shipped behavior.
- [x] Card moved `doing/` -> `done/`, and the five inbound links repointed from `../../doing/...` to `../../done/...`:
  [extension_disable_runtime](../../done/extension_disable_runtime/card.md) (3) and
  [runtime_scoped_extension_modules](../../done/runtime_scoped_extension_modules/card.md) (2). These were repointed once
  already when this card moved `proposed/` -> `doing/`; the move to `done/` breaks them again.
- [x] Consider promoting to `impl_notes.md` after human review: refusing to *edit a file* is not refusing the
  *operation*. A doc sentence and a docstring that both compressed that distinction are what let this defect read as
  intended behavior for as long as it did. Deliberately deferred until human review; no durable note was promoted during
  implementation closeout.
