# Preserve session launch preconditions checklist

Current focus: implementation and behavioral verification are complete; finish branch gates and independent review while
O036 remains parked.

## Phase 1: Activation and evidence

- [x] Close PR #175 bookkeeping on local `main` at `eaa4a7f3`.
- [x] Create `agent/preserve-session-launch-preconditions`, move only this member to `doing/`, and repoint inbound board
  links.
- [x] Recheck every finding against merged production code at `967d9cae`; narrow O011 to host-mode typed failures and
  O017 to fresh rewind resume because their sidecar/worktree-fork siblings already enforce cleanup.
- [x] Retain fail-first regressions and compatibility controls for all six findings before production changes.
- [x] Run the retained regression slice on unchanged production code (`15 failed, 7 passed`).

## Phase 2: Launch-boundary corrections

- [x] Make incognito failure cleanup independent of host/sidecar launch mode.
- [x] Reject unready rewind input before invocation and remove any derived child created for the failed attempt.
- [x] Latch JSON-output incompatibility only when the runtime rejection explicitly names `--output-format`.
- [x] Validate required fork UUID and derived resume names before durable or generated-context mutation.
- [x] Keep launch-confirmation persistence best-effort across ordinary store and path failures.

## Acceptance tests

| Finding | Fixture                                                  | Assertion                                                  | Test file                                                           |
| ------- | -------------------------------------------------------- | ---------------------------------------------------------- | ------------------------------------------------------------------- |
| O011    | typed host/sidecar incognito launch failures             | both clean up; non-incognito stays intact                  | `tests/regression/test_bug_o011_incognito_fork_cleanup.py`          |
| O017    | fresh rewind selects an unready fallback transcript      | child is removed and Claude is not invoked                 | `tests/regression/test_bug_o017_rewind_resume_unready_fallback.py`  |
| O021    | generic versus `--output-format` rejection stderr        | only the explicit flag rejection retries/latches           | `tests/regression/test_bug_o021_json_capability_rejection_scope.py` |
| O023    | native, transfer, and deferred forks without parent UUID | native fails before mutation; UUID-free modes remain legal | `tests/regression/test_bug_o023_fork_uuid_preflight.py`             |
| O029    | launch-confirmation store/path failures                  | failure is logged and completed launch result is preserved | `tests/regression/test_bug_o029_launch_confirmation_best_effort.py` |
| O030    | overlong derived/explicit resume names                   | validation precedes context and durable mutation           | `tests/regression/test_bug_o030_resume_name_preflight.py`           |

## Verification and closeout

- [x] Run focused unit and retained regression slices (`22` retained and `168` focused tests passed).
- [x] Run the targeted session/Codex-runtime integration tests required by repository policy (`48 passed`).
- [x] Run the full regression (`894 passed`) and unit (`9004 passed, 1 skipped, 122 deselected`) gates.
- [x] Run full pre-commit and final board integrity checks (297 Markdown files, 723 local links, no missing targets,
  Wave 6 at 11 done / 1 doing / 1 todo members, no stale lane references, and a clean diff check).
- [x] Review normative design and end-user docs; no synchronization is required because this member restores existing
  launch-ordering and best-effort contracts without changing architecture, ownership, or CLI surface.
- [ ] Record verification in `docs/board/change_log.md`, update epic counts and links, and move this card to `done/`.
- [ ] Review and merge independently before activating O036.

O036 remains parked until this member merges and its bookkeeping closes on `main`.
