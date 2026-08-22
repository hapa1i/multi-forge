# policy_shared_library_seam -- extract the reactive transport core and consolidate policy seams

**Lane**: `done/` -- completed and verified 2026-07-24 on branch `policy-shared-library-seam`; closeout is bundled with
the implementation for merge. The re-verified execution contract is [checklist.md](checklist.md). The card extracts the
common direct-LLM **transport core** while preserving five deliberately different parsing and telemetry contracts, then
consolidates the semantic/workflow block rule, lane resolution, UUID validation, and team-supervisor routing.

Slices are ordered: Slice 2 and Slice 4 consume the Slice-1 helper. Slices 1-3 are behavior-preserving. Slice 4 contains
the decided D7 team-policy change, the model-pin defect fix, and intentional D3 pre-dispatch routing/observability
changes.

**Origin**: full-codebase refactor audit, 2026-07-05 (`/refactor_audit whole repo --full`; area policy-pkg). The
original audit found the right duplication sites but overstated the shared emission seam and treated the team confidence
gate as an established defect. Re-verification on 2026-07-24 corrected both claims; the checklist records the evidence
and decisions.

**Type**: one refactor card with an explicit policy-change slice, staged in four ordered slices.

**References**: `docs/design_workflows.md` §1.2 (reactive node taxonomy and semantic supervisor bar), §2.1
(shared-library table to extend), and §3.5 (runners); `docs/design.md` §3.6.12 (normative subprocess routing);
`docs/design_runtime.md` §E (`core.llm`) and §G (routing details); `docs/board/impl_notes.md` (import boundaries,
supervisor launch controls, and single-emitter invariants).

---

## Why (the thesis)

Five sites repeat the same transport mechanics -- construct a `core.llm` client and `SyncAdapter`, conditionally attach
an exact-cost request id, time `.complete()`, and return its response:

- `core/reactive/tagger.py:41-117`
- `policy/semantic/plan_check.py:394-479`
- `policy/workflow/stages.py:183-238`
- `policy/team/handlers.py:163-221`
- `session/transfer.py:611-657`

Their parsers, status vocabularies, exception emission, session tagging, provider metadata, and upstream outcomes differ
by design. The honest seam is transport-only; the checklist's telemetry matrix is the preservation contract.

Adjacent drift remains worth fixing in the same ordered card:

- Workflow stages duplicate the semantic supervisor's confidence-plus-citation predicate.
- `run_supervisor_check` duplicates the two-line body of `resolve_supervisor_lane`.
- Two policy modules define the same anchored UUID regex.
- The team handler resolves explicit config locally, while `run_claude_session`/`build_claude_env` applies ambient proxy
  fallbacks later. Ambient destinations already work, but the handler cannot validate them or use their `base_url` for
  cost snapshots and model-pin scrubbing before committing the dispatch.
- The team prompt asks for confidence but the handler ignores it. D7 deliberately changes that team contract to a
  confidence-only gate with exit-0 diagnostic feedback; citation gating remains semantic-supervisor-specific.
- A proxied team supervisor inherits executor model-pin variables because it does not pass `unset_env_vars`.

---

## Non-goals / must-not-break

- **Do not centralize parsing or emission.** Each direct caller retains its telemetry row from the checklist.
- **No behavior change** to the five direct-call failure postures, the workflow/semantic block rule, throttle-cache
  keys, or lane-error fail-open handling.
- **Preserve single-emitter behavior** exactly; the transport helper never emits.
- **Preserve the checker-helper source of truth** (`policy/semantic/supervisor.py` holds the Click-free
  `CHECKER_PROVIDER_CHOICES`/`validate_checker_model`/`apply_checker_options` per impl_notes) -- extend it, do not fork
  it.
- **Fail-open remains mandatory.** D3 preserves the existing pre-dispatch failure for missing/corrupt named routes and
  moves reachability failures in front of dispatch, but still returns an allow outcome; D7 changes only whether a parsed
  divergent team verdict blocks.
- **Do not give the team supervisor semantic citation gating or `model="opus"`.** Its decided bar is confidence-only and
  its resumed cheap-proxy posture remains model-unpinned.

---

## Target shape

| Recipe / rule                                                                | Target owner                                                         | Current copies / outlier                                                           |
| ---------------------------------------------------------------------------- | -------------------------------------------------------------------- | ---------------------------------------------------------------------------------- |
| Direct `core.llm` transport (client, request-id gate, timing, `.complete()`) | new `core/reactive/llm_call.py`; add to design_workflows §2.1        | five sites listed above                                                            |
| Parsing, usage emission, and upstream outcomes                               | each call site                                                       | deliberately different; pinned by the telemetry matrix                             |
| Semantic/workflow confidence-plus-citation predicate                         | `policy/semantic/verdict.py`                                         | workflow `stages.py:255-302` reimplementation                                      |
| Team confidence-only gate                                                    | `policy/team/handlers.py`, reading the shared threshold at call time | confidence currently ignored                                                       |
| Lane resolution                                                              | `resolve_supervisor_lane`                                            | two-line inline copy in `run_supervisor_check`                                     |
| Subprocess routing                                                           | `resolve_subprocess_routing` before team dispatch                    | explicit config handled early; ambient routes resolved later by `build_claude_env` |
| Claude model-pin env names                                                   | `core/reactive/session_runner.py`                                    | semantic-supervisor private constant                                               |
| Anchored resume-id UUID regex                                                | `policy/queries.py` as `RESUME_ID_UUID_RE`                           | `queries.py:16`; `supervisor.py:40-42`                                             |

---

## Phased plan

| Slice | Scope                                                                                                                                    | Exit signal                                                      |
| ----- | ---------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------- |
| 1     | Add the provider-aware transport helper; repoint tagger + plan-check; add the §2.1 design row.                                           | both callers delegate; telemetry rows and throttle key unchanged |
| 2     | Repoint workflow stages + transfer; share the semantic/workflow block predicate.                                                         | transport delegates; threshold monkeypatch moves both consumers  |
| 3     | Delegate lane resolution; consolidate the UUID regex under `policy.queries` (the existing dependency direction).                         | one lane resolver and one tested regex definition                |
| 4     | Repoint team tagger; apply D7; resolve routing before dispatch; scrub proxied model pins; correct proxy docs; add team-wire integration. | D3 matrix, D7 wire, model-pin regression, and design sync pass   |

Slice 2 and Slice 4 depend on Slice 1. Each slice is shippable after its predecessors.

## Blast radius

- `policy/semantic/supervisor.py` and `policy/workflow/stages.py` are policy-hook hot paths.
- The direct-LLM helper is imported by tagger/plan_check/workflow/team/transfer -- count `patch(...)` targets on each
  before repointing; the throttle-cache and emit seams are the fragile parts.
- Team routing spans `handlers.py`, `session_runner.py`, and `env.py`. The D3 matrix distinguishes unchanged proxy
  destinations from new strict preflight, attribution, pin-scrub, usage, and lane-freeze timing.
- Run the deterministic Docker policy/supervisor paths plus the new team-hook fixture; the fixture must control both the
  cheap tagger response and harnessed `claude -p` verdict.

## Re-verification status

The five transport copies, telemetry divergences, workflow block-rule duplication, lane duplication, UUID duplication,
proxy importers, two-layer team routing, and model-pin leak were re-verified against `main` at `0435e561`. D7 was
resolved as a user policy decision. The checklist's telemetry and D3 matrices are the execution authorities.

## Risks

- A transport helper that catches exceptions or emits would silently change one or more telemetry rows.
- Provider overrides are load-bearing for plan-check client construction and exact-cost request-id gating.
- Strict routing validates named proxies before `on_dispatch`; present-but-unreachable named routes intentionally stop
  freezing lanes or producing dispatch usage events.
- D7 exit-0 feedback is diagnostic stderr visibility only; teammate delivery remains guaranteed only for exit 2.
- Moving model-pin names without testing every resolved source could leave ambient routes unfixed.

## Metric / falsifiable prediction

Prediction: a transport change (client construction, provider-aware request-id gate, timing, `.complete()`) touches one
helper instead of five sites; semantic/workflow threshold changes touch one predicate; the team supervisor stops being
an early-routing outlier. Emission changes intentionally remain per-site.

## Acceptance (per-slice)

Tick a slice only when its checklist assertions and characterization tests pass. Closeout additionally requires unit,
regression, deterministic policy/supervisor integration, and the new end-to-end team-hook wire test.

## Closeout

See [checklist.md §Closeout](checklist.md#closeout).
