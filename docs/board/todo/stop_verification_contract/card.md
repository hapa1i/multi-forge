# Decide the Stop verification contract

**Epic**: [`epic_repo_maintenance_round`](../epic_repo_maintenance_round/card.md) (DG1; D006 and U002).

**Lane**: `todo/` -- accepted decision work, parked until an execution branch becomes active.

## Problem

The shipped architecture promises incompatible Stop-verification behavior:

- `docs/design.md` §3.10 requires synchronous Stop work to finish in under 100 ms.
- `docs/design_workflows.md` §1.3 places blocking `test_suite` verification at Stop and documents `custom_command` as
  “Run any command.”
- `VerificationConfig` has no custom-command field, and the hook supports only `completion_promise` and a fixed
  `["uv", "run", "pytest"]` test command.
- A stored unknown type such as `custom_command` reaches the hook's unknown-type branch and silently allows Stop without
  running verification.

The contract must be chosen before D006 or U002 can become implementation work. Implementing arbitrary commands,
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

- Review: [`review_combined.md` DG1, D006, U002](../../review_combined.md#decision-gates).
- Latency contract: `docs/design.md` §3.10.
- Verification types: `docs/design_workflows.md` §1.3.
- Model: `src/forge/session/models.py:215-246`.
- Hook dispatch and unknown-type behavior: `src/forge/cli/hooks/verification.py:82-132`.
- Fixed test command: `src/forge/cli/hooks/verification.py:43-79`.

## Acceptance Criteria

- Normative docs describe one implementable Stop latency and verification contract.
- The supported verification-type schema, unknown-type behavior, and failure posture are explicit.
- D006 and U002 receive a disposition: implementation member, documentation correction, or a split where both are
  required.
- Follow-up member cards name observable behavior, security constraints, and unit/integration coverage.
- No code change is bundled into this decision card.
