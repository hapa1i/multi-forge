# Session delete and purge checklist

**Branch**: `codex/session-delete-and-purge`, based on `a33c4d24`. **Current focus**: final verification and PR review.
The [card](card.md) owns the intended behavior; the [audit](evidence/ownership-audit.md) records current code and gaps.
Implementation is in progress; checked acceptance items require the verification recorded below.

Planning verification (2026-10-20): targeted `pre-commit run --files` passed for the three card documents, including
formatting and size limits; the full Markdown link audit passed for 737 sources, and `git diff --check` passed. The two
isolated reproductions are recorded in the audit. Implementation and native verification are recorded below and in
[verification](evidence/verification.md).

## 1. Activation and verified discovery

- [x] Create the execution branch and move the owner's uncommitted card to `doing/`; preserve unrelated `AGENTS.md`
  edits.
- [x] Verify the delete/clean/incognito paths and context/queue contracts at `a33c4d24`; record findings in the audit.
- [x] Reproduce incognito transcript retention and same-name journal reuse with synthetic state in temporary homes.
- [x] Resolve dependent-session handling with the owner: both delete and purge refuse existing dependents. No ancestor
  archive, implicit cascade or partial-purge acknowledgment in this version.
- [x] Finish the ownership inventory with every producer, consumer, reference field and cleanup authority. Cover the
  global reviewer home and pending QA/walkthrough copies as well as project artifacts, transfers, search and work
  queues.
- [x] Define a complete dependency scan across registered Forge roots and relevant manifests. Include inactive children,
  supervisor sources, borrowed plans, context/transcript paths, shared UUIDs and native ancestry. Corrupt or unreadable
  sources must produce an actionable refusal rather than an empty dependency set.
- [x] Pin the definition of active native conversation and how inactivity is established for adopted sessions outside
  Forge's active registry. Unknown activity cannot authorize purge.

## 2. Instance identity and destructive-operation admission

This precedes content removal. The [generation-token proposal](../../proposed/session_delete_generation_token/card.md)
already records a stale-deleter race. Its terminal index guard is necessary but does not cover artifact or worker
writes.

- [x] Explicitly fold the identity prerequisite into this card's branch/PR; the card records ordering and integration
  ownership. Read index v1 without writes; confirmed operations bind its existing review owner, or create an owner only
  for validated ownerless state without old review history. Index v2 records that instance. Unreadable ownership refuses
  migration.
- [x] Carry `(forge_root, session instance)` through discovery, dependency scans, queue markers, detached workers,
  artifact writes and deletion retries. Revalidate ownership at each mutation boundary; names and timestamps are
  insufficient identities.
- [x] Establish the lock/exclusion order with index publication, manifest updates, conversation locks, marker locks and
  reviewer leases. A concurrent launch, new dependent, stale worker or same-name creation must not cross deletion's
  admission boundary unnoticed. Do not hold a global lock across model calls.
- [x] Prevent queue drain and automatic retention from mutating the target before delete/purge preview or confirmation.
  Root CLI startup currently drains session commands before their leaf handlers.
- [x] Define behavior for malformed manifests, absent worktrees, legacy artifacts without ownership evidence, symlinks
  and path replacements. Neither `--force` nor raw path strings may supply missing native deletion authority.

## 3. Shared inventory and failure handling

- [x] Add a session-domain cleanup planner and typed plan/result; use it for CLI preview and apply, explicit delete,
  clean, retention and incognito. Keep owner-specific native discovery and search/queue cleanup in their existing
  domains.
- [x] Classify exact absolute paths as remove, retain, refuse or outside scope. Include author-edited transfer overlays
  in the disclosed inventory. Inspect only supported per-session data, never sweep a native home by glob.
- [x] Refuse dependencies before any mutation. For explicit multi-name and `--all` batches, define and test dependency
  ordering and partial-failure reporting; no target outside the approved set may be selected implicitly.
- [x] Revalidate the inventory at apply and immediately before unlink. Changed identity, dependencies or activity must
  refuse/replan visibly; do not silently expand the approved set.
- [x] Preserve retry state outside any checkout scheduled for removal, or prove an ordering that keeps the inventory
  available through every failure. Record identity and remaining targets; report failures instead of logging success.
- [x] Exercise native-unlink, search/queue removal, worktree removal and final record-removal failures independently.
  Repeating the command must finish the same instance without touching a replacement or unrelated files.

## 4. Forge-owned delete

- [x] Preserve all native Claude transcripts/subagents and Codex rollouts byte-for-byte, including adopted, relocated,
  rollover and rewind material. Remove `--keep-transcripts` from delete/clean and update rollback recovery hints.
- [x] Remove proven session-owned artifacts, plans, compaction snapshots, reports, journals, transfers and applicable
  pending-run/reviewer copies. Refuse shared references and active reviewer leases before cleanup.
- [x] Remove search documents plus BM25/content-store and fingerprint/index-state entries coherently.
- [x] Cancel owned pending and failed queue markers. Fence already-dispatched index, memory and shadow workers so they
  cannot persist results after cleanup or onto a replacement name.
- [x] Preserve worktree/branch choices and dirty-worktree guards. Explain when removing the checkout leaves a retained
  native conversation without its original directory. Protect cross-root dependencies before removing a containing root.
- [x] Route `delete --all`, `session clean` and automatic retention through the same delete contract. Retention skips
  dependencies with an applicable diagnostic and never becomes a native purge.
- [x] Add orphan-artifact cleanup to `forge clean` using the same ownership/reference rules; preview first, and retain
  unknown, modified ownership metadata or unreadable dependencies rather than inferring safety from a missing name.

## 5. Native purge and incognito

**Gate:** finish a concrete native-layout probe plan before any new native run. Synthetic fixtures prove code behavior;
they do not establish an undocumented client layout. Use isolated homes and disclose any required paid invocation before
requesting its approval. Existing host Codex integration fixtures can select the user's real home.

- [x] Record admitted Claude/Codex versions, exact runtime-generated files from disposable conversations with synthetic
  content, inactivity evidence, shared ancestry, sidechains and excluded runtime state. Reuse applicable versioned
  evidence; probe only unresolved contracts.
- [x] Implement provenance-aware identity checks: original Claude project/CWD and UUID, native-relocate
  source/destination, rewind's fresh filename with preserved parent envelope, Codex thread/header CWD, and path
  containment.
- [x] Add `forge session purge <name>...` and `forge session purge --all`: preview by default, `--yes` apply, stable
  `--json` preview, grouped absolute paths and out-of-reach list. No automatic retention or force bypass of inactivity,
  identity and dependency guards.
- [x] Match `delete --all` selection: current Forge project required, include incognito candidates, reject explicit
  names with `--all`, reject a missing selector, and succeed on an empty project. Preview all eligible/refused targets;
  apply only the initially admitted set, report per-session results, and exit non-zero for any refusal or failure. Never
  add newly created/replacement instances or initially refused targets to an approved batch. Dependencies between
  selected sessions remain subject to the same refusal contract, independent of processing order.
- [x] Include adopted native conversations with an explicit preview label. Remove only admitted, verified native files;
  external copies, provider data, project memory docs, git history, telemetry and unprobed runtime indexes remain
  outside the guarantee.
- [x] Make incognito exit invoke the same bounded purge after runtime exit. Treat starting incognito as the automatic
  cleanup exception, and retain actionable retry evidence if cleanup cannot finish.
- [x] Replace old incognito journal-survival assertions with the new cleanup contract and add regression coverage for
  both reproduced gaps.

## Acceptance matrix

Existing suites are named below; new tests are explicitly marked.

| Concern             | Fixture                                                  | Required observation                                     | Test home                                                            |
| ------------------- | -------------------------------------------------------- | -------------------------------------------------------- | -------------------------------------------------------------------- |
| Native preservation | Claude/Codex, adopted/relocated/rewind                   | Delete leaves native bytes unchanged                     | `tests/src/session/test_manager_delete.py`                           |
| Pure preview        | Pending work, stale indexes, cancelled confirmation      | No spawn, repair or target mutation                      | `tests/regression/test_bug_session_delete_preview_index_mutation.py` |
| Dependencies        | Inactive cross-root child or supervisor                  | Named refusal; no file removed                           | New session cleanup-plan tests                                       |
| Name reuse          | Delete/recreate plus stale second deleter                | No predecessor history or replacement damage             | Existing crash-atomicity suite + new journal regression              |
| Incognito           | Synthetic Stop capture then exit                         | Owned transcript/artifacts/journals removed              | New incognito-artifact regression                                    |
| Late worker         | Dispatched writer paused before persistence              | No files or search entries recreated                     | Queue/search/memory/shadow tests                                     |
| Native identity     | Symlink, wrong CWD/id, native-relocate and rewind        | Refuse mismatches; admit proven special forms            | Native cleanup/adoption suites + new purge tests                     |
| Active purge        | Managed or adopted active runtime                        | Refusal even with force                                  | New purge CLI tests                                                  |
| Retry               | Failure at each cleanup stage                            | Inventory survives; retry affects original instance      | New cleanup transaction tests                                        |
| Bulk/retention      | Shared, dirty and inactive candidates                    | Preview/apply agree; native files retained               | `tests/src/session/test_cleanup.py`                                  |
| Bulk purge          | Two Forge roots; eligible, active and dependent sessions | Project-scoped set; guards retained; preview/apply agree | New purge CLI and cleanup transaction tests                          |
| Orphan collection   | Legacy artifact tree, reference or unreadable owner      | Disclosed set only; unknown stays intact                 | New global-clean artifact tests                                      |
| Runtime layouts     | Isolated native homes on admitted versions               | Exact per-conversation targets and exclusions            | New targeted Docker purge integration                                |

## Documentation, checks and closeout

- [x] Sync shipped behavior in `design_sessions.md`, `design_session_context.md`, `design_session_execution.md`,
  `docs/end-user/session.md` and `docs/cli_reference.md`; update `design.md` only if its ownership map changes.
- [x] Update the session-deletion verification paragraph in `AGENTS.md` without folding in unrelated local edits.
  Reconcile contradictory historical ownership notes through the repository's human-reviewed note process.
- [x] Verify CLI help and stream placement, JSON preview, cancellation, delete, purge, clean, incognito and orphan
  cleanup using isolated state. Extend `tests/src/cli/test_output_streams.py` for the new read surface.
- [x] Run focused unit/regression tests and targeted Docker integration through `scripts/test-integration.sh`; do not
  substitute synthetic fixture success for the native-layout gate.
- [x] Run `make test`, `make test-regression`, `make pre-commit`, Markdown links and file limits before final review.
  Record commands, failures/skips and native evidence separately.
- [ ] Commit reviewable changes, open/attach a PR, and keep the checklist aligned with remaining gates.
- [ ] After merge, record verification and closeout, move to `done/`, update incoming links and the change log.
