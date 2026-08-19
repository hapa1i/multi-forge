# Remove verified internal residue

**Epic**: [`epic_wave7_refactor_and_deletion`](../epic_wave7_refactor_and_deletion/card.md).

**Lane**: `done/` -- shipped independently in PR #184 (`95488c10`) from order-6 closeout commit `4f167379`.

**Findings**: O098 and the verified `caps.py` branch subset of O092.

## Goal

Remove a bounded set of internal residue whose callers, ownership, and behavior have been mechanically characterized:
stale session re-export metadata, the zero-caller session summary helper, and an unreachable cap-state type guard.

## Evidence and Authority

Rechecked on merged `main` at `cd3e50e8`: `forge.cli.session` imports the lifecycle and management modules only for
Click registration and does not wildcard-import either module. No repository import or patch target consumes their
`__all__` lists. The rewind helpers belong to `session_rewind`; the only indirect production consumer can import its
helper from that owner. `_print_session_summary` has no caller beyond its stale `__all__` entry. Finally,
`core.state.read_json` returns `dict[str, Any]` and raises `StateCorruptedError` for every non-object JSON value, making
`load_cap_state`'s immediately repeated non-dict branch unreachable. These are internal seams, not documented Python
API. Authority: [`deletion_compatibility_contract`](../../done/deletion_compatibility_contract/card.md) and
[`docs/developer/coding_standards.md`](../../../developer/coding_standards.md).

The user explicitly admitted this mechanically verified, non-overlapping subset after the order-6 review. That is a
bounded sequencing exception, not authorization for a broader dead-code sweep.

## Acceptance Criteria

- Correct the three session module docstrings so they describe registration and direct ownership rather than a
  nonexistent parent-module re-export mechanism.
- Remove the lifecycle/management `__all__` lists and `_print_session_summary`; import the fork rewind helper directly
  from `session_rewind`.
- Remove only `load_cap_state`'s redundant non-dict guard, retaining all schema, proxy-ID, daily-window, and error
  behavior; add a regression proving non-object JSON is still rejected by the state reader.
- Re-run repository import, patch-target, entry-point, documentation, and resource searches immediately before deletion;
  run focused session/telemetry tests, targeted session integration, and full project gates.

## Implementation Outcome

The verified residue was removed without changing public commands or runtime behavior. Session lifecycle and management
modules no longer advertise stale re-export metadata, the zero-caller summary helper is gone, and `session_fork` imports
the rewind helper from its defining module. Cap-state loading now relies on the shared JSON object boundary instead of
rechecking an unreachable non-dict branch; a regression pins rejection of non-object JSON at that boundary.

Verification covered 508 focused tests, 23 targeted Docker session-lifecycle integrations, 9,113 unit tests with one
skip and 122 deselections, 898 regressions, full pre-commit, and board-integrity checks. PR #184 merged as `95488c10`.
No Forge workflow command was used.

## Exclusions

Do not absorb O084's public CLI contract, converter/Gemini candidates, release-gated deprecations, or O092's unnamed
tail. Do not change Click registration, session output, cap schemas, tolerant-reader policy, or wire conversion.
