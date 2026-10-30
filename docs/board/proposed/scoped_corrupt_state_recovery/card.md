# Scope corrupt-state recovery to the affected resource

**Lane:** `proposed/` -- P2 follow-up from
[derived-session override validation](../../doing/validate_derived_session_overrides/card.md).

## Problem and evidence

Generic corruption diagnostics suggest deleting `.forge` or `~/.forge` even when a single manifest is malformed or uses
an unsupported schema version. Those directories also hold unrelated durable state.

- `src/forge/cli/output.py`, `handle_corrupt_state_error`, offers deletion of the named file, project/global Forge
  directories and `forge clean` for every `StateCorruptedError`.
- `src/forge/session/store.py`, `_validate_data`, embeds "Delete this session and recreate it" in unsupported-version
  errors.
- `src/forge/cli/session_derived_preflight.py` provides scoped repair/restoration guidance for derivation, including
  suppressing the embedded version-reset advice. Other callers retain the generic guidance.
- `src/forge/core/ops/session.py`, `reset_session_overrides`, calls `snapshot_supervisor_options` before mutation. A
  truthy scalar/list at `overrides.policy.supervisor` reaches `dacite.from_dict` in `policy/semantic/identity.py` and
  raises an unclassified `AttributeError`. Derivation recovery handles this boundary, but the reset command still leaks
  a traceback instead of its configured-supervisor removal or absent-baseline restoration guidance.

## Scope

Make recovery guidance reflect the affected resource. Durable session/configuration failures should name the file and
offer applicable repair, restoration or version-compatibility guidance. Preserve narrowly scoped reset advice for
disposable runtime state where its owner establishes that rebuilding it is safe. Preserve retry/permissions guidance for
unreadable files. Consolidate the derivation-specific workaround when the shared handler can express this contract.
Classify malformed supervisor-container failures in the shared reset path without admitting a reset that currently
violates supervisor transition rules.

## Acceptance

- CLI tests cover malformed, unknown-field and unsupported-version manifests, resource-specific runtime corruption, and
  unreadable state.
- Diagnostics stay on stderr, preserve exception classifications and leave on-disk bytes unchanged.
- Recovering one durable record never recommends deleting project/global roots.
- Reset of a truthy scalar/list supervisor override produces an actionable refusal without a traceback or writes.
  Preserve existing nullable/falsey behavior and native/frozen supervisor identity checks.
- The user guide distinguishes restoration of durable records from rebuilding disposable runtime state.

Automatic repair, new migrations, broader cleanup/deletion behavior and lifecycle admission changes are out of scope.
