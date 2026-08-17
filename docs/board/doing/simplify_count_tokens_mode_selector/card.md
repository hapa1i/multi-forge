# Simplify the count-tokens mode selector

**Epic**: [`epic_wave7_refactor_and_deletion`](../../doing/epic_wave7_refactor_and_deletion/card.md).

**Decision**: [`deletion_compatibility_contract`](../../done/deletion_compatibility_contract/card.md) (DG4).

**Lane**: `doing/` -- active on `refactor/simplify-count-tokens-mode-selector` from the order-21 closeout (`78678e18`).

**Finding**: O092's `scripts/count-tokens.py --local` subset.

## Goal

Keep the explicit `--local` CLI while making both mutually exclusive mode flags write one authoritative destination.

## Evidence and Authority

Reverified on `78678e18`: local counting remains the default and `--provider-api` remains the only provider-attempt
path; argparse enforces mutual exclusion, but `args.local` is still unread. The help surface still documents both flags,
so deleting `--local` would violate DG4.

Executable characterization confirms omitted mode, `--local`, and a network-free OpenAI-shaped `--provider-api`
invocation all exit zero with the same count, while the conflicting pair exits two. Before this member, no direct test
pinned those four invocations.

## Acceptance Criteria

- `--local`, omitted mode, and `--provider-api` select one named mode value with unchanged output/exit behavior.
- `--local --provider-api` remains an argparse error and help continues to describe both choices.
- Add direct script tests for all four invocations and run the repository token-count smoke checks.

## Exclusions

Do not remove `--local`, change token models/provider access, alter output schemas, or require network access for local
mode.
