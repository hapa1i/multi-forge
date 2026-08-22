# Repository-Owned Context Limits Checklist

Activation base: `0bc42799` (`main`, 2026-08-22).

## Policy tooling

- [x] Add root policy, repository checker, pre-commit registration, and tests.
- [x] Align `count-tokens.py` with the configured Opus-first chain while retaining explicit local mode and returning the
  tokenizer family as machine-readable policy input.
- [x] Document config precedence, provider disclosure, targets, hard limits, and the historical exception.

## Design migration ledger

Every original level-2 through level-4 section must be assigned below before the appendix is deleted. `Integrated` means
its complete unique contract is represented at the destination; it never means discarded.

| Original section                                                       | Destination              | Disposition |
| ---------------------------------------------------------------------- | ------------------------ | ----------- |
| `design.md` §1-§2                                                      | `design.md`              | Moved       |
| `design.md` §3 prelude, project identity, context model, §3.1-§3.2     | `design.md`              | Moved       |
| `design.md` §3.3, §3.8-§3.10, §3.13                                    | `design_sessions.md`     | Moved       |
| `design.md` §3.4, proxy portions of §3.6, §3.7, §7                     | `design_runtime.md`      | Moved       |
| `design.md` §3.14                                                      | `design_telemetry.md`    | Moved       |
| `design.md` configuration/install portions of §3.6 and §5.1, §5.3-§5.4 | `design_installation.md` | Moved       |
| `design.md` §3.11-§3.12, §4, §5.2, §6                                  | `design.md`              | Moved       |
| Appendix §A.1-§A.5, §A.10                                              | `design_runtime.md`      | Moved       |
| Appendix §A.6-§A.7b                                                    | `design_installation.md` | Moved       |
| Appendix §A.8-§A.9, §A.11-§A.14                                        | `design_telemetry.md`    | Moved       |
| Appendix §B                                                            | `design_sessions.md`     | Moved       |
| Appendix §C-§D                                                         | `design_installation.md` | Moved       |
| Appendix §E                                                            | `design.md`              | Moved       |
| Appendix §G                                                            | `design_runtime.md`      | Moved       |
| Appendix §F                                                            | `design_history.md`      | Moved       |
| Appendix §H-§J                                                         | `design_sessions.md`     | Moved       |

## Other oversized documents

- [x] Extract the memory architecture from `design_workflows.md` into `design_memory.md`.
- [x] Move the retired WorkflowPolicy record verbatim into `design_history.md` so the shipped workflow contract stays
  below the migration target.
- [x] Rotate complete changelog entries into dated archives without shortening them.
- [x] Partition implementation notes by domain behind a compact index.
- [x] Partition the combined review into overview, finding inventories, and execution ledger without dropping findings.

## Link and fidelity verification

- [x] Rewrite all appendix and moved-section links, including links in closed cards.
- [x] Verify all tracked local Markdown paths and fragments resolve and no reference to the retired appendix path
  remains.
- [x] Audit unique code fences, tables, identifiers, normative statements, edge cases, and examples against the
  activation-base sources; mark every migration-ledger row `Moved` or `Integrated`, never `Dropped`.
- [x] Record authoritative Opus counts for each resulting living/context document.

Fidelity evidence against activation base `0bc42799`:

- All 142 original level-2 through level-6 design headings are present. A normalized multiset of the 985 original
  non-navigation paragraphs has zero missing and zero extra instances; normalization covers only moved link targets,
  line wrapping, and repeated blockquote markers. All 52 fenced examples remain; the sole byte difference is the
  expected architecture-file path update in the directory-tree comment.
- All 26 changelog date blocks, 46 implementation-note sections, and 11 combined-review sections have a destination with
  zero missing heading or content instances.
- The repository link audit passes 566 Markdown sources, including same-document fragments and every moved ledger.
- Paired counts across the 20 resulting living/context documents put Opus at 1.597x-1.902x the local cl100k count
  (median 1.673x). The checked-in 12,000/15,000 local thresholds preserve a 2x safety ratio against the 25,000/30,000
  Opus target and ceiling instead of using the median as a hard-limit conversion.

Authoritative counts (`anthropic API (claude-opus-5)`):

| Document                                                    | Tokens |
| ----------------------------------------------------------- | -----: |
| `docs/design.md`                                            | 19,267 |
| `docs/design_sessions.md`                                   | 22,747 |
| `docs/design_runtime.md`                                    | 21,693 |
| `docs/design_telemetry.md`                                  | 20,483 |
| `docs/design_installation.md`                               | 20,074 |
| `docs/design_workflows.md`                                  | 22,947 |
| `docs/design_memory.md`                                     |  7,284 |
| `docs/design_history.md`                                    |    395 |
| `docs/cli_reference.md`                                     | 16,458 |
| `docs/board/change_log.md`                                  | 17,207 |
| `docs/board/archive/change_log_2026-08-05_to_2026-08-14.md` | 20,683 |
| `docs/board/archive/change_log_through_2026-08-04.md`       |  9,433 |
| `docs/board/impl_notes.md`                                  |    562 |
| `docs/board/impl_notes/core_installation.md`                | 10,422 |
| `docs/board/impl_notes/sessions.md`                         |  7,947 |
| `docs/board/impl_notes/runtime_telemetry.md`                | 19,221 |
| `docs/board/review_combined.md`                             |  7,156 |
| `docs/board/reviews/whole_repo_design_findings.md`          | 17,849 |
| `docs/board/reviews/whole_repo_maintenance_findings.md`     | 17,422 |
| `docs/board/reviews/whole_repo_execution.md`                | 10,793 |

## Verification and closeout

- [x] Run focused script/link tests, unit, regression, Markdown pre-commit, full pre-commit, and `git diff --check`.
- [x] Update the change log, close the card, push the branch, and open the PR.

Verification evidence:

- 101 focused token-policy and Markdown-link tests pass.
- 9,576 unit tests pass with 117 deselected; 1,057 regression tests pass.
- The repository link audit passes all 566 tracked Markdown sources.
- The file-size hook passes against all 1,658 eligible repository files in 3.2 seconds after per-file counts were
  batched into one process per method chain.
- Full pre-commit, Markdown pre-commit, and `git diff --check` pass.
- PR [#237](https://github.com/hapa1i/multi-forge/pull/237) opened from the verified four-commit implementation head.
