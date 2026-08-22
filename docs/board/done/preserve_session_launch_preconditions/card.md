# Preserve session launch preconditions

**Epic**: [`epic_wave6_correctness_maintenance`](../epic_wave6_correctness_maintenance/card.md).

**Lane**: `done/` -- shipped in PR #176 (`88ac88c5`).

**Findings**: O011, O017, O021, O023, O029, and O030.

## Goal

Validate launch prerequisites before durable mutation, roll back derived state when fallback preparation fails, and keep
best-effort post-launch/capability detection from corrupting later launches.

## Evidence and Authority

Rechecked on merged production code at `967d9cae`: the host-mode `ForgeOpError` fork arm alone skips incognito cleanup;
fresh rewind resume ignores `resume_transcript_ready`, while the worktree-fork sibling already rolls back; generic
argparse rejection phrases still disable JSON process-wide without naming `--output-format`; the common fork UUID check
runs after child creation and incorrectly gates transfer and `--no-launch`; launch confirmation guards only its import
and missing-manifest update race; and both derived and explicit invalid resume names reach transfer-context creation
before validation.
[`docs/design_sessions.md` §§3.3, 3.9](../../../design_sessions.md#33-session-file-schema-forgesessionjson) define
durable mutation and launch ordering.

The retained regression artifact produces `15 failed, 7 passed` on that unchanged cursor. Each finding has a direct
failure, while controls preserve sidecar/non-incognito cleanup, a usable same-directory rewind fallback, explicit
`--output-format` rejection, confirmed-parent native fork, missing-transcript no-op, and valid resume context creation.

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

## Implementation Outcome

- Typed incognito fork failures now run the same cleanup in host and sidecar modes, and an unready fresh-rewind fallback
  removes its derived child before returning without launching Claude.
- JSON capability rejection requires an explicit `--output-format` token. Generic argument failures no longer retry or
  disable JSON output for later process calls.
- Launched native forks validate the parent UUID before proxy startup or `fork_session()` mutation. Transfer and
  `--no-launch` paths remain UUID-free, and resume child names are validated before transfer-context generation.
- Launch confirmation catches and logs ordinary transcript-path and manifest-store failures while preserving the
  completed launch result and the existing concurrent-delete guard.

## Verification

- Retained regressions: `22 passed` after producing `15 failed, 7 passed` on `967d9cae`.
- Focused fork, rewind, resume, JSON-capability, and confirmation slice: `168 passed`.
- Marked regression gate: `894 passed`.
- Unit gate: `9004 passed, 1 skipped, 122 deselected`.
- Targeted session-command, Codex-session-start, and Docker rewind-contract integrations: `48 passed`.
- Full pre-commit passed after expected Black/Markdown normalization. The final board audit found 297 Markdown files,
  723 local links, no missing targets, and the intended Wave 6 split of 11 done / 1 doing / 1 todo members.
- Normative design and end-user docs were reviewed; no update is required because the fixes restore their existing
  launch-ordering and best-effort contracts without changing architecture, ownership, or CLI surface.
