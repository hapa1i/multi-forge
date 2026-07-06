# diverged_twin_consolidation -- collapse already-drifted twin copies in the session family and cli-hooks

**Lane**: `doing/` -- active phased card (branch `refactor/diverged-twin-consolidation`). Consolidation of
must-stay-identical copies, several already drifted or bug-shipping; mostly behavior-preserving, with **two defect-fix
slices** (Slice 1 restores the transcript-artifact type guard; Slice 2 fixes the `%policy check` nested-layout
misorder). Independently shippable slices.

> **Superseded (2026-07-05):** taken into `doing/` as a **single phased card** (this directory), mirroring the
> `state_primitive_hoist` precedent. The per-slice member-card / epic suggestion below is not the active structure; each
> phase in `checklist.md` is still independently landable as its own commit/PR.

**When accepted**: a batch of independent consolidations, not one seam. Per `docs/developer/board_contract.md`, promote
as **separate member cards per slice** (or an `epic_session_hook_dedup` coordinator if the session-family slices need
shared sequencing against in-flight session work) rather than moving the whole batch to `doing/` at once.

**Origin**: full-codebase refactor audit, 2026-07-05 (`/refactor_audit whole repo --full`; area auditors cli-session,
cli-hooks, session-pkg). The inheritance allowlist, the transcript-artifact guard gap, and the TDD-sort drift were
inline-verified by reading both copies; the micro-copy cluster and preflight/lane fragments are auditor first-pass
evidence (adversarial refuter spend-capped -- re-verify the counts before the relevant slice).

**Type**: **refactor batch card**, deliberately **not an epic**. Two areas (session command family + `cli/hooks/`) share
the theme "one concept, hand-synced twins," not a load-bearing contract. Splittable into two cards if preferred.

**References**: `docs/design.md` §3.3 (session schema, intent inheritance), §3.10 (hooks); `docs/design_workflows.md`
§1.1 (TDD `applies_to` nested-aware gating); `docs/board/impl_notes.md` (memory inheritance, consumer-lane freeze, codex
preflight cache); archetype `docs/board/done/session_op_layer_extraction/card.md` (the same family, prior slice).

---

## Why (the thesis)

The `session_op_layer_extraction` card (closed 2026-07-02) cleaned the CLI-vs-ops boundary for the launch path. It
deliberately left the intra-family *micro-duplication* for a second pass -- its own Slice 3 goal named "collapsing the
five `_launch_*`/`_resume_*` helpers' repeated logic." This card is that second pass, plus the parallel cluster in
`cli/hooks/`. The findings are must-stay-identical copies, and three have **already drifted or shipped a bug**:

1. **Intent-inheritance allowlist copied 3x.** The tuple
   `("subprocess_proxy", "policy", "memory", "system_prompt", "verification", "consumer_lanes")` plus the
   `_inherited_launch_intent(parent)` block is byte-identical at `session/manager.py:896`, `:1309`, `:1548` (resume
   child, fork, into-fork). Add a new inheritable intent field, forget one path, and you ship a silent inheritance bug
   -- the audit's evidence is that this class has bitten before.
2. **Transcript-artifact extraction lost its type guard on one copy.** `manager.py` has a helper (`:238`/`:246`) and two
   inline copies; the native-resume branch at `:758` assigns `latest.get("copied_path")` into a `str | None` field
   **without** the `isinstance(str)` guard its twin at `:804` and the helper both have (Surfaced Defect -- a malformed
   manifest passes a non-str through).
3. **TDD tests-first sort drifted between the CLI diagnostic and the Codex enforcer.**
   `cli/hooks/direct_commands.py:_sort_tests_first` (`:1194-1209`) uses top-level `startswith("tests/")` prefix
   matching; `cli/hooks/codex_policy.py:sort_contexts_tests_first` (`:177-197`) uses the **nested-aware**
   `is_under_directory` rule -- the exact fix (with regression `test_bug_codex_tdd_nested_layout.py`) the CLI copy never
   got. The two disagree on `pkg/tests` + `pkg/src` layouts (Surfaced Defect).

The rest are must-stay-identical copies without (yet) shipped drift: the supervisor flag family duplicated between
`start` and `fork`; the `else "claude_code"` runtime default inlined 5x; `LaneRecord -> Lane` inlined 4x while
`consumer_lanes._record_to_lane` exists; the codex preflight readiness gate byte-identical in all three dispatch arms;
the byte-identical teammate-idle / task-completed hook bodies; and the Stop / StopFailure transcript-capture core.

---

## Non-goals / must-not-break

- **No behavior change on the consolidation slices** (3, 4, 5): same manifest writes in the same order, same dispatch
  semantics, same hook JSON. **Slices 1 and 2 are deliberate defect-fixes** (the missing `isinstance` guard; the
  nested-layout sort) -- they change an observable and each ships with a regression test.
- **Preserve the deliberate divergences** the audit flagged as intentional: the `_dispatch_codex_*` arms differ by
  design on degrade path / upstream-row / sandbox (impl_notes T6b/T6c) -- only the *shared preflight-readiness gate* and
  *lane conversion* are candidates, never the arm bodies. `fork` vs `resume` `--resume-mode` value sets stay distinct
  (documented asymmetry).
- **Do not re-open** the `session_op_layer_extraction` end state (that card's function-local imports are its documented,
  deliberate output -- refuted in this audit; see that card).
- **Rendering stays in the CLI**; supervisor-flag consolidation shares the option *definition* and *validation*, not the
  Rich presenters.

---

## Target shape

| Concept                                  | Target home                                                                            | Current copies                                                               |
| ---------------------------------------- | -------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------- |
| Intent inheritance                       | `manager._inherit_intent_fields(child, parent)` (single allowlist + launch block)      | manager.py:896, :1309, :1548                                                 |
| Latest transcript artifact               | one `latest_transcript_artifact(state)` helper with the `isinstance` guard             | manager.py:238 (helper), :758 (guardless), :804                              |
| Fresh-resume context-limit ref           | one helper (the drifted `session_lifecycle.py:641` reconciled)                         | session_resume_modes.py:41, :147; session_lifecycle.py:1849, :641            |
| Supervisor flag family (start/fork)      | shared Click option-group decorator (mirror the codex `*_options` composite exemplar)  | session_lifecycle.py:932/1071/806; session_fork.py:216/338/710               |
| Session runtime default                  | `resolve_session_runtime(state)` (the named accessor in codex_session.py:111 promoted) | claude_session.py:384; session_manage.py:878/1206; session_lifecycle.py:1391 |
| `LaneRecord -> Lane`                     | call existing `consumer_lanes._record_to_lane` (make it non-private)                   | supervisor.py:730/806; shadow_curation.py:330; memory_writer.py:420          |
| Codex preflight readiness gate           | one `codex_preflight_cache` accessor the 3 arms share                                  | supervisor.py:647; shadow_curation.py:476/517; memory_writer.py:693/732      |
| TDD tests-first sort                     | one `sort_tests_first(paths)` keyed on `is_under_directory` (the fixed rule)           | direct_commands.py:1194; codex_policy.py:177                                 |
| teammate-idle / task-completed hook body | shared handler body                                                                    | commands.py:1722-1770, :1773-1821                                            |
| Stop / StopFailure capture+reconcile     | shared capture-and-reconcile helper                                                    | commands.py:400-470, :661-727                                                |

---

## Phased plan (each slice independently landable)

| Slice | Scope                                                                                                                       | Exit signal                                                                                                        |
| ----- | --------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| 1     | Inheritance allowlist -> `_inherit_intent_fields`; transcript-artifact helper applied at all 3 sites (fixes the guard gap). | one allowlist definition; `:758` has the `isinstance` guard; regression test for the malformed-manifest case       |
| 2     | TDD tests-first: one `sort_tests_first` on `is_under_directory`; repoint `%policy check` + codex sorter.                    | both call one helper; regression test asserts `%policy check` orders a nested `pkg/tests`+`pkg/src` diff correctly |
| 3     | `resolve_session_runtime` + `_record_to_lane` (promote) + shared codex preflight gate.                                      | `rg 'else "claude_code"'` inline count drops; the 3 arms call one preflight accessor                               |
| 4     | Supervisor flag family: shared option-group decorator for start/fork; context-limit ref helper.                             | `start`/`fork` share one option definition; validation lives once                                                  |
| 5     | teammate/task hook body + Stop/StopFailure capture core.                                                                    | one handler body each; hook JSON byte-identical (characterization test)                                            |

---

## Blast radius

- **Test coupling:** the session family is the repo's highest patch concentration (`test_session_commands.py`, 4933
  lines). Slice 1/3/4 touch `manager.py` / `session_lifecycle.py` / `session_fork.py` -- count
  `patch("forge.cli.session_*")` and `patch("forge.session.manager.*")` sites before each move; repoint per slice.
- `cli/hooks/commands.py` (1913 LOC) Slices 2/5: hooks are integration-tested against real `claude -p`/Docker -- run the
  hook integration path, not just unit, before finishing (testing_guidelines.md).
- `_record_to_lane` non-private rename: ~4 call sites + their patches.

## What was verified vs. first-pass

- **Inline-verified (High):** inheritance allowlist byte-identical at 3 sites; transcript-artifact guard gap at `:758`;
  TDD-sort prefix-vs-nested divergence (read both, plus the codex docstring naming the fix).
- **First-pass, re-verify (Medium):** the micro-copy cluster counts (memory-flag x6 etc.), the 4x lane conversion, the
  3x preflight gate, teammate/task and Stop/StopFailure bodies -- their adversarial refuters were spend-capped.

## Adversarial verification (survived where run)

The auto-refuter confirmed no design doc / impl_note / board card adjudicates the CLI-vs-hook TDD-sort duplication or
the supervisor-flag start/fork duplication as deliberate; the nearby adjudications (cascade launch asymmetry, dual
effort vocabularies, `_dispatch_codex_*` arm divergence) are different seams whose invariants this card preserves.

## Risks

- **Behavior drift is the failure mode, not test breakage.** Every slice is a pure move: identical manifest writes /
  hook JSON in identical order. Add a characterization test before Slices 1 and 5.
- **Slice 2 changes an observable** for nested-layout projects (the `%policy check` ordering becomes correct). That is
  the point -- pair it with the Surfaced Defect fix, not framed as pure refactor.
- **Preserve the intentional divergences** (see Non-goals) -- consolidating the codex preflight gate must not fold the
  arm bodies.

## Metric / falsifiable prediction

Prediction: adding a new inheritable intent field touches **1 allowlist, not 3**; a nested `pkg/tests`+`pkg/src` diff
orders identically under `%policy check` and the Codex hook; a new consumer's lane conversion reuses `_record_to_lane`.
Confirm on the next inheritance-field PR and the next TDD-layout report.

## Acceptance (per-slice)

Tick only when: (a) `rg` of the collapsed pattern shows one definition; (b) a characterization test pins identical
writes/JSON; (c) the focused test module **and** (for Slices 2/5) the hook integration path pass; (d) the documented
divergences remain intact; (e) **the two defect-fix slices carry a regression test** -- Slice 1 the malformed-manifest
(non-str `copied_path`) case, Slice 2 the nested `pkg/tests`+`pkg/src` ordering under `%policy check`.

## Closeout

(pending)
