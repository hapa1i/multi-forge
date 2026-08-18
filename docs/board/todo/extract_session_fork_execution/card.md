# Extract session-fork execution and thin the CLI

**Epic**: [`epic_wave7_refactor_and_deletion`](../../doing/epic_wave7_refactor_and_deletion/card.md).

**Lane**: `todo/` -- accepted Wave 7 structural/deletion work.

**Findings**: O068's mutation/launch subset and O096's unreachable second `elif proxy_name` branch.

**Depends on**: [`extract_session_fork_preflight`](../../doing/extract_session_fork_preflight/card.md).

## Goal

Execute a validated fork plan through command-core mutation/rollback primitives and leave Click responsible only for
input, prompts, presentation, and process handoff.

## Evidence and Authority

On `5777192a`, the callback still owns child creation, native relocation, rollback, transfer/rewind artifacts, extension
preparation, `ForkLaunchPlan` assembly, and launch rendering. The second proxy-name routing branch is unreachable
because preflight routing is already populated. Authority:
[`docs/design.md` "3.12 Command-core ops"](../../../design.md#312-command-core-ops-shared-implementation) and the
session transaction/launch contracts in
[`docs/design.md` "3.2"](../../../design.md#32-contract-files-authoritative-paths).

## Acceptance Criteria

- One op consumes the typed preflight and owns create/relocate/artifact/rollback/launch-plan transitions with explicit
  compensation for every pre-launch failure point.
- Reuse existing `ForkLaunchPlan`/launch ops; remove the unreachable re-resolution branch after proxy, inherited, and
  direct routing characterization.
- The Click callback becomes a bounded adapter without changing human/JSON output, confirmation, task delivery, or
  runtime launch argv.
- Run full fork/resume/session regressions and targeted worktree/native-relocate/rewind/Codex integration coverage.

## Exclusions

Do not change branch naming, session identity, transfer/rewind strategy, extension ownership, or post-launch best-effort
confirmation semantics.
