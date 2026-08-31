# Refresh the walkthrough for v1.0.0

**Lane**: `proposed/` -- candidate release-blocking end-user education work for v1.0.0. Execute after
[`refresh_release_qa_for_1_0`](../../doing/refresh_release_qa_for_1_0/card.md) defines which contracts belong to
automated, clean-wheel, human, and exploratory release evidence.

**References**:

- [Interactive manual testing design](../../../design_installation.md#d-interactive-manual-testing)
- [Interactive manual testing guidelines](../../../developer/testing_guidelines.md#interactive-manual-testing-smoke-test-smoke-test-walkthrough-qa)
- [Session launch and continuity design](../../../design_sessions.md#39-session-resume-context-management)
- [Session end-user guide](../../../end-user/session.md)
- [`harden_walkthrough_sandbox_provenance`](../../done/harden_walkthrough_sandbox_provenance/card.md)
- [`lock_walkthrough_state_parity`](../../done/lock_walkthrough_state_parity/card.md)
- [`model_first_session_routing`](../../done/model_first_session_routing/card.md)

## Goal

Make `/walkthrough` a short, accurate Day 1 tour of managed sessions, model/runtime choice, session continuity, and
operator evidence. The default journey should teach Forge's mental model in 25-30 minutes; it must not double as an
installer schema regression suite.

## Verified Baseline

Rechecked on `main` at `000cfc9c` on 2026-08-25:

- The walkthrough has 45 steps and 108 assertions. Its checklist content has not changed since the v0.9.4 release;
  metadata still says `last-updated: 2026-07-23` and `aligned-with: v0.1.0`.
- Step 6.3 creates `walkthrough-demo` with `forge session start ... --no-launch`.
- Step 7.1 launches `forge claude start --proxy ...`, which is a bare, sessionless launcher that clears `FORGE_SESSION`.
  It cannot satisfy later claims that Session B shows `walkthrough-demo`, writes that session's transcript, or sets its
  `confirmed.claude_session_id`.
- Step 7.1 says hooks and direct commands are active because of the local install. Runtime hooks are user-scoped; local
  scope supplies project assets and the status line.
- The tour contains no `session resume`, `session transfer`, `telemetry costs`, `telemetry activity`, model-first
  selection, or incognito journey.
- Codex appears only in a fake-binary extension-package exercise. The tour neither explains managed versus bare Codex
  launch nor shows the preflight/cross-runtime path marketed by the current README.
- The default journey spends substantial space on exact package inventories, legacy hook migration, passport envelope
  manipulation, and optional sidecar mechanics before teaching session continuity.
- `setup-test-repo.sh` and `run-in-repo.sh` deliberately isolate `FORGE_HOME`, `CLAUDE_HOME`, and `CODEX_HOME`, preserve
  real `HOME` for native auth/tool reachability, and enforce marker plus canonical-path safety gates.

## Proposed Decisions

1. **Repair the managed-session story first.** Resume the never-launched `walkthrough-demo` through
   `forge session resume walkthrough-demo`; never use a bare launcher while claiming managed state.
2. **Teach concepts, not inventories.** The walkthrough explains the smallest successful user journey. Exact package
   counts, malformed state, migrations, ownership ledgers, and security matrices remain QA/test responsibilities.
3. **Keep the v1.0.0 frontend Claude-hosted.** Do not duplicate the checklist for Codex before release. Teach Codex as
   an optional managed runtime and record a post-1.0 follow-up for a thin Codex-facing frontend over shared scenarios.
4. **Default path first, advanced chapters optional.** The default tour uses one managed Claude session and one
   continuity child. Sidecar, legacy migration, passport internals, supervisor wiring, and live Codex are explicit
   opt-ins.
5. **Bound the tour.** Target 25-30 minutes, at most eight human checkpoints, and at most three paid model sessions in
   the default path. Optional Codex or sidecar journeys report their additional cost/time separately.
6. **Preserve the sandbox boundary.** Every mutating command continues through `run-in-repo.sh` or an equally strict
   proven boundary; no educational simplification may touch real extension targets or Forge state.

## Default Journey

The implemented order should follow the user's questions rather than the repository's component inventory:

01. **Create the sandbox and orient the user.** Show the test root and isolated homes, then explain what remains real
    (the installed `forge` executable and runtime authentication).
02. **Check and enable Forge.** Use `extension doctor`, a user-scope runtime-hook enable, and project setup. Summarize
    resulting ownership without enumerating every installed package.
03. **Explain managed versus bare launch.** Name what managed sessions add: manifest, lifecycle hooks, artifacts,
    continuity, search, and telemetry. Contrast `forge claude start`/`forge codex start` as sessionless proxy launchers.
04. **Choose a model or runtime.** Start the managed Claude fixture through a current model-first or explicit route,
    then inspect `forge session model show` so the user sees intent versus committed route evidence.
05. **Use one live managed session.** Reattach `walkthrough-demo`, inspect the rendered status line, invoke one `%`
    command, and trigger one visible policy decision before exiting cleanly.
06. **Inspect what happened.** Show the session manifest at a user-facing level, transcript artifact, search result,
    `forge telemetry activity`, and `forge telemetry costs show`. Do not teach raw internal schemas as normal operation.
07. **Continue the work.** Create one fresh child, show the generated context through `forge session transfer show`, and
    ask one grounded question that proves the child received parent context.
08. **Show ephemerality.** Run a short incognito example or a deterministic equivalent that proves the session is
    removed on exit without adding another long conversation.
09. **Orient Codex users.** Explain `forge runtime preflight codex`, managed `session start --runtime codex`, and bare
    `forge codex start`. If an explicit Codex option is selected and readiness passes, run one bounded managed turn;
    otherwise show actionable readiness output and do not fake successful runtime validation.
10. **Clean up.** Remove only walkthrough-owned sessions, proxies, indexes, installations, and repository state, then
    prove the real-system snapshot is unchanged.

## Advanced Optional Chapters

Keep these discoverable but outside the default time budget:

- legacy hook migration preview/apply;
- exact Claude/Codex package inventory and sync persistence;
- memory passport authoring and legacy-envelope upgrade;
- sidecar start/shell/cleanup;
- supervisor wiring and workflow fan-out; and
- a real Claude -> Codex cross-runtime handoff when Codex readiness is available.

An optional chapter must state its prerequisites, extra paid calls, cleanup owner, and whether failure changes the
default walkthrough verdict.

## Scope

### 1. Correct the existing journey

- Replace the sessionless Session B launch with managed resume and verify the manifest before proceeding.
- Correct user/local hook, status-line, skill, and command ownership language.
- Audit every later claim against the artifacts actually produced by its command; remove hand-waved success paths.
- Retag checklist version, last-updated date, alignment target, and assertion count after the content settles.

### 2. Reduce maintainer QA inside the tour

- Replace exact portable-skill directory diffs with a concise status/health result and link to the advanced package
  chapter.
- Remove legacy migration from the default path unless the setup fixture deliberately represents an upgrading user.
- Replace the long passport-envelope validator with a short `track/show` educational example or move it entirely to the
  advanced chapter.
- Keep the existing policy and search story only where each teaches a visible user outcome from the managed session.
- Keep sidecar opt-in and avoid loading its prerequisites or assertions during a default run.

### 3. Add the missing Day 1 concepts

- Model-first session selection and `session model show` evidence.
- One `resume --fresh` continuity loop plus `session transfer show`.
- Cost and per-session activity inspection after a real request.
- Incognito lifecycle and cleanup.
- Managed versus bare Claude/Codex semantics and Codex readiness guidance.
- The difference between local proxy health and an upstream smoke test.

### 4. Preserve packaging and sandbox behavior

- Run the installed walkthrough from a clean wheel, not only the checkout copy.
- Preserve the six `run-in-repo.sh` safety gates, marker checks, symlink/canonical-path denial, and real-system
  snapshot.
- Keep both state scripts parity-locked if parsing or annotation behavior changes.
- Ensure cleanup remains safe after interruption and on a resumed walkthrough state file.

### 5. Synchronize user-facing documentation

Update `README.md`, `docs/end-user/README.md`, `docs/end-user/session.md`, `docs/end-user/transfer.md`, and
`docs/end-user/skills.md` only where the refreshed journey exposes stale Day 1 wording or runtime distinctions. Update
manual-testing design/guidelines when default versus optional walkthrough semantics change.

## Out of Scope

- A second independent Codex checklist or copied state machine.
- Exhaustive extension lifecycle, malformed-state, proxy-template, telemetry-schema, or strategy-matrix testing.
- Replacing `/smoke-test` / `$smoke-test`; the walkthrough remains stateful education, not a health probe.
- Requiring Codex, Docker, sidecar, or more than one provider for the default walkthrough to pass.
- Changing product behavior to preserve a walkthrough command that contradicts the managed-session contract.

## Risks

- **Teaching the wrong launcher**: a bare process can look healthy while every later managed-session claim is false.
- **Tour-to-QA regression**: adding every newly shipped feature recreates the current duration and maintenance problem.
- **Sandbox escape**: runtime/auth convenience can accidentally point extension or state writes at the user's real home.
- **Paid-run variance**: multiple context questions or workflow calls can make a Day 1 tour slow and nondeterministic.
- **Codex false confidence**: a fake binary proves package selection only; it must not be described as runtime
  readiness.
- **Cleanup drift**: new child/incognito/Codex state can survive unless every optional branch has a named cleanup path.

## Acceptance Tests

| Test                       | Fixture                                                            | Assertion                                                                                             | Test File                                                                        |
| -------------------------- | ------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------- |
| Managed Session B          | `walkthrough-demo` created with `--no-launch`                      | resume launches it in place; status and manifest resolve that name; confirmed runtime id is populated | walkthrough checklist plus session lifecycle integration                         |
| Hook ownership explanation | user and project/local installs in isolated homes                  | runtime hooks exist only at user scope; project/local owns the status line and project assets         | installer tests plus walkthrough assertions                                      |
| Transcript and search      | clean exit from managed Session B                                  | transcript artifact belongs to `walkthrough-demo`; search indexes and finds the seeded policy prompt  | walkthrough full-run evidence                                                    |
| Model route inspection     | managed session with explicit supported model/route                | `session model show` names intent and supported committed evidence without conflating live fallback   | session-routing integration plus walkthrough assertion                           |
| Fresh continuity           | exited parent with transcript and one child                        | transfer show exposes generated context; child answers one parent-grounded question                   | session lifecycle integration plus guided checkpoint                             |
| Cost/activity orientation  | one real managed request                                           | activity reports the session; costs show reported or honestly unavailable evidence                    | telemetry tests plus walkthrough output                                          |
| Incognito cleanup          | short incognito launch and clean exit                              | session manifest/index entry is absent afterward                                                      | session CLI/integration plus walkthrough assertion                               |
| Codex readiness branch     | Codex ready and not-ready fixtures                                 | ready path may run one managed turn; unavailable path is actionable and never reports fake success    | `tests/integration/core/test_codex_session_start.py` plus checklist branch       |
| Sandbox provenance         | malicious env, missing marker, symlink alias, valid generated repo | unsafe targets execute nothing; valid sandbox remains functional                                      | `tests/regression/test_bug_o036_walkthrough_sandbox_provenance.py`               |
| Interrupted cleanup        | owned and foreign proxies plus stale walkthrough state             | cleanup removes owned state, preserves foreign resources, and keeps diagnostic evidence               | existing walkthrough regressions plus focused additions                          |
| Clean-wheel package        | wheel-installed walkthrough                                        | scripts/resources resolve package-locally and the full default run does not import the checkout       | installer Docker lifecycle or new sibling                                        |
| State parity               | QA and walkthrough state copies                                    | any parser change remains behaviorally and byte-parity guarded                                        | `tests/src/skills/test_walkthrough_state.py`, `test_walkthrough_state_parity.py` |

## Verification Requirements

- Focused walkthrough-state, sandbox-provenance, cleanup, report, installer, and runtime-skill tests.
- Targeted session, hook, telemetry, routing, search, and optional Codex integration tests for changed paths.
- A clean-wheel `--setup-only` run followed by one complete default walkthrough with saved report/evidence.
- One interruption/resume exercise and one cleanup rerun.
- Confirm measured default duration, human checkpoint count, and paid-run count satisfy the ratified budget.
- `make test-unit`, `make test-regression`, relevant targeted integration commands, `uv build`,
  `scripts/test-wheel-runtime.sh`, `make pre-commit`, Markdown link checks, file-size checks, and `git diff --check`.

## Open Questions

- Which model-first example is cheap and stable enough for Day 1 without making OpenRouter mandatory? Prefer a direct
  Claude route when it still demonstrates useful route evidence.
- Does incognito earn a paid default launch, or should it be a short optional chapter after continuity and cost? Keep it
  only if the measured tour stays within budget.
- Should the optional Codex path use one headless `--task` turn or an interactive TUI? Headless is easier to bound and
  verify; interactive better demonstrates the user experience but adds another human window.
- After v1.0.0, should the shared walkthrough driver remain skill-owned or move behind a small Forge CLI surface before
  adding a Codex-facing frontend?
