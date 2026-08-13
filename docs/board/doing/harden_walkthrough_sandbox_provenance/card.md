# Harden walkthrough sandbox provenance

**Epic**: [`epic_wave6_correctness_maintenance`](../../doing/epic_wave6_correctness_maintenance/card.md).

**Lane**: `doing/` -- implementation and verification are complete on `agent/harden-walkthrough-sandbox-provenance` from
merged production code at `88ac88c5` after the PR #176 bookkeeping closeout at `180c2bba`; independent review and merge
remain before Wave 6 closeout.

**Finding**: O036.

## Goal

Resolve the walkthrough target canonically and prove its marker before sourcing target-controlled shell code.

## Evidence and Authority

Rechecked on merged production code at `88ac88c5`: `run-in-repo.sh` still uses `abspath` for its denylist and sources
`.forge/walkthrough/env.sh` before checking the provenance marker and required structure. The bundled walkthrough skill
declares the wrapper as the mandatory safety boundary.

The retained regression artifact produces `3 failed, 1 passed` on that unchanged code: missing-marker and
incomplete-structure targets execute their env side effect, a symlink alias reaches command execution through the
denylist, and the setup-generated walkthrough repo remains a passing compatibility control.

## Acceptance Criteria

- Canonical real paths (including symlinks) are checked against the denylist.
- The marker and required structure are validated before `env.sh` can execute.
- A valid generated walkthrough repo still exports its isolated homes and runs commands unchanged.
- Retain shell-level malicious-env and symlink regressions; verify the built wheel contains the corrected script.

## Compatibility and Exclusions

Do not change the default test-repo location, the six safety checks, or setup/reset behavior.

## Implementation Outcome

- `FORGE_TEST_REPO` is now resolved with `realpath` semantics before denylist comparison, so a symlink alias cannot
  conceal a protected target.
- The env-file, marker, and required-structure checks now run before `env.sh` is sourced. The existing home-isolation
  checks still validate the values exported by a proven walkthrough repo.
- The generated-repo command path, default target, and setup/reset behavior remain unchanged.

## Verification

- Retained regressions: `4 passed` after producing `3 failed, 1 passed` on `88ac88c5`.
- Focused walkthrough slice: `98 passed`; marked regression gate: `898 passed`; unit gate:
  `9004 passed, 1 skipped, 122 deselected`.
- The sdist and wheel build passed; the wheel script is byte-identical to source and ran a generated repo from a clean
  temporary install. The targeted Docker wheel-lifecycle integration passed (`1 passed, 22 deselected`).
- Full pre-commit and the 298-file/723-link board audit pass with no missing targets. The bundled skill safety model is
  synchronized; no normative design or end-user update is required because the correction restores the documented
  wrapper boundary without changing CLI or setup behavior.
