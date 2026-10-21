# Session cleanup verification

Implementation on `codex/session-delete-and-purge`, based on `a33c4d24`. This records the new contract; the
[ownership audit](ownership-audit.md) preserves the earlier behavior at its source revision.

## Ownership and exclusion

| Content                                            | Producer and consumer                                          | Cleanup owner                                                                    |
| -------------------------------------------------- | -------------------------------------------------------------- | -------------------------------------------------------------------------------- |
| Manifest, instance owner, runtime metadata         | Session manager, store, hooks, launch                          | `session/deletion.py`; entire metadata directory disclosed                       |
| Transcript, compaction and approved-plan artifacts | Stop, PreCompact, SessionStart; transfer, search and reviewers | `session/cleanup_content.py`                                                     |
| Authority, routing and review journals             | Authority commands, launch and policy hooks                    | Session artifact inventory                                                       |
| Memory, handoff and shadow reports                 | Instance-bound queue/direct workers                            | Session artifact inventory                                                       |
| Transfer cache, child snapshots and author notes   | Derivation preparation and transfer commands                   | Exact transfer inventory; borrowed contexts block removal                        |
| Pending and failed work                            | Work queue and detached consumers                              | Exact marker inventory plus instance admission                                   |
| Search documents, text, BM25 and fingerprints      | Index worker and explicit rebuild                              | `search/cleanup.py`, under all four store locks                                  |
| QA/walkthrough transcript copies                   | Pending-run capture                                            | Exact supported identity; unknown copies reported outside scope                  |
| Codex reviewer inputs                              | Reviewer preparation                                           | Exact attributed inputs under reviewer lease; auth and unrelated inputs retained |
| Native transcripts, agent logs and rollouts        | Claude/Codex clients                                           | `session/purge_native.py`; explicit purge only                                   |

The index publication lock precedes target manifest, reviewer and search-store locks. Apply holds the reviewer lease
before removing native files or Forge content; a busy reviewer refuses preview and apply without mutations.
Generation-bound worker leases cover long operations without holding the global index lock. Deletion refuses live or
abandoned leases. Supported parent context preparation acquires its lease before reading the parent and keeps it through
child publication. Transfer generation and notes editing also hold leases. Supervisor binding publication revalidates
both source and executor identities. Stale queue, hook and detached-worker results cannot write to a replacement
instance.

Launch and rollback carry the instance captured at child creation. Creation failure compensation checks indexed and
orphan session references before removing its worktree. Relative child-context paths resolve against the child's Forge
root; an absolute, validated parent-root snapshot remains supported. A same-named snapshot in the other root is
retained. Dependency scans include exact selected files outside the session's directories, so another session borrowing
a child snapshot or its notes blocks removal. Search retry keys outside the artifact directory must match a recorded
transcript path and any surviving search metadata ownership.

Worktree removal refuses overlaps with configured native homes and recorded native sources, even with `--force`. The
guard checks both recorded paths and resolved targets during preview and apply; `--keep-worktree` retains those
locations. Forced worktree forks capture the cleanup inventory before Git preflight and remove the old session through
the shared cleanup path before recreating its checkout. Branch advancement, dependencies or replacement ownership
prevent removal.

Sidecars receive a read-only mount of a host-held worker lease, bound to the exact session instance. Hooks validate it
against the mounted manifest without needing the host's global index. The host releases the lease only after Docker
confirms exit; an interrupted launcher or failed census retains the lease and blocks cleanup.

Dependency discovery includes registered roots and orphan manifests. Inactive children, borrowed context/plan paths,
configured prompt files, managed supervisor sources and shared native identities refuse cleanup. Legacy children resolve
parent roots through read-only index membership, with ambiguous candidates and same-directory fallbacks protected.
Unreadable state refuses rather than becoming an empty dependency set. Native purge also scans supported native ancestry
and observes a runtime-wide process census; it cannot prevent an unrelated external client from starting afterward.

The private retry inventory lives under `$FORGE_HOME/session-cleanup/`, outside a removed checkout. It binds the session
instance, original manifest, Git identity and authorized files. A retry tolerates already-removed targets but refuses
new files, changed contents or replacement ownership. Its existence reserves the name and rejects new producers. The CLI
prints the original `--forge-root` and options for recovery after worktree removal.

## Focused evidence

- `tests/src/session/test_deletion.py`: cross-root dependencies, changed admission, stale previews, durable retries,
  unsafe manifests and real linked-worktree replacement/partial removal.
- `tests/src/session/test_purge_native.py`: runtime identity, adoption/relocation/rewind provenance, ancestry, unknown
  layouts, native activity and descriptor-based file checks.
- `tests/src/session/test_cleanup_content.py` and `tests/src/search/test_cleanup.py`: exact owned content, author notes,
  QA/reviewer copies, all search representations, changed inventories and interrupted removal.
- `tests/src/cli/test_session_purge.py` and `tests/src/cli/test_output_streams.py`: cancellation, pure JSON previews,
  project-scoped bulk selection, frozen refusals, removed options and recovery diagnostics.
- `tests/regression/test_bug_session_delete_generation.py`, `test_bug_session_parent_cleanup_race.py`,
  `test_bug_deleted_session_artifact_writer.py` and `test_bug_session_producer_generation.py`: replacement instances,
  parent preparation and late writers.
- `tests/regression/test_bug_session_creation_worktree_replacement.py` and `test_bug_incognito_cleanup_instance.py`:
  failed creation, prepared launches and incognito cleanup preserve replacement instances and their worktrees.
- `tests/regression/test_bug_cleanup_external_content_ownership.py` and `test_bug_session_cleanup_native_worktree.py`:
  borrowed external snapshots, changed search ownership and native storage inside a removable checkout refuse cleanup.
- `tests/regression/test_bug_force_worktree_fork_cleanup.py`: eight real Git cases cover shared cleanup before checkout
  replacement, dependency and branch refusals, and competing ownership. All 18 selected Docker tests passed, including
  the existing fork integration class.
- `tests/src/session/test_sidecar_workers.py` and the existing sidecar hook integration suite: exact delegated
  admission, stale leases, malformed census and uncertain exit. The focused sweeps passed 387 host tests and four
  no-provider Docker tests; the separate real-Claude slow trial was not run.
- Existing adoption, transcript-sharing, rewind and retention regressions now assert native preservation on ordinary
  delete. Unsupported external deletion remains distinct from supported cleanup, which refuses active launches.
- The memory-writer command treats a missing or replaced session as a no-op before provider dispatch. Its focused unit
  suite passed 39 tests, and the handoff Docker suite passed all 10 tests.
- Final deletion and startup-queue Docker checks passed 20 tests. Queue fixtures use real producer output with an
  instance identity; refusal tests verify stdout detail, stderr failure, unchanged corrupt manifests and shared-branch
  preservation.

## PR review corrections

All five reported issues were confirmed against the implementation. The new regressions cover:

- `test_bug_cleanup_implicit_dependencies.py`: prompt borrowers and legacy cross-worktree plan inheritance block
  preview, apply and retry without repairing the index. Duplicate names resolve by project and relative path; ambiguous
  parent candidates remain protected.
- `test_bug_launch_instance_environment.py`: an ownerless v1 Claude sidecar receives the instance minted by admission.
  Headless Codex start/resume use the target's captured token, admit its hook writes and restore the caller's
  environment after success or failure.
- `test_bug_codex_post_turn_identity.py`: both frontends preserve a replacement's manifest, receipts, pending context
  and index after runtime exit or between manifest and index publication, returning the completed result with a warning.
- `test_bug_force_fork_metadata_restore.py`: publication failure after force replacement does not recreate metadata for
  deleted artifacts and transfer files. Same-directory, `--into` and owned-worktree paths retain native files and report
  the prior target's removal. Refusal before cleanup preserves the original bytes; competing owners remain protected.

The force-fork failure boundary also covers Git recreation, runtime-config copying and preparation after successful
cleanup. Replacement cleanup checks the originally captured owner before removal, including legacy owners. Codex
post-turn publication also checks the captured instance after the runtime lease ends. The user guide now distinguishes a
refusal before removal from a creation failure after removal.

## Native evidence

The first separately approved synthetic Claude 2.1.245 invocation reported $0.01699045 and completed one subagent. Purge
correctly refused an uncharacterized 131-byte metadata companion. The separately approved follow-up invocation reported
$0.0170009 and captured that companion with its parent and agent logs. Total reported cost: $0.03399135. Both used
isolated Docker homes, no repository content or host mounts, and observed live-process refusal followed by post-exit
admission. No Codex invocation was made for this card; its versioned source evidence is reused by the probe plan. See
the [first plan](native-probe-plan.md), [follow-up plan](native-companion-probe-plan.md) and their execution records for
exact payloads and limits.

Capturing a native layout and replaying it through the finished cleanup implementation are separate checks. The
[offline replay](README.md) passed 297 selected Docker tests and exercised delete/purge against the captured parent,
agent and metadata bytes. A subsequent 47-test Docker sweep verified the final child-context path correction. These runs
had networking disabled, no credentials and no native invocation.

## Aggregate checks

Final checks after the PR review corrections on 2026-10-21:

| Command                                         | Result                                       |
| ----------------------------------------------- | -------------------------------------------- |
| `make test`                                     | 11,134 unit and 523 integration tests passed |
| `make test-regression`                          | 2,040 tests passed                           |
| `make pre-commit`                               | All hooks passed                             |
| `uv run python scripts/check-markdown-links.py` | 741 Markdown sources passed                  |
| `git diff --cached --check`                     | Passed                                       |

Tests ran with provider credentials unset, `PYTHON_DOTENV_DISABLED=1` and an offline dependency cache. Unit selection
deselected 117 integration-marked cases; integration selection deselected 13,330 nonselected cases, including slow
provider trials. All selected tests passed without retries. The integration run includes the exact-wheel release-image
check and the new cleanup lifecycle tests. Native-layout evidence remains the separately approved captures above.

Earlier aggregate attempts exposed the sidecar admission and forced-fork ordering gaps described above, plus obsolete
fixture assumptions and the missing environment-variable inventory entries. The final runs include those corrections.
The three edited design/session documents requiring provider counts have current, separately approved token-count
evidence; the repository file-size hook passes.
