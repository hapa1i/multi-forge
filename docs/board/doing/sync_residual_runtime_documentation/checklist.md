# Sync residual runtime documentation checklist

Current focus: active as Wave 8 Batch 5 order 19 on `agent/wave8-batch-5`, based on pushed `main` at `1e0e664c`. This
card owns the residual design, CLI-reference, and workflow-comment edits; the Batch 5 integrator owns shared board
evidence.

## Phase 1 -- Reverification

- [x] Confirm design section 7 still omits the read-only global runtime-config file from its exhaustive sidecar mount
  paragraph even though `sidecar/container.py` mounts it.
- [x] Confirm the CLI reference still omits `forge auth logout`, `forge auth profiles`, and
  `forge workflow list-models --available`.
- [x] Confirm the consensus implementation evaluates `-p` before the positional subject while its source comment says
  the reverse.

## Phase 2 -- Documentation and comment sync

- [x] Add the runtime-config file to the narrow sidecar mount description without implying all of `~/.forge` is mounted.
- [x] Document only the three missing CLI surfaces and their current behavior/options.
- [x] Correct the consensus precedence comment to `-p > positional > stdin` without changing parsing.

## Phase 3 -- Verification

- [x] Run focused CLI help/behavior tests for the documented surfaces and confirm the source diff is comment-only.
- [x] Run `make pre-commit-md`, design/CLI-reference token checks, board/doc link checks, and `git diff --check`.
- [x] Record final documentation evidence without closing the card before merge.

## Acceptance evidence

| Boundary        | Source of truth                            | Assertion                                                          |
| --------------- | ------------------------------------------ | ------------------------------------------------------------------ |
| Sidecar mounts  | `sidecar/container.py`                     | design lists the existing read-only runtime-config mount precisely |
| CLI inventory   | registered auth/workflow commands and help | all three missing surfaces are documented with current options     |
| Consensus input | `cli/workflow.py` evaluation order         | the comment states `-p > positional > stdin` and code is unchanged |

Implementation evidence: design section 7 now names the conditional read-only `~/.forge/config.yaml` mount while
retaining the narrow global-directory boundary. The CLI reference documents auth profile deletion/listing and the
readiness-only `workflow list-models --available` filter. The consensus source change is comment-only.

Verification evidence: 203 auth, workflow, and workflow-documentation tests passed; `make pre-commit-md`, the configured
Python hooks for the touched comment, and `git diff --check` passed. The documentation scan resolved 1,207 local links
across 447 files. `design.md` is 29,997 Opus tokens and `cli_reference.md` is 9,551.

Integrated evidence: the combined head passed 9,332 unit tests with 124 deselected, 1,059 regression tests, three
targeted integration tests, and every `make pre-commit` hook. The final scan resolved 1,209 local paths across 447
documentation files.
