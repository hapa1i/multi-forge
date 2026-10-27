# Validate derived-session overrides before creating a child

**Lane:** `proposed/` -- implementation follow-up; not started.

**Origin:** The maintainer selected the
[derived-session inheritance decision](../../doing/decide_derived_session_override_inheritance/decision.md) on
2026-10-27. [Current evidence](../../doing/decide_derived_session_override_inheritance/evidence.md) was captured on
`32df0219`. The completed maintenance epic is provenance, not an active coordinator.

## Problem

Relaunch copies generic overrides without fully validating them before child publication. A parent carrying
`verification.bypass: "bad"` can produce a persisted child whose effective configuration cannot be decoded. A legacy
`launch.runtime: codex` override over Claude intent produces a child whose effective runtime disagrees with immutable
dispatch identity. Fork/fresh reject the bad scalar indirectly through memory inheritance but omit the stale runtime
override. Unknown paths already fail strict manifest reads.

Make parent validation explicit before publication, new worktree creation and transfer inference. Preserve the selected
layer contract: fork/fresh omit generic overrides and materialize effective memory `auto_update`; relaunch copies valid
overrides without baking them into baseline. Ordinary reattach remains a separate operation on the same session.

## Scope and constraints

- Share structural validation across the three manager derivation paths, including native/transfer/rewind callers.
  Reject malformed effective values and stored overrides of lifecycle-owned fields with an exact path and applicable
  recovery. Protect runtime, resolved route, authority, consumer lanes and native supervisor source identity.
- Check explicit paths and nested object contents. Preserve permitted nullable parents and scalar/list/null override
  semantics; do not turn an omitted immutable descendant into an explicit override.
- Keep strict unknown-key/container/version refusal and the existing allowlisted read migrations. Do not silently
  sanitize a parent, rewrite it on inspection or add a general manifest migration. Readable invalid values can use
  supported keyed reset or `reset --all`; a manifest rejected by strict decoding requires explicit repair/restoration.
- Preserve existing supervisor transition/admission rules. Structural validation must not add source/auth reads,
  credential resolution or reviewer preflight for an unrelated override. Disabled relaunch policy must remain usable
  with an unavailable reviewer; active inherited policy still follows existing admission.
- Preserve selected raw intent, all four requested consumer lanes, memory flags, advisory-only authority inheritance,
  explicit child choices and parent/child independence. Do not copy frozen bindings, degradation state, review ownership
  or spent allowances. Do not use the entire effective parent as the child baseline.
- Keep existing locking, cleanup leases and rollback boundaries; a rejected derivation must publish no child and leave
  parent bytes, worktrees and transfer artifacts unchanged. This is not a new concurrent snapshot protocol.
- Update the session design's validation limitation when the guard ships. Current layer/reset documentation is owned by
  the decision package and must remain accurate.

## Acceptance

Use `tests.fixtures.session_state.publish_session` for coherent parent fixtures. Parameterize manager cases across fork,
fresh resume and relaunch; use real persisted manifests and the shared reset operation. Introduce malformed overrides
only after valid fixture publication and explain the deliberately violated invariant.

| Case                   | Fixture                                                                 | Required assertion                                                 |
| ---------------------- | ----------------------------------------------------------------------- | ------------------------------------------------------------------ |
| Policy both ways       | Baseline on/live off; baseline off/live on                              | Fork/fresh use baseline; relaunch keeps override                   |
| Suspension and bypass  | Supervisor suspended; verification bypass                               | Same layer rule; reset restores child baseline                     |
| Memory exception       | Effective writer config differs from intent                             | Fork/fresh materialize only `auto_update`; relaunch retains layers |
| Explicit memory flags  | Parent on/off/null, custom writer settings                              | On retains settings; off stores disabled defaults                  |
| Nullable sections      | `memory: null`, `policy: null`, `launch: null`                          | Valid clears follow the selected matrix                            |
| Lanes                  | Four explicit intent slots, frozen parent bindings                      | Copy intent only; child confirmed bindings absent                  |
| Cleared lane intent    | Cleared request with a still-frozen parent lane                         | Child uses no inherited frozen binding                             |
| Invalid types          | Wrong scalar; scalar in object field; bad nested value                  | Refuse before child/worktree/transfer writes                       |
| Forbidden legacy keys  | Direct/nested runtime, route, authority, lanes, native source           | Refuse with offending path; retain parent bytes                    |
| Strict legacy reads    | Unknown key/container/version; allowed migration controls               | Preserve refusal and no-write migration behavior                   |
| Reset and independence | Valid relaunch/fork/fresh child, then child and parent edits            | Correct reset baseline; no cross-session mutation                  |
| Supervisor recovery    | Disabled native policy, unavailable reviewer                            | Relaunch succeeds without reviewer preflight                       |
| CLI dispatch           | Inactive reattach, active `--force`, native fork, fresh native/transfer | Select the intended derivation rule                                |
| Refusal effects        | Worktree/transfer-producing paths with invalid parent                   | No new checkout, child, snapshot or inference                      |

Extend `tests/src/session/test_memory_inheritance.py`, `test_authority_inheritance.py` and `test_consumer_lanes.py`
where they own existing rules. Add `tests/regression/test_bug_derived_session_override_validation.py` for the reproduced
publication/runtime gaps and manager matrix. Keep CLI assertions in `tests/src/cli/test_session_resume.py` and
`test_session_fork.py`; exercise persisted child behavior through Docker-backed
`tests/src/session/test_manager_integration.py` using the standard targeted integration runner.

## Verification and boundaries

Run focused tests, aggregate unit/regression, full pre-commit and relevant Docker lifecycle checks. No live inference is
needed to prove these configuration rules. Explicitly cover empty overrides and valid v2-v5 manifests so the guard does
not break normal sidecar-compatible writes. Do not broaden Codex source bridging, proxy routing, memory discovery,
consumer dispatch or ordinary reattach semantics. Record separate follow-ups if those boundaries reveal unrelated bugs.
