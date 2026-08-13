# Remove the unreachable fork routing branch (retired)

> **RETIRED -- REFERENCE ONLY. DO NOT IMPLEMENT.**

**Outcome**: `folded`

**Retired**: 2026-08-13

**Epic**: [`epic_wave7_refactor_and_deletion`](../../doing/epic_wave7_refactor_and_deletion/card.md).

**Decision**: [`deletion_compatibility_contract`](../../done/deletion_compatibility_contract/card.md) (DG4; O096).

**Lane**: `retired/`. The deletion is folded into
[`extract_session_fork_execution`](../../todo/extract_session_fork_execution/card.md), where the branch precondition and
resulting routing plan can be characterized at the same seam. This card did not ship independently.

## Historical Goal

Remove `session_fork`'s second `elif proxy_name` resolution after characterizing the precondition that every proxy name
already produces `_preflight_routing`.

## Historical Acceptance Criteria

- Tests prove proxy, inherited, and direct modes choose the same effective template, URL, and proxy ID after deletion.
- Routing resolution still occurs once before mutation and retains current error output.
- Run focused fork/routing tests and targeted session integration coverage.
