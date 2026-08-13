# Simplify the count-tokens mode selector

**Epic**: [`epic_wave7_refactor_and_deletion`](../../doing/epic_wave7_refactor_and_deletion/card.md).

**Decision**: [`deletion_compatibility_contract`](../../done/deletion_compatibility_contract/card.md) (DG4).

**Lane**: `todo/` -- accepted Wave 7 script cleanup work.

**Finding**: O092's `scripts/count-tokens.py --local` subset.

## Goal

Keep the explicit `--local` CLI while making both mutually exclusive mode flags write one authoritative destination.

## Evidence and Authority

On `5777192a`, local counting is the default and `--provider-api` is the only remote path; argparse enforces mutual
exclusion, but `args.local` itself is unread. The public help surface makes flag deletion incompatible under DG4.

## Acceptance Criteria

- `--local`, omitted mode, and `--provider-api` select one named mode value with unchanged output/exit behavior.
- `--local --provider-api` remains an argparse error and help continues to describe both choices.
- Add direct script tests for all four invocations and run the repository token-count smoke checks.

## Exclusions

Do not remove `--local`, change token models/provider access, alter output schemas, or require network access for local
mode.
