# Epic: Installer transaction safety

**Parent epic**: [`epic_repo_maintenance_round`](../epic_repo_maintenance_round/card.md).

**Lane**: `doing/` -- D013/D014 shipped in PR #144 and D012 in PR #145; D019 is implemented and awaiting review as the
final member.

## Goal

Make extension enable, sync, and disable preserve one reversible installation state across Claude settings, Codex hook
registration, generated files, and the installed manifest without combining three independently reviewable fixes.

## Design Authority

- [`docs/design_appendix.md` §C.3](../../../design_appendix.md#c3-settings-merge-rules): settings removal uses the
  pre-Forge baseline, compares tracked values, and preserves user edits.
- [`docs/design_appendix.md` §C.4](../../../design_appendix.md#c4-durable-installproject-files): filesystem work
  precedes atomic tracking, later failures preserve or restore an honest state, and incomplete rollback is named.
- [`docs/design_appendix.md` §C.6](../../../design_appendix.md#c6-codex-hook-registration-hooks-codex-owned-half): Forge
  owns only one marker-delimited Codex block and preserves user content outside it.
- [`testing_guidelines.md` integration requirements](../../../developer/testing_guidelines.md#when-to-run-integration-tests):
  installer changes require targeted Docker integration coverage rather than host-only tests.
- [`review_combined.md`](../../review_combined.md#design-conformance-findings): D012–D014 and D019.

## Reproduction Record

All four findings were rechecked on merged `main` at `2461e3fa`. One disposable pytest module passed four assertions of
the documented broken behavior and was removed after the evidence was recorded. A fifth two-run characterization
corrected D012's stale source claim: sync replaces the tracked baseline path as well as creating the newer backup that
disable later selects.

| Finding | Fixture                                                                  | Observed result                                                                                           |
| ------- | ------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------- |
| D013    | fresh user install; real Codex merge; final tracking write raises        | the extension file rolled back, but the managed Codex block remained without an installation row          |
| D014    | fresh user install; Codex read-back raises after the managed-block write | raw `OSError` escaped; the extension file and Codex block remained without an installation row            |
| D012    | two settings-bearing runs with distinct backup timestamps, then disable  | sync replaced `settings_backup_path`; disable selected that Forge-bearing backup and retained Forge state |
| D019    | legacy tracked scalar/env values, no ownership sidecar, then user edits  | full disable deleted both user-modified values instead of comparing them with the tracked Forge values    |

## Members and Sequence

| Order | Findings  | Member                                                                                        | Review boundary                                             |
| ----- | --------- | --------------------------------------------------------------------------------------------- | ----------------------------------------------------------- |
| 1     | D013–D014 | [`rollback_codex_install_transaction`](../../done/rollback_codex_install_transaction/card.md) | Codex mutation, failure rollback, and final tracking commit |
| 2     | D012      | [`preserve_install_settings_baseline`](../../done/preserve_install_settings_baseline/card.md) | Immutable pre-Forge baseline across enable/sync and disable |
| 3     | D019      | [`preserve_legacy_settings_user_edits`](../preserve_legacy_settings_user_edits/card.md)       | Value-aware fallback when no ownership sidecar exists       |

D013 and D014 stay together because one pre-mutation Codex snapshot and one rollback path must cover both the post-write
read-back boundary and the later manifest commit; splitting them would duplicate the transaction mechanism while
deliberately leaving one adjacent fault point live. That member goes first because a failed fresh enable can otherwise
leave state with no ownership row. D012 follows as the remaining HIGH-severity disable invariant. D019 is the bounded
legacy compatibility path and ships last.

D013/D014 restores the exact Codex config bytes/mode across apply, read-back, and final tracking failures while
preserving and reporting a later concurrent edit. Independent review found no design violations, and the member shipped
in PR #144 (`37a03209`). D012 now retains one immutable settings baseline across enable/sync and both disable paths; its
review's one LOW tracked-baseline deletion race is closed, and the member shipped in PR #145 (`f069226f`). D019 now
removes legacy scalar/environment values only when they still match tracking; its fail-first regression plus host,
Docker, and clean-wheel coverage pass, and independent review/merge remain.

## Drift Constraints

- Preserve Codex's visible best-effort `unavailable` and conflict outcomes, manual-registration dedupe, stable trust
  bytes, and scope validation.
- A failed operation may remove only content created by that attempt; pre-existing Codex bytes and file mode must be
  restored exactly, and incomplete rollback paths must remain visible.
- Keep the pre-Forge settings baseline distinct from per-attempt rollback snapshots and immutable across later
  enable/sync runs.
- When a tracked baseline path exists, do not silently substitute a newer backup. Legacy rows without the field need an
  explicit compatibility test rather than an invented baseline.
- Preserve hooks and permissions matching behavior while making only the legacy scalar/env fallback value-aware.
- Do not change the installed-manifest schema unless execution proves the existing `settings_backup_path` field cannot
  express the contract.
- Every bug member must add a dedicated marked regression that fails on its merged-`main` base, run the targeted Docker
  installer tier, and exercise the clean wheel path required for installer changes.

## Closeout

Close this epic only after all three members ship independently, the review ledger records each outcome, the normative
installer contract matches the implemented rollback and baseline ownership, and enable/sync/disable integration covers
both Claude and Codex surfaces.
