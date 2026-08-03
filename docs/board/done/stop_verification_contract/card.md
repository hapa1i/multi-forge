# Decide the Stop verification contract

**Epic**: [`epic_repo_maintenance_round`](../../doing/epic_repo_maintenance_round/card.md) (DG1; D006 and U002–U003).

**Lane**: `done/` -- approved on 2026-08-04; implementation is parked in
[`align_stop_verification_contract`](../../todo/align_stop_verification_contract/card.md).

## Problem

The shipped architecture promises incompatible Stop-verification behavior:

- `docs/design.md` §3.10 requires synchronous Stop work to finish in under 100 ms.
- `docs/design_workflows.md` §1.3 places blocking `test_suite` verification at Stop and documents `custom_command` as
  “Run any command.”
- `VerificationConfig` has no custom-command field, and the hook supports only `completion_promise` and a fixed
  `["uv", "run", "pytest"]` test command.
- A stored unknown type such as `custom_command` reaches the hook's unknown-type branch and silently allows Stop without
  running verification.
- The workflow example uses `on_incomplete: re_inject`, while the model supports `block | warn | allow`; the
  undocumented fall-through makes `re_inject` behave as `block` by accident.

The contract must be chosen before D006, U002, or U003 can become implementation work. Implementing arbitrary commands,
deleting the documented feature, and defining an explicit latency exception are materially different product choices.

## Decision Required

Specify one coherent contract covering:

- whether the under-100-ms rule is absolute or has named verification exceptions;
- whether `test_suite` remains a synchronous blocking check;
- whether `custom_command` is removed from the design or becomes a supported, configured verification type;
- how unknown verification types are validated and surfaced; and
- the timeout, security, output, and fail-open/fail-closed behavior for every supported type.

Do not infer that documentation automatically authorizes arbitrary shell execution. The decision must account for
command ownership, argument representation, working directory, environment, timeout, and secret/output handling if
custom commands remain in scope.

## Evidence

- Review: [`review_combined.md` DG1, D006, U002–U003](../../review_combined.md#decision-gates).
- Latency contract: `docs/design.md` §3.10.
- Verification types: `docs/design_workflows.md` §1.3.
- Model: `src/forge/session/models.py:215-246`.
- Hook dispatch and unknown-type behavior: `src/forge/cli/hooks/verification.py:82-132`.
- Fixed test command: `src/forge/cli/hooks/verification.py:43-79`.

## Decision

**Status:** approved on 2026-08-04. This card records the contract; implementation remains a separate member.

The ordinary Stop pipeline keeps the under-100-ms budget. `test_suite` is the sole named exception: selecting it is an
explicit request to block Stop on an external process, bounded by `test_timeout_seconds`. The latency budget covers all
Forge-owned work before and after that subprocess, including manifest reads, artifact capture, verification dispatch,
state persistence, and marker enqueueing. Tests must measure that overhead separately from subprocess wall time.

Forge supports exactly two verification types:

| Type                 | Contract                                                                                                                   |
| -------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| `completion_promise` | Inspect only the last assistant message for the configured single-line promise. No external process runs.                  |
| `test_suite`         | Run the fixed argv `uv run pytest`, without a shell, in the resolved session worktree. The default timeout is 300 seconds. |

`custom_command` is removed from the design. Arbitrary command execution is not added: it would require a separate
security and ownership design for argv, environment, working directory, output, and secrets, and no current product
requirement justifies that surface.

`on_incomplete` supports exactly `block`, `warn`, and `allow`. `block` emits the reinjection guidance and exits with the
hook's blocking status; `warn` emits a diagnostic and allows Stop; `allow` skips the check. “Reinject” describes the
effect of `block`, not a fourth stored value.

### Validation and failure posture

- New session writes and mutation commands reject unknown `type` or `on_incomplete` values with an actionable error.
- Legacy manifests containing an unknown value remain recoverable: the Stop hook warns on stderr, allows Stop, and does
  not record a successful verification. It must never silently reinterpret an unknown value.
- A missing or multiline completion promise, a missing `uv` executable, an unavailable worktree, an execution error, or
  a verification-state persistence failure is infrastructure or configuration failure. It warns and allows Stop so a
  malformed guard cannot trap a session indefinitely.
- A configured promise not found in the last assistant message, a non-zero test exit, or a test timeout after a valid
  check starts is an incomplete result and follows `on_incomplete`, including the existing iteration/minute escape
  hatches.
- The subprocess inherits the session environment because tests commonly need it, but uses no shell. Captured output is
  never copied wholesale into the manifest or hook response. Any bounded diagnostic excerpt must pass the repository's
  secret-redaction helper before stderr display or persistence.
- The recorded result distinguishes `passed`, `incomplete`, `misconfigured`, and `infrastructure_error`; a fail-open
  path is not reported as a pass.

## Finding Disposition

| Finding | Severity | Disposition                                 | Downstream work                                                                                                              |
| ------- | -------- | ------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| D006    | HIGH     | Implement                                   | Preserve synchronous `test_suite` as the documented opt-in latency exception; measure Forge overhead and retain the timeout. |
| U002    | MED      | Documentation correction and implementation | Remove `custom_command`; validate supported types and diagnose legacy unknown values.                                        |
| U003    | LOW      | Documentation correction and implementation | Replace `re_inject` with `block`; validate `on_incomplete` and diagnose legacy unknown values.                               |

Proposed implementation member: `align_stop_verification_contract`. It must update both design documents, add
authoring/legacy-value tests, cover working-directory and redaction behavior, and include a regression assertion that
unknown values are visible and fail open rather than passing silently.

## Acceptance Criteria

- Normative docs describe one implementable Stop latency and verification contract.
- The supported verification-type schema, unknown-type behavior, and failure posture are explicit.
- D006 and U002–U003 each receive a disposition: implementation member, documentation correction, or both where
  required.
- Follow-up member cards name observable behavior, security constraints, and unit/integration coverage.
- No code change is bundled into this decision card.

## Closeout

The workflow and Stop-pipeline documentation now describe the shipped two-type schema and fixed-command latency
exception. Validation, legacy diagnostics, resolved cwd, redaction, result classification, and overhead regression work
remain in [`align_stop_verification_contract`](../../todo/align_stop_verification_contract/card.md). Verification:
`make pre-commit-md` and `git diff --check`.
