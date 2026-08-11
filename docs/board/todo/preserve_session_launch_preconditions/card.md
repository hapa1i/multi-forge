# Preserve session launch preconditions

**Epic**: [`epic_wave6_correctness_maintenance`](../../doing/epic_wave6_correctness_maintenance/card.md).

**Lane**: `todo/` -- accepted Wave 6 work; parked pending fail-first regressions.

**Findings**: O011, O017, O021, O023, O029, and O030.

## Goal

Validate launch prerequisites before durable mutation, roll back derived state when fallback preparation fails, and keep
best-effort post-launch/capability detection from corrupting later launches.

## Evidence and Authority

On `246aaff1`, one incognito `ForgeOpError` path skips host cleanup; rewind resume ignores an unready transcript;
generic unknown-option text can disable JSON globally; fork checks a required parent UUID after mutation; launch
confirmation catches only a missing file; and derived resume names can exceed 64 characters after context creation.
[`docs/design.md` §§3.3, 3.9](../../../design.md#33-session-file-schema-forgesessionjson) define durable mutation and
launch ordering.

## Acceptance Criteria

- Incognito failures clean up regardless of host/sidecar launch mode.
- Unready rewind artifacts remove the derived child and fail before invoking Claude.
- JSON capability latches only when the rejection explicitly names `--output-format`.
- UUID/name validation happens before fork/resume artifacts, manifest, worktree, or branch mutation; transfer/no-launch
  paths that do not require a UUID remain legal.
- Launch confirmation catches/logs every ordinary store/path failure and never changes the completed launch result.
- Retain regressions and run targeted session/Codex-runtime integration tests required by repository policy.

## Compatibility and Exclusions

Preserve native/transfer/rewind launch shapes, concurrent-delete authority, generated-context cleanup, and explicit user
names (which continue to fail normal validation rather than being silently truncated).
