# Derived-session override validation checklist

**Current focus:** [PR #294](https://github.com/hapa1i/multi-forge/pull/294) review and CI. Parent validation now
precedes derivation side effects while preserving the selected
[inheritance contract](../../done/decide_derived_session_override_inheritance/decision.md).

**Execution:** `codex/derived-session-override-validation`, based on `04c9620d` (`main`), accepted 2026-10-30.

## Implementation

- [x] Confirm the relaunch publication gap, late fork/fresh validation and CLI route-start boundary against current
  code.
- [x] Move the selected proposal to `doing/` and update inbound links; no active epic coordinates this card.
- [x] Add a pure shared structural guard for effective types and explicitly stored lifecycle-owned fields, with exact
  offending paths. Nullable parents and free-form configuration dictionaries remain valid.
- [x] Suggest keyed reset or reset-all only when the existing supervisor snapshot/transition checks admit it; otherwise
  give applicable supervisor remove/reconfigure or manifest repair/restoration guidance.
- [x] Guard fork planning and fresh/active-force resume before route realization, process startup or transfer work.
- [x] Guard all three manager derivations before legacy identity migration and again within the existing parent lease,
  before replacement deletion, worktree creation, inference or child publication.
- [x] Preserve native-supervisor derivation readiness and launch-owned sidecar/Claude readiness boundaries.

## Acceptance evidence

Tests publish coherent parents before deliberately introducing invalid persisted overrides. Existing inheritance tests
remain the owners of their respective rules; the regression matrix exercises persisted children and shared reset.

| Fixture                                                                                     | Required assertion                                                                        | Test owner                                                                     |
| ------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------ |
| Wrong scalar/object/nested override; explicit runtime/route/authority/lanes/native source   | Exact path; no child or durable parent mutation across fork/fresh/relaunch                | `test_derived_overrides.py`, `test_bug_derived_session_override_validation.py` |
| Native/frozen supervisor identity or malformed timeout; absent baseline supervisor          | Only recovery accepted by shared reset rules is offered; no reviewer/auth preflight       | `test_derived_overrides.py`                                                    |
| Policy baseline/live values both ways, both supervisor-off commands, verification overrides | Fork/fresh selected baseline; relaunch copied layers; reset preserves baseline suspension | `test_bug_derived_session_override_validation.py`                              |
| Effective memory settings, explicit on/off/null; nullable policy/launch                     | Only effective auto-update materialized for fork/fresh; relaunch retains layers           | `test_memory_inheritance.py`, regression matrix                                |
| Four lane intents, cleared request with frozen parent; authority                            | Child inherits intent and permitted authority only; no frozen bindings/review ownership   | `test_consumer_lanes.py`, `test_authority_inheritance.py`                      |
| Child/parent edits, child with no own plan                                                  | Independent configuration; plan remains live against immediate parent                     | Regression matrix                                                              |
| Empty overrides, valid v2-v5, allowlisted read migrations; strict legacy failures           | Valid derivation remains available; reads do not rewrite invalid/legacy parent manifests  | Regression matrix                                                              |
| Invalid fresh ai-curated, forced fork replacement, explicit route flags                     | No deletion, checkout, child, transfer, inference or process startup                      | CLI and regression tests                                                       |
| Inactive/never-launched resume, active force, native/transfer/rewind derivation             | Correct operation selected; ordinary reattach unchanged                                   | CLI tests                                                                      |
| Persisted parent and child in Docker                                                        | Valid layer/reset behavior and invalid-parent refusal hold with real filesystem/git       | `test_manager_integration.py`                                                  |

## Verification and documentation

- [x] Focused structural, manager and CLI tests pass; record reproduced failures and resulting coverage below.
- [x] Targeted Docker lifecycle tests pass through `scripts/test-integration.sh`; no live inference is required.
- [x] Aggregate `make test-unit` and `make test-regression` pass on the integrated branch.
- [x] Replace the session design validation limitation and document user-facing refusal/recovery.
- [x] Full `make pre-commit`, board/link checks and independent diff review pass.
- [x] Open the implementation PR with recorded local acceptance evidence; require green CI before merge.

### Recorded local evidence (2026-10-30)

These results cover implementation head `252d20c2`; review follow-up verification is recorded below.

Before the fix, a coherently published parent edited to contain `verification.bypass: "bad"` produced a persisted
relaunch child that could not decode; fork/fresh failed late with key `unknown`. A stored `launch.runtime: codex`
override was silently dropped by fork/fresh and copied by relaunch over Claude dispatch intent. Both reproductions now
refuse before writes, with the precise override path.

- The final structural guard and persisted regression selection: **210 passed** in 15.80 seconds (**42** guard cases,
  **168** regression cases). These execute real publication, reset and supervisor-remove operations on isolated
  persisted state. All four lane slots and cleared requests are covered in the persisted matrix; no duplicate
  lane-helper tests were needed.
- The focused tests include constructor-error path narrowing, nullable parents, native/frozen identity recovery and
  malformed whole-supervisor values. The final container checks reproduced a decoder `AttributeError` during recovery;
  derivation now handles it at the snapshot boundary and offers executable removal or explicit manifest repair.
- CLI cases cover route/process/transfer refusal, ordinary versus child dispatch and stderr-only repair/restoration for
  native, transfer and rewind manager reread failures. Memory, authority and lane owner tests remain in the aggregate
  gates.
- `make test-unit`: **11,573 passed** in 90.12 seconds on the final recovery fix.
- `make test-regression`: **2,428 passed** in 109.45 seconds on the final recovery fix.
- `make pre-commit`: **all hooks passed**, including mypy, Pyright, file limits and Markdown links. The initial run
  normalized test formatting and found a fixture dictionary annotation; both were corrected before the final pass.
- Targeted Docker command below: **54 passed** in 50.96 seconds on the final recovery fix, including twelve new
  persisted-child cases. Credentials were removed from the invocation; the runner warned that Gemini was unavailable,
  and these tests needed no live LLM. The first invocation selected an incorrect test filename and collected nothing;
  the corrected invocation passed.

```bash
env -u GEMINI_API_KEY -u OPENROUTER_API_KEY -u ANTHROPIC_API_KEY -u OPENAI_API_KEY \
  PYTHON_DOTENV_DISABLED=1 ./scripts/test-integration.sh \
  tests/src/session/test_manager_integration.py \
  tests/src/session/test_resume_integration.py \
  tests/integration/cli/test_session_resume_proxy_integration.py -q
```

Independent seam review found no remaining ordering, dispatch, readiness or lease issue. Broader corrupt-state recovery,
including the shared reset command's existing malformed-supervisor traceback, remains outside this card and is recorded
in [a separate proposal](../../proposed/scoped_corrupt_state_recovery/card.md). Raw local logs are temporary; this
checklist retains their result summary and the checked-in tests reproduce the acceptance cases.

### PR review follow-up

- [x] Reject native-source authoring through direct/descendant keys, enclosing objects and wildcards, including null or
  identical values. Preserve nullable parent clears and identity-checked legacy keyed reset. Focused override, native
  supervisor CLI and persisted authoring checks: **192 passed**.
- [x] Warn that both reset-all recovery paths also clear unrelated valid live overrides; verify actual reset removes
  temporary policy and verification settings.
- [x] Use a neutral manifest error heading before a corrupt record can establish whether force-resume derives or
  reconnects; cover never-launched and confirmed-but-inactive parents. Focused guard, resume and persisted regression
  selection: **313 passed**.
- [x] Correct current board status while preserving the historical decision's initially unstarted follow-up.
- [x] Verify the integrated review fixes with aggregate unit/regression, targeted Docker and full hooks: **11,596 unit**
  passed in 103.69 seconds; **2,456 regression** passed in 123.47 seconds; **64 Docker** passed in 63.96 seconds; all
  hooks passed. Docker used the same no-live-inference command above, including ten new persisted CLI cases for native
  source authoring and nullable clears. Final-head CI is the remaining live review gate on PR #294 and must pass before
  merge.

## Closeout after merge

- [ ] Confirm merged commit and required checks, then record final verification and completed-work change-log entry.
- [ ] Move this card to `done/` and repoint inbound links; verify design/end-user docs match shipped behavior.

No design decision is blocked. Ordinary reattach, Codex bridging, routing policy and concurrent snapshot guarantees are
outside this card.
