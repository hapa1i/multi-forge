# Refresh the walkthrough for v1.0.0

**Lane**: `doing/` -- accepted on 2026-09-01 and activated on branch `test/refresh-walkthrough-for-1-0` after
[`refresh_release_qa_for_1_0`](../../done/refresh_release_qa_for_1_0/card.md) established the automated, clean-wheel,
human, and exploratory release-evidence boundaries.

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

Rechecked on `main` at `7c6847dd` on 2026-09-01:

- The parser reports 14 sections, 45 steps, and 108 assertions: 33 `auto` and 12 `human:guided`. Excluding the three
  sidecar-only checkpoints still leaves nine human checkpoints in the default run, above the proposed cap of eight.
- Apart from PR #247 correcting the standalone selector from `/forge:walkthrough` to `/walkthrough`, the educational
  checklist has not changed since v0.9.4. Metadata still says `last-updated: 2026-07-23` and `aligned-with: v0.1.0`.
- The driver accepts only `--setup-only`, `--reset`, `--report`, and `--sidecar`, and always initializes progress with
  `--force`. Although the shared state engine already supports validated `--from` resume, the walkthrough cannot use it.
- Step 6.3 creates `walkthrough-demo` with `forge session start ... --no-launch`, including a pre-seeded Claude UUID but
  no hook confirmation, transcript evidence, or committed route.
- Step 7.1 launches `forge claude start --proxy ...`, which is a bare, sessionless launcher that clears `FORGE_SESSION`.
  It cannot satisfy later claims that Session B shows `walkthrough-demo`, hook-confirms that session, or writes its
  transcript; the already-populated UUID cannot supply that missing evidence.
- Step 7.1 says hooks and direct commands are active because of the local install. Runtime hooks are user-scoped; local
  scope supplies project assets and the status line.
- The tour contains no `session resume`, `session transfer`, `telemetry costs`, `telemetry activity`, model-first
  selection, or incognito journey.
- Codex appears only in a fake-binary extension-package exercise. The tour neither explains managed versus bare Codex
  launch nor shows the preflight/cross-runtime path marketed by the current README.
- The default journey spends substantial space on exact package inventories, legacy hook migration, passport envelope
  manipulation, and optional sidecar mechanics before teaching session continuity.
- `setup-test-repo.sh` and `run-in-repo.sh` deliberately isolate `FORGE_HOME`, `CLAUDE_HOME`, and `CODEX_HOME`, preserve
  real `HOME` for installed-tool and Claude-auth reachability, and enforce marker plus canonical-path safety gates.
  Native Codex stored auth is therefore absent unless the user explicitly copies one named auth file into the sandbox.

## Accepted Decisions

1. **Repair the managed-session story first.** Resume the never-launched `walkthrough-demo` through
   `forge session resume walkthrough-demo`; never use a bare launcher while claiming managed state. Before resume, model
   inspection must report durable intent with no committed route; committed evidence arrives only during resume.
2. **Teach concepts, not inventories.** The walkthrough explains the smallest successful user journey. Exact package
   counts, malformed state, migrations, ownership ledgers, and security matrices remain QA/test responsibilities.
3. **Keep the v1.0.0 frontend Claude-hosted.** Do not duplicate the checklist for Codex before release. Teach Codex as
   an optional managed runtime using one headless initial-message turn and record a post-1.0 follow-up for a thin
   Codex-facing frontend over shared scenarios. Native stored auth is never imported implicitly; the optional branch may
   use an inherited key/token or one explicitly named auth file copied into isolated `CODEX_HOME`.
4. **Default path first, advanced chapters optional.** The default tour uses one managed Claude session and one
   continuity child. Sidecar, legacy migration, passport internals, supervisor wiring, and live Codex are explicit
   opt-ins.
5. **Bound the tour.** Target 25-30 minutes, at most eight human checkpoints, and at most three paid operations in the
   default path. Optional Codex or sidecar journeys report their additional cost/time separately.
6. **Preserve the sandbox boundary.** Every mutating command continues through `run-in-repo.sh` or an equally strict
   proven boundary; no educational simplification may touch real extension targets or Forge state. Before a guided
   Terminal uses bare `forge`, it verifies the walkthrough marker and isolated home variables in that shell.
7. **Keep ownership and selection distinct.** Optional section-12 steps use driver-owned `option: codex` or
   `option: sidecar` modifiers over the existing generic annotation parser. Automated owners live in the journey map;
   the walkthrough does not reuse QA's evidence-selection lanes for a different meaning.

## Default Journey

The implemented order should follow the user's questions rather than the repository's component inventory:

01. **Create the sandbox and orient the user.** Show the test root and isolated homes, then explain what remains real
    (the installed `forge` executable and runtime authentication).
02. **Check and enable Forge.** Use `extension doctor`, a user-scope runtime-hook enable, and project setup. Summarize
    resulting ownership without enumerating every installed package.
03. **Explain managed versus bare launch.** Name what managed sessions add: manifest, lifecycle hooks, artifacts,
    continuity, search, and telemetry. Contrast `forge claude start`/`forge codex start` as sessionless proxy launchers,
    and display—but do not execute—the difference between local proxy health and an upstream smoke test.
04. **Choose a model or runtime.** Create the direct Claude fixture with a model alias and `--no-launch`, then inspect
    `forge session model show`: the alias is canonicalized, direct intent is durable, and committed route evidence is
    honestly absent before launch.
05. **Use one live managed session.** Launch `walkthrough-demo` through managed resume, inspect the rendered status
    line, SessionStart confirmation and now-committed direct route, invoke the two read-only `%` orientation commands,
    and trigger one visible policy decision before exiting cleanly. A pre-seeded conversation id alone never counts as
    launch proof.
06. **Inspect what happened.** Show the session manifest at a user-facing level, transcript artifact, search result,
    `forge telemetry activity`, and `forge telemetry costs show`. The policy outcome should be visible, while an empty
    or sparse model-calls pane and absent direct-session proxy cost are taught as honest telemetry boundaries. Do not
    teach raw internal schemas as normal operation.
07. **Continue the work.** Create one fresh child, show the generated context through `forge session transfer show`, and
    ask one grounded question that proves the child received parent context.
08. **Show ephemerality.** Run a short incognito example or a deterministic equivalent that proves the session is
    removed on exit without adding another long conversation.
09. **Orient Codex users.** Explain `forge runtime preflight codex`, managed `session start --runtime codex`, and bare
    `forge codex start`. If `--codex` is selected, accept environment auth or an explicit `--codex-auth` file, then run
    one bounded managed turn with `--context-delivery initial-message` when readiness passes. Hook enrollment is a
    separate capability, not a blocker for this path; unavailable readiness remains actionable and never becomes fake
    success.
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
- A display-only explanation of local proxy health versus a credentialed, potentially paid upstream smoke test.

### 4. Preserve packaging and sandbox behavior

- Run the installed walkthrough from a clean wheel, not only the checkout copy.
- Preserve the six `run-in-repo.sh` safety gates, marker checks, symlink/canonical-path denial, and real-system
  snapshot.
- Permit Codex stored-auth ingress only through one explicit regular-file path copied into isolated `CODEX_HOME`; keep
  its source path, bytes, and credential values out of progress and report artifacts.
- Keep both state scripts parity-locked if parsing or annotation behavior changes.
- Ensure cleanup remains safe after interruption and on a resumed walkthrough state file.

### 5. Synchronize user-facing documentation

Update `README.md`, `docs/end-user/README.md`, `docs/end-user/manual_testing.md`, `docs/end-user/session.md`,
`docs/end-user/transfer.md`, `docs/end-user/model_selection.md`, and `docs/end-user/skills.md` only where the refreshed
journey exposes stale Day 1 wording or runtime distinctions. Update `docs/design_installation.md` and
`docs/developer/testing_guidelines.md` when default versus optional walkthrough semantics change.

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
- **Codex credential leakage**: implicit native-store reuse or report capture could violate the sandbox while appearing
  convenient; only explicit single-file ingress is allowed, and its contents never become evidence.
- **Hook/readiness conflation**: plain Codex readiness does not prove trust enrollment, and initial-message delivery
  does not require it; the walkthrough must not make either false claim.
- **Cleanup drift**: new child/incognito/Codex state can survive unless every optional branch has a named cleanup path.

## Acceptance Tests

| Test                       | Fixture                                                            | Assertion                                                                                            | Test File                                                                        |
| -------------------------- | ------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------- |
| Managed Session B          | `walkthrough-demo` created with `--no-launch`                      | resume launches it in place; status, SessionStart confirmation, and transcript resolve that name     | walkthrough checklist plus session lifecycle integration                         |
| Hook ownership explanation | user and project/local installs in isolated homes                  | runtime hooks exist only at user scope; project/local owns the status line and project assets        | installer tests plus walkthrough assertions                                      |
| Transcript and search      | clean exit from managed Session B                                  | transcript artifact belongs to `walkthrough-demo`; search indexes and finds the seeded policy prompt | walkthrough full-run evidence                                                    |
| Model route inspection     | canonicalized direct model intent before and after managed resume  | pre-launch commitment is null; post-resume evidence is supported and direct                          | session-routing integration plus walkthrough assertion                           |
| Fresh continuity           | exited parent with transcript and one child                        | transfer show exposes generated context; child answers one parent-grounded question                  | session lifecycle integration plus guided checkpoint                             |
| Cost/activity orientation  | one real managed policy request                                    | policy outcome appears; model-call and direct-cost gaps remain explicit rather than fabricated       | telemetry tests plus walkthrough output                                          |
| Incognito cleanup          | short incognito launch and clean exit                              | session manifest/index entry is absent afterward                                                     | session CLI/integration plus walkthrough assertion                               |
| Codex readiness branch     | environment, explicit-file, native-home-only, and not-ready auth   | one initial-message turn may run; native auth stays isolated; enrollment remains separate            | `tests/integration/core/test_codex_session_start.py` plus checklist branch       |
| Sandbox provenance         | malicious env, missing marker, symlink alias, valid generated repo | unsafe targets execute nothing; valid sandbox remains functional                                     | `tests/regression/test_bug_o036_walkthrough_sandbox_provenance.py`               |
| Interrupted cleanup        | owned and foreign proxies plus stale walkthrough state             | cleanup removes owned state, preserves foreign resources, and keeps diagnostic evidence              | existing walkthrough regressions plus focused additions                          |
| Clean-wheel package        | wheel-installed walkthrough                                        | scripts/resources resolve package-locally and the full default run does not import the checkout      | installer Docker lifecycle or new sibling                                        |
| State parity               | QA and walkthrough state copies                                    | any parser change remains behaviorally and byte-parity guarded                                       | `tests/src/skills/test_walkthrough_state.py`, `test_walkthrough_state_parity.py` |

## Verification Requirements

- Focused walkthrough-state, sandbox-provenance, cleanup, report, installer, and runtime-skill tests.
- Targeted session, hook, telemetry, routing, search, and optional Codex integration tests for changed paths.
- A clean-wheel `--setup-only` run followed by one complete default walkthrough with saved report/evidence.
- One interruption/resume exercise and one cleanup rerun.
- Confirm measured default duration, human checkpoint count, and paid-run count satisfy the ratified budget.
- `make test-unit`, `make test-regression`, relevant targeted integration commands, `uv build`,
  `scripts/test-wheel-runtime.sh`, `make pre-commit`, Markdown link checks, file-size checks, and `git diff --check`.

## Deferred Question

- After v1.0.0, should the shared walkthrough driver remain skill-owned or move behind a small Forge CLI surface before
  adding a Codex-facing frontend?
