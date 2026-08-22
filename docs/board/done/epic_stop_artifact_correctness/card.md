# Epic: Stop and artifact correctness

**Parent epic**: [`epic_repo_maintenance_round`](../epic_repo_maintenance_round/card.md).

**Lane**: `done/` -- all three Wave 2 members shipped in PRs #130–#132 and the coordinated outcome closed on 2026-08-06.

## Goal

Make Stop verification, transcript artifact reconciliation, and sidecar shadow-drain scheduling honor their shipped
contracts without combining three independently reviewable behavior changes.

## Design Authority

- [`stop_verification_contract`](../../done/stop_verification_contract/card.md) (DG1): exactly
  `completion_promise | test_suite`, with fixed `uv run pytest` as the sole opt-in blocking latency exception and
  visible fail-open handling for legacy unknown values.
- [`docs/design_sessions.md` §3.8](../../../design_sessions.md#38-session-artifacts-plans-transcripts): transcript
  artifacts use a stable `session_id`/`copied_path` schema and UUID-named destinations.
- [`docs/design_sessions.md` §3.10](../../../design_sessions.md#310-hook-handlers): repeated Stop invocations are safe;
  Forge-owned synchronous work remains under 100 ms outside explicit test-suite wall time.
- [`docs/design_runtime.md` §7](../../../design_runtime.md#7-isolation-and-proxy-modes) and
  [`docs/design_workflows.md` §1.2](../../../design_workflows.md#12-semantic-policy-the-supervisor): a sidecar probes
  project artifacts through its mounted path but persists host-resolvable shadow work markers for later host draining.
- [`review_combined.md`](../../reviews/whole_repo_design_findings.md#design-conformance-findings): D006–D007, D024,
  D039, and U002–U003.

## Reproduction Record

All Wave 2 findings were initially rechecked against merged `main` at `86fa53da`. Four isolated executable
characterizations used the real verifier, artifact helper/read seam, sidecar path resolver, and shadow candidate probe.
They were not retained because they assert the broken behavior; each member requires a regression that asserts the
target contract.

| Findings | Fixture                                                                                 | Observed result                                                                                                      |
| -------- | --------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------- |
| D006     | Real `_check_test_suite`; patched subprocess waits 150 ms and succeeds                  | Caller returned after 155 ms with fixed `uv run pytest` argv and the default 300-second timeout.                     |
| D007     | Append the same `session_id`/`copied_path` twice; append into a mapping-valued field    | Two equal records remained; the pre-existing mapping was replaced by a one-element list.                             |
| D024     | Canonical copied transcript followed by a PreCompact-style `snapshot_path` entry        | `_latest_transcript_artifact_path` returned `None` because the incompatible tail shadowed the valid copied artifact. |
| D039     | Sidecar env with distinct mounted and host roots; candidate exists only under the mount | The current host-root probe returned false while the container-visible project-root probe returned true.             |

## Members and Sequence

| Order | Findings        | Member                                                                                              | Review boundary                                      |
| ----- | --------------- | --------------------------------------------------------------------------------------------------- | ---------------------------------------------------- |
| 1     | D006, U002–U003 | [`align_stop_verification_contract`](../../done/align_stop_verification_contract/card.md)           | Verification schema, result states, and latency      |
| 2     | D007, D024      | [`preserve_transcript_artifact_identity`](../../done/preserve_transcript_artifact_identity/card.md) | Artifact identity, schema, and legacy reads          |
| 3     | D039            | [`repair_sidecar_shadow_drain_routing`](../repair_sidecar_shadow_drain_routing/card.md)             | Container-local detection and host-marker path split |

The verification member goes first because DG1 already defines its complete contract and it owns the Stop decision
boundary. Artifact reconciliation follows as a separate durable-state change. Sidecar shadow routing remains separate
because it requires container-path integration evidence and does not depend on either preceding implementation.

D006/U002/U003 were rechecked again on their execution branch from merged `main` at `5813994c`. The three retained
regression modules failed in six cases before implementation, reproducing hook-CWD execution, timeout and persistence
misclassification, unredacted diagnostics, silent unknown-type allow, and unknown-mode blocking. The member shipped in
PR #130 (`fee562ab`) on 2026-08-05 before transcript-artifact work was activated.

D007/D024 were rechecked again on the execution branch from `fee562ab`. The two retained regression modules failed in
six cases before implementation, covering duplicate and clobbering writes, schema pollution, two broken read paths, and
both bypassed budget preflights. The member shipped in PR #131 (`3e090ef5`) with focused, regression, unit, and required
Docker-hook coverage before D039 was activated.

D039 was rechecked again on the execution branch from `3e090ef5`. Its retained regression failed before implementation
because Stop reported `queued_shadow=false` when the candidate existed under the mounted root but marker paths named
distinct host roots. The implemented split probes through the process-visible `SessionStore` root and translates only
the marker payload. Focused tests (120), the full sidecar hook integration file (4), the regression suite (659), and the
unit suite (8,734 passed, one pre-existing platform skip) passed. It shipped in PR #132 (`dc963a7c`) on 2026-08-06.

## Drift Constraints

- Do not add arbitrary-command verification or hide unknown configuration as success.
- Do not charge the fixed test subprocess wall time to Forge's under-100-ms overhead measurement.
- Do not append snapshot-only records to the canonical transcript-artifact schema or discard malformed durable state.
- Keep canonical transcript-list selection behind one session-layer selector across manager, transfer, and fork without
  absorbing D023's broader source-resolution work.
- Preserve existing transcript files and provenance while tolerating legacy duplicate and PreCompact-shaped records.
- Keep sidecar candidate discovery on a container-visible path and deferred marker payloads host-resolvable.
- Preserve fail-open hook behavior, rate-zero shadow inertness, and idempotent pending-work markers.

## Closeout

All three members shipped independently with marked regressions and their required Docker integration coverage. The
review ledger, member cards, and normative design documentation record the final contracts; Wave 3 is coordinated
separately by [`epic_session_durable_state_safety`](../epic_session_durable_state_safety/card.md).
