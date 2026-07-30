# `disable` orphans the Codex hook block on a scope mismatch

**Lane**: `done/` -- completed and verified 2026-07-30 on branch `fix/disable-scope-mismatch-orphan`; execution record
in [checklist.md](checklist.md). Small and independently shippable.

**Type**: bug card. Split from [extension_disable_runtime](../../doing/extension_disable_runtime/card.md) (D-mismatch)
because the defect is **not** runtime-specific: it affects bare `forge extension disable` today, with no `--runtime`
flag involved. Fixing it inside a feature card would have hidden a live defect behind a new option.

**Sequencing**: ships **before** [extension_disable_runtime](../../doing/extension_disable_runtime/card.md), so that
card's "preflight refusal leaves tracking untouched" contract is inherited rather than invented. It has no dependency on
[runtime_scoped_extension_modules](../../done/runtime_scoped_extension_modules/card.md) and can ship at any time.

**Origin**: found while verifying a constraint for the runtime-disable card, 2026-07-29. `design_appendix.md` section
C.6 states that "disable refuses a tracked path that no longer matches the scope mapping". The code refuses to *edit
that file* but does not refuse the *operation*, and the difference orphans user state.

---

## Problem

`_remove_codex_registration` compares the tracked Codex config path against the current scope mapping and, on mismatch,
logs a warning and returns without editing:

```text
tracked Codex config <path> does not match the scope mapping <expected>; not modifying it
```

`src/forge/install/installer.py:2477-2483`. Control then returns to `uninstall()`, which removes the tracking row
unconditionally at `src/forge/install/installer.py:2464`.

The result is an orphan: Forge's managed hook block stays in the user's `config.toml` while the tracking row that owned
it is gone. Consequences:

- The user's Codex still fires Forge hooks after they ran `forge extension disable`, which reads as the command not
  working.
- Nothing owns the block any more, so no Forge command will remove it. `forge extension disable` cannot -- there is no
  installation row. `forge clean` cannot -- it governs unmanaged *skill packages*, not Codex config blocks.
  `forge extension status` cannot see it either.
- Manual recovery requires the user to hand-edit `config.toml` between marker comments, and then re-trust Codex.

The mismatch is reachable without tampering: the docstring names a `CODEX_HOME` that changed since install. A user who
moves or re-points `CODEX_HOME` and later disables hits this.

**Severity is "silent orphan", not data loss.** No user content is destroyed; the block is preserved. But the user is
left with active hooks, no owner, and no diagnostic -- and the warning goes to the logger, which is off by default
(`log_level: off`, `design_appendix.md` section A.7). So in the default configuration the failure is completely silent.

## Goal

A scope mismatch must leave the system in a state the user can act on: either the block is removed, or the tracking row
that owns it survives so a later command can remove it. Never both gone.

## Design

**Refuse the operation, preserve tracking.** Promote the mismatch from a silent skip to a preflight refusal:

- Detect the mismatch **before** any removal work begins, not midway through `uninstall()`. It is a pure comparison of
  the tracked path against `get_codex_config_path(scope, project_root)` and needs no filesystem mutation to evaluate.
- On mismatch: make no filesystem change, leave the tracking row intact, print an error naming both paths, and exit
  non-zero. This matches the existing `invalid-target` refusal posture (`design_appendix.md` section C.5) and the
  fail-closed rule for explicit CLI mutations (`coding_standards.md` section 5).
- The error must be actionable. The user's real options are to restore `CODEX_HOME` to the value the row records and
  retry, or to remove the block by hand. Name both, and name the tracked path so hand-editing is possible.

**Why refuse rather than remove the tracked path anyway:** the guard exists to protect against editing an unexpected
file, including a tampered tracking file. Removing the block at a path the current mapping does not sanction would
defeat the guard's purpose. Refusing keeps the guard and fixes only the orphaning.

**`--all` composes without weakening its aggregate contract.** `disable --all --yes` already attempts every scope,
aggregates failures, and exits non-zero if any remain (`design_appendix.md` section C.4). A refused scope becomes one
such failure: other scopes still proceed, and the aggregate exit stays non-zero.

**`setup.sh --uninstall` inherits correct behavior for free.** It deletes `$FORGE_HOME` only after a fully successful
disable and preserves tracking on failure. Today a mismatch reports success while orphaning; after the fix it reports
failure and preserves `installed.json`, which is the honest outcome.

## Constraints (verified against current code)

- `_remove_codex_registration` currently `return`s on mismatch after `logger.warning`, and is called at
  `installer.py:2462` -- two lines before `self._tracking.remove_installation(...)` at `installer.py:2464`. There is no
  conditional between them.
- The comparison is `tracked.resolve() != expected.resolve()` where
  `expected = get_codex_config_path(self._scope, self._project_root)`. Both sides are resolvable without mutation, so a
  preflight check is a pure move, not new logic.
- The same function separately warns about `result.leftover_commands` (Forge hook commands outside the managed block).
  That is a different condition -- a successful removal with residue -- and must keep warning rather than become a
  refusal, or a user with a hand-added registration can never disable.
- `log_level` defaults to `off` (`design_appendix.md` section A.7), so the current warning reaches nobody by default.
  The fix must use the CLI error surface (`forge.cli.output` helpers per `CLAUDE.md`), not only the logger.
- `uninstall()` has no partial-failure reporting today: it either completes or raises. A preflight refusal must
  therefore land before the first mutation, which is also what makes "tracking untouched" trivially true.

## Risks

- **Newly failing disable for users currently in the mismatch state.** Someone whose `CODEX_HOME` moved will now get a
  non-zero exit where they previously got a silent (broken) success. That is the intended correction, but the error text
  has to be good enough that it reads as a diagnosis rather than a regression.
- **`setup.sh --uninstall` will now preserve `$FORGE_HOME` in this case.** Correct, and consistent with its documented
  contract, but it is a visible behavior change for anyone hitting the mismatch.

## Acceptance Criteria

- With a tracked `codex_config_path` that does not match the current scope mapping, `forge extension disable` makes
  **no** filesystem change, leaves the tracking row byte-identical, prints an error naming both the tracked and expected
  paths plus the two recovery options, and exits non-zero.
- The same input with `--yes` behaves identically -- `--yes` bypasses the prompt, never the preflight.
- A matching path is unaffected: normal disable removes the block, clears the row, and exits 0, byte-identical to today.
- `result.leftover_commands` on a *successful* removal still warns and still exits 0; it is not converted into a
  refusal.
- `disable --all` with one mismatched scope disables the other scopes, reports the refused scope, and exits non-zero.
- `scripts/setup.sh --uninstall` against a mismatched install preserves `$FORGE_HOME` and `installed.json` and reports
  the failure.
- Regression test lives at `tests/regression/test_bug_disable_codex_scope_mismatch_orphan.py` per
  `testing_guidelines.md`, asserting the exact failure mode: block still present **and** tracking row still present.
- `design_appendix.md` section C.6's "refuses a tracked path" sentence is corrected to say what is refused -- the
  operation, not just the edit -- and the changelog records the behavior change.

**Verification**: unit plus the named regression test. `testing_guidelines.md` names installer changes as an integration
trigger, so also run `tests/integration/docker/test_installer.py`; a clean-wheel run is not required because no install
path or packaged asset changes.

## Closeout

Completed 2026-07-30. Single-scope disable now validates the tracked Codex config path before rendering its plan or
prompt, and `Installer.uninstall()` repeats the same validation before any removal work. A mismatch raises a typed,
actionable error while leaving managed files, settings, the hook block, and tracking byte-identical. `--all` continues
with healthy scopes and reports the refusal in its aggregate non-zero result.

Verification: focused install/CLI (`808 passed, 1 skipped`), unit (`8491 passed, 1 skipped, 117 deselected`), regression
(`550 passed`), installer Docker integration (`20 passed`), and `make pre-commit`.

Known limitation: hook blocks orphaned by older Forge versions remain untracked and require manual discovery/removal.
