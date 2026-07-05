# policy_shared_library_seam -- build the reactive shared-library seam design_workflows promises

**Lane**: `proposed/` -- accepted-candidate refactor, not yet scheduled. Extraction of the direct-LLM-call + emission
recipe and the supervisor block-bar into the shared `core/reactive/` utilities the design doc already specifies.
Slices 1-3 are behavior-preserving; **Slice 4 is a defect-fix** (the team supervisor's missing confidence/citation bar
and possible model-pin leak) that ships with regression tests. Independently shippable slices.

**When accepted**: this is one seam (the reactive shared library) staged in slices, so it can move to `doing/` as a
single card -- but Slice 4's two defect fixes may be pulled out and shipped first as standalone bug fixes if the seam
work is deferred.

**Origin**: full-codebase refactor audit, 2026-07-05 (`/refactor_audit whole repo --full`; area policy-pkg). The
four-site direct-LLM recipe and the block-bar re-implementation are auditor first-pass evidence with concrete anchors;
the adversarial refuters were spend-capped -- re-verify the per-site diffs before the seam is cut. Corroborated by two
surfaced defects (team supervisor missing the confidence/citation bar; possible executor model-pin leak).

**Type**: single **refactor card**, staged in slices. One seam (the reactive shared library), not an epic.

**References**: `docs/design_workflows.md` §2.1 (shared library scope table -- the seam this card builds), §1.2
(supervisor block-only-on-high-confidence + cited; fail-open), §3.5 (runners); `docs/design_appendix.md` §E (`core.llm`);
`docs/board/impl_notes.md` (supervisor launch controls -- the Click-free checker-helper source; single ledger emitter).

---

## Why (the thesis)

`design_workflows.md` §2.1 already declares a shared reactive library ("session runner, proxy resolution, throttle
cache, structured output, tagger, env builder, fan-out runner, adversarial runner") that policies and skills import
instead of hand-rolling. Most of it exists. But the **direct-LLM-call + usage-emission recipe** -- resolve routing, build
`core.llm` hyperparams, call, parse structured output, `emit_direct_llm_usage` best-effort -- is hand-rolled at four
sites that the library was meant to cover:

- `policy/workflow/stages.py:183-252` (checker stage)
- `policy/semantic/plan_check.py:394-479` (tier-1 checker)
- `policy/team/handlers.py:175-221` (team event tagger)
- `core/reactive/tagger.py:41-117` (action tagger)
- (+ `session/transfer.py:767-802`, the curation call, a fifth near-copy)

Because each is hand-rolled, correctness has already fragmented across them:

- **`policy/workflow/stages.py:ReviewerStage` re-implements the supervisor block bar** (`CONFIDENCE_THRESHOLD` +
  citation gate, `:255-302`) that `policy/semantic/verdict.py:114-189` owns -- synced by comment only. If the block rule
  changes on one, the workflow reviewer silently keeps the old bar.
- **`run_supervisor_check` inlines the body of `resolve_supervisor_lane`** (`supervisor.py:806-812` duplicates
  `:721-736`) instead of calling it.
- **`policy/team/handlers.py:245` is the last subprocess launcher on ad-hoc registry-only transport resolution** instead
  of the shared `resolve_subprocess_routing` chain every other consumer migrated to (its sibling docstring in
  `core/reactive/proxy.py:4` is now stale). This is also where the team supervisor blocks with no confidence bar and may
  leak the executor model-pin (Surfaced Defects).
- The anchored resume-id UUID regex is duplicated `policy/queries.py:16` vs `supervisor.py:40-42` and applied to the same
  value in one flow.

---

## Non-goals / must-not-break

- **No behavior change** to any policy verdict, throttle-cache key, or fail-open contract. The block bar, the throttle
  key (which includes `checker_effort`), and fail-open-on-error are load-bearing -- the shared helper must reproduce them
  exactly.
- **Preserve the single-ledger-emitter rule** (impl_notes shadow-sampling: `run_supervisor_check` is the sole cost/usage
  emitter; the shadow path parameterizes the label). The shared recipe must not introduce a second emit for the same run.
- **Preserve the checker-helper source of truth** (`policy/semantic/supervisor.py` holds the Click-free
  `CHECKER_PROVIDER_CHOICES`/`validate_checker_model`/`apply_checker_options` per impl_notes) -- extend it, do not fork
  it.
- **Fail-open is mandatory** (§1.2): every extracted call site keeps its degrade-to-allow / degrade-to-aligned posture.

---

## Target shape (per design_workflows §2.1)

| Recipe / rule | Shared home (target) | Current copies |
| --- | --- | --- |
| Direct `core.llm` call + parse + `emit_direct_llm_usage` | one `core/reactive/` helper (the §2.1 "single LLM call" node) | stages.py:183; plan_check.py:394; team/handlers.py:175; tagger.py:41; transfer.py:767 |
| Supervisor block bar (threshold + citation gate) | `policy/semantic/verdict.py` (owner) | workflow/stages.py:255-302 (re-impl) |
| Lane resolution | call `resolve_supervisor_lane` | supervisor.py:806-812 (inlined :721-736) |
| Subprocess transport resolution | `resolve_subprocess_routing` chain | team/handlers.py:245 (ad-hoc registry-only) |
| Anchored resume-id UUID regex | one constant | queries.py:16; supervisor.py:40-42 |

---

## Phased plan

| Slice | Scope | Exit signal |
| --- | --- | --- |
| 1 | Extract the direct-LLM-call + emit recipe into a `core/reactive/` helper; repoint the tagger + plan_check first (lowest-risk, already have exact-token emission). | tagger + plan_check call the helper; single-emitter rule intact; throttle key unchanged |
| 2 | Repoint workflow checker stage + transfer curation; fold `ReviewerStage`'s block bar onto `verdict.py`. | workflow reviewer imports the block bar from `verdict.py`; a threshold-change test proves both move together |
| 3 | `run_supervisor_check` calls `resolve_supervisor_lane`; one UUID-regex constant. | no inlined lane body; `rg` for the UUID regex returns one definition |
| 4 | Team handler onto `resolve_subprocess_routing`; add the confidence/citation bar (Surfaced Defect); refresh the stale `core/reactive/proxy.py:4` docstring. | team supervisor routes via the shared chain and blocks only on high-confidence + cited |

Slice 4 folds in the two surfaced defects -- their fixes need regression tests regardless, and the routing migration is
the natural moment.

## Blast radius

- `policy/semantic/supervisor.py` (1324 LOC) and `policy/workflow/stages.py` are policy-hook hot paths -- run the policy
  integration path (real `claude -p`), not just unit, before finishing (testing_guidelines.md).
- The direct-LLM helper is imported by tagger/plan_check/workflow/team/transfer -- count `patch(...)` targets on each
  before repointing; the throttle-cache and emit seams are the fragile parts.

## What was verified vs. first-pass

- **First-pass, re-verify before cutting the seam (Medium):** all five findings ([48],[49],[50],[52],[54]). Their
  adversarial refuters were spend-capped. The design-doc authority (§2.1 shared-library table) is explicit, which is why
  the batch is credible; but confirm each per-site diff (especially that the block bars are byte-equivalent) before Slice
  2/3.

## Adversarial verification (to run before scheduling)

Refuter briefs to apply: (1) is any copy *deliberately* independent (different throttle semantics, different fail-open)?
(2) does the shared helper's blast radius across 5 hot-path sites exceed the benefit? (3) can the block-bar fold be
behavior-preserving given `checker_effort` is part of the throttle key? Resume the audit workflow
(`resumeFromRunId: wf_dfc2d14a-03c`) once spend resets to complete these.

## Risks

- **Fail-open + single-emitter are the failure modes.** A shared recipe that emits twice, or swallows differently, is a
  telemetry/enforcement regression. Pin both with tests before Slice 1.
- **The block bar is a policy-correctness surface.** Folding `ReviewerStage`'s copy onto `verdict.py` must not shift the
  confidence threshold or citation requirement -- characterization test first.
- **Team handler routing migration** changes how the team supervisor reaches its model; verify the executor model-pin no
  longer leaks (Surfaced Defect) as part of the same slice.

## Metric / falsifiable prediction

Prediction: a change to the block rule or the direct-LLM emission touches **1 helper, not 4-5 sites**; the team
supervisor stops being the routing-chain outlier. Confirm on the next supervisor-threshold PR and the next routing
change.

## Acceptance (per-slice)

Tick only when: (a) the recipe/rule lives in one home and callers delegate; (b) throttle key, fail-open posture, and
single-emitter behavior are pinned by tests and unchanged; (c) the policy integration path passes; (d) Slice 4's two
defect fixes carry regression tests.

## Closeout

(pending)
