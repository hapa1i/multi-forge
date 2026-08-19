# Extract session-fork execution and thin the CLI

**Epic**: [`epic_wave7_refactor_and_deletion`](../epic_wave7_refactor_and_deletion/card.md).

**Lane**: `done/` -- shipped in PR #211 as `e4a62d1b` after focused, full, regression, targeted fork/rewind Docker,
pre-commit, and CI verification.

**Findings**: O068's mutation/launch subset and O096's unreachable second `elif proxy_name` branch.

**Depends on**: [`extract_session_fork_preflight`](../../done/extract_session_fork_preflight/card.md).

## Goal

Execute a validated fork plan through command-core mutation/rollback primitives and leave Click responsible only for
input, prompts, presentation, and process handoff.

## Evidence and Authority

Reverified on `1897b547`, the callback still owns child creation, native relocation, rollback, transfer/rewind
artifacts, extension preparation, `ForkLaunchPlan` assembly, and launch rendering. The second proxy-name routing branch
is unreachable because preflight routing is already populated. Authority:
[`docs/design.md` "3.12 Command-core ops"](../../../design.md#312-command-core-ops-shared-implementation) and the
session transaction/launch contracts in
[`docs/design.md` "3.2"](../../../design.md#32-contract-files-authoritative-paths).

Order 31 intentionally retained two temporary seams for this member to remove: mock-manager CLI tests take a weaker
non-concrete planner path, and force-replacement/supervisor error predicates are duplicated between planning and
mutation. The frozen request also carries execution-only `extensions`/`memory_flag` fields, while typed error codes are
reserved for this execution boundary.

## Acceptance Criteria

- One op consumes the typed preflight and owns create/relocate/artifact/rollback/launch-plan transitions with explicit
  compensation for every pre-launch failure point.
- Reuse existing `ForkLaunchPlan`/launch ops; remove the unreachable re-resolution branch after proxy, inherited, and
  direct routing characterization.
- Migrate mock-manager fork tests to concrete stores, remove the weaker planner fallbacks, and consolidate duplicated
  force-replacement and supervisor error decisions behind the execution boundary.
- The Click callback becomes a bounded adapter without changing human/JSON output, confirmation, task delivery, or
  runtime launch argv.
- Run full fork/resume/session regressions and targeted worktree/native-relocate/rewind/Codex integration coverage.

## Exclusions

Do not change branch naming, session identity, transfer/rewind strategy, extension ownership, or post-launch best-effort
confirmation semantics.

Start still renders extension inheritance through the CLI-owned `_auto_install_extensions`, while fork returns typed
extension events from command core. Their shared detection/install mechanics remain explicit follow-up debt; order 33
decomposes the installer transaction itself and does not currently own this caller seam.
