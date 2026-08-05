# Preserve transcript artifact identity checklist

Current focus: implementation and verification are complete; review and merge before activating D039 sidecar routing.

## Activation and reproduction

- [x] Start `fix/preserve-transcript-artifact-identity` from merged `main` at `fee562ab`.
- [x] Move the member from `todo/` to `doing/` and update parent-epic links and merge gates.
- [x] Retain marked regressions that fail on the duplicate-write and trailing-legacy-snapshot behaviors before the fix.
- [x] Confirm non-list transcript state is currently clobbered and record the exact execution-branch evidence.

## Implementation

- [x] Put canonical transcript validation and identity reconciliation behind one session-layer write helper.
- [x] Make Stop and SessionStart rollover use the shared write helper without changing their fail-open posture.
- [x] Put latest canonical transcript selection behind one session-layer read helper used by both manager seams, transfer,
      and CLI fork preflight.
- [x] Write new PreCompact metadata only to `confirmed.compaction.transcript_snapshots` and explicitly recognize the
      legacy mixed shape on read.
- [x] Preserve distinct records and provenance; surface unrelated malformed records and non-list state without clobbering
      them.
- [x] Synchronize normative manifest/artifact design documentation with the shipped schema and compatibility behavior.

## Acceptance tests

| Test | Fixture | Assertion | Test file |
| ---- | ------- | --------- | --------- |
| D007 repeated Stop | one transcript UUID captured twice, plus one distinct identity | one refreshed canonical record per identity; distinct record retained | `tests/regression/test_bug_d007_stop_artifact_idempotency.py` |
| D007 malformed state | mapping-valued canonical transcript field | write reports malformed state and leaves the value unchanged | focused session/hook unit tests |
| D024 new PreCompact | canonical transcript followed by PreCompact | snapshot metadata stays outside the canonical transcript list | `tests/regression/test_bug_d024_precompact_artifact_schema.py` |
| D024 legacy read | canonical record plus trailing recognized snapshot record | manager, transfer, and both budget preflights select the same canonical artifact | `tests/regression/test_bug_d024_precompact_artifact_schema.py` |
| Hook integration | repeated Stop, PreCompact, and SessionStart rollover | manifest schemas and artifact contents remain stable across hook boundaries | `tests/integration/cli/test_artifact_hooks_integration.py` |

## Verification and closeout

- [x] Run the focused unit and regression modules.
- [x] Run `./scripts/test-integration.sh tests/integration/cli/test_artifact_hooks_integration.py`.
- [x] Run `make test-regression` and `make test-unit`.
- [x] Run `make pre-commit`.
- [x] Record the outcome in the review ledger, card, and change log; move the member to `done/` with inbound links fixed.
- [ ] Review and merge this member before activating D039 sidecar routing.
