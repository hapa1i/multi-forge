# Change Log

Completed-work record for Forge implementation sessions.

Older entries are retained verbatim in [2026-08-21](archive/change_log_2026-08-21.md),
[2026-08-20](archive/change_log_2026-08-20.md), [2026-08-19](archive/change_log_2026-08-19.md),
[2026-08-18](archive/change_log_2026-08-18.md),
[2026-08-15 through 2026-08-17](archive/change_log_2026-08-15_to_2026-08-17.md),
[2026-08-05 through 2026-08-14](archive/change_log_2026-08-05_to_2026-08-14.md), and
[through 2026-08-04](archive/change_log_through_2026-08-04.md).

## 2026-10-27

### Preserve tool evidence in transfer summaries

List-form results retain ordered text and delegation calls retain labeled arguments within the existing field caps.
Structured keeps its text-bearing-group admission rule; Unicode escapes stay whole, and oversized Codex initial prompts
refuse before launch with session/snapshot rollback. Session-context design and end-user guides are synced.

**Verification**: [PR #283](https://github.com/hapa1i/multi-forge/pull/283) merged as `9751470b`, matching reviewed head
`fa4c53b6`, with all five CI checks passing. Local checks passed 11,223 unit tests, 2,202 regressions, 10 Docker
transfer/resume/launch tests and full pre-commit. The
[closeout](done/transfer_summarizer_fidelity/checklist.md#merged-closeout) retains size comparisons, launch-boundary
evidence and the successful three-test Docker storage rerun. M2 is done.

### Disable native delegation and memory in Forge workers

**Goal**: Keep Forge-owned reviews and consumers independent of inherited native delegation and memory settings.

**Key changes**:

- Apply explicit Claude/Codex worker profiles across review panels, supervisors, the memory writer and shadow curation;
  compose authentication helpers with the final controls before subscription verification.
- Fork resumed Claude reviews into separate sessions, preserving source transcripts during parallel reviews.
- Verify native admission from clean wheels on pinned/current runtimes and recognize Ubuntu's GNU timeout binary in the
  probe harness. Managed-root delegation and memory choices remain separate.

**Verification**: [PR #282](https://github.com/hapa1i/multi-forge/pull/282) merged as `ef6a41e1`, matching reviewed head
`81586905`, with all five CI checks passing. CI passed 11,173 unit tests, 2,176 regressions, dependency pins and the
clean-wheel runtime check. Local verification includes 16 targeted Docker cases, four live reviewer/cost cases, native
probes on both version tracks, build, full pre-commit and live panels. The
[closeout](done/worker_native_controls/checklist.md#merged-closeout) links evidence and limitations. M0 is done; the
broader native-multiagent epic remains proposed.

## 2026-10-25

### Add the October open-model shortlist

**Goal**: Support Kimi K3.1 Pro, MiniMax M3.1 Flash, and DeepSeek V4.1 Flash 1017 as explicit model choices.

**Key changes**:

- Add catalog entries, OpenRouter routes, template alternatives, and workflow workers while preserving existing defaults
  and saved proxy snapshots.
- Apply model-specific reasoning, sampling, and tool-choice constraints; document translated reasoning-history limits
  and add release QA coverage.
- Prevent OpenRouter request extras from leaking across requests, clean up workflow test health stubs, and restore
  inherited reviewer helpers on supported Claude versions that reject anonymous settings paths.

**Verification**: [PR #281](https://github.com/hapa1i/multi-forge/pull/281) merged as `30ad379b`, matching reviewed head
`d1edbed9`, with both CI workflows passing. Local verification includes six live tool round trips, 2,158 regressions, 16
workflow/auth integration cases, full pre-commit, build and clean-wheel checks. The
[closeout](done/october_open_models/checklist.md#merged-closeout) preserves the evidence and corrected local
unit-inventory failure; proxy-guide size cleanup remains a separate proposal.

## 2026-10-22

### Pin build and installation inputs

**Goal**: Make Forge-owned build and installation inputs reviewable and refuse unverified source updates.

**Key changes**:

- Derive runtime constraints and hashed build requirements from the lock; pin CI Actions, bootstrap artifacts and Docker
  defaults.
- Validate immutable source candidates before changing the active editable installation, and scope build constraints to
  Forge commands.
- Document and test hash-verified global wheel installation; add a separate scheduled/manual unconstrained wheel
  compatibility check. The [dependency security guide](../developer/dependency_security.md) records remaining limits.

**Verification**: [PR #280](https://github.com/hapa1i/multi-forge/pull/280) merged as `50472bee`, matching reviewed head
`12a033bb`, with all five CI checks passing. Local checks passed 11,151 unit tests, 2,152 regressions, 29 targeted
Docker tests, full pre-commit, build and clean-wheel checks. The
[closeout](done/supply_chain_pins/checklist.md#merged-closeout) links the evidence and retains the distinction between
version constraints and hash verification.

### Separate session deletion from native purge

**Goal**: Separate Forge-owned session cleanup from explicitly requested removal of native conversation files.

**Key changes**:

- Delete and clean preserve native conversations; purge previews additional verified paths and supports project-scoped
  `--all`.
- Dependency and activity checks, instance ownership and writer fences protect replacement sessions and cleanup retries.
- Native removal admits characterized Claude 2.1.245 and Codex 0.162.1 layouts; unverified layouts refuse, and global
  runtime state remains outside scope. Design and end-user documentation reflect the shipped contract.

The [card is done](done/session_delete_and_purge/checklist.md#merged-closeout); the
[generation-token proposal](retired/session_delete_generation_token/card.md) retires as folded into it.

**Verification**: [PR #278](https://github.com/hapa1i/multi-forge/pull/278) merged as `c1afa9cd`, matching reviewed head
`538a7a4f`, with all five CI checks passing. Local `make test` passed 11,138 unit and 523 Docker integration tests;
2,084 regressions and full pre-commit passed. Slow provider trials were excluded. The
[verification record](done/session_delete_and_purge/evidence/verification.md) separates those checks from the two
approved synthetic Claude captures. No new paid capture ran during closeout.

## 2026-10-20

### Remove retired Jev consumer experiments

**Goal**: Remove A2/A3 implementation and maintenance cost while retaining the shipped A1 client and historical
evidence.

**Key changes**:

- Removed retired experiment runners, private rule/consent modules and their tests; ordinary policy validation remains.
- Preserved A1 and all 45 historical JSON artifacts; current documentation links the archived experimental source.
- Made fast forced-tool rejection tests use local upstream fixtures and assert that no request is forwarded.

**Verification**: [PR #277](https://github.com/hapa1i/multi-forge/pull/277) merged as `51c2d92c`, with the same tree as
reviewed head `e760648f` and all five GitHub checks passing. Local `make test` passed 10,962 unit and 519 integration
tests; 1,891 regressions, full pre-commit, build and clean-wheel checks passed. Slow live-provider tests were excluded.
The [cleanup closeout](done/retired_jev_cleanup/checklist.md#merged-closeout) preserves verification details. A1 remains
done; the epic, A2 and A3 remain retired.

## 2026-10-19

### Preserve the A3 comparison and retire the Jev initiative

**Outcome**: [PR #276](https://github.com/hapa1i/multi-forge/pull/276) merged as `ca943b6c`, preserving 24
human-reviewed synthetic cases, offline admission/composition and four deterministic controls. Those controls cover all
six expected allows; the remaining 18 actions escalate. This packet stopped before paid capture and establishes no
general A3 quality or quota-saving claim.

The owner cancelled and retired the [epic](retired/epic_jev_support/checklist.md#retirement-closeout),
[A2](retired/jev_rule_pack/checklist.md#retirement-closeout) and
[A3](retired/jev_cascade/checklist.md#merged-closeout-and-retirement), with no replacement selected. A1 remains done.
Retained foundations and evidence remain available; unfinished warnings and review skipping do not receive completion
credit. Future reconsideration requires a new proposed card.

**Verification**: PR #276's merged tree matches reviewed head `b989b55f`, with all five CI checks passing. Pre-merge
validation passed 172 focused tests and full pre-commit. Retirement checks and preserved evidence identities are
recorded in the epic closeout. No paid model call or native collection ran during retirement.

### Preserve bounded Jev evidence and pause A2

**Goal**: Close the bounded A2 investigation with retained evidence and an explicit pause before further runtime work.

**Key changes**: Retained the approved diagnostic capture and human review with bounded capture and replay guards.
Preserved the failed Jev sentinel, Opus's missing-replacement disagreement and latency shortfall, and the inconclusive
native audit. A2 moves to `paused/` with all 40 JSON evidence files and unmet acceptance gates preserved. The epic
selects independent A3 feasibility next; no runtime policy or review skipping is enabled.

**Verification**: [PR #275](https://github.com/hapa1i/multi-forge/pull/275) merged as `fe2d09a1`, identical to reviewed
head `06074f0c`, with all five GitHub checks passing. Local `make test` passed 11,597 unit and 528 integration tests;
`make test-regression` passed 2,015. Applicable pre-commit checks and the 722-source Markdown link audit passed. The
[pause handoff](retired/jev_rule_pack/evidence/pr-275-pause-handoff.md) records the earlier offline-cache setup failure,
successful normal rerun, standard test-selection limits and remaining A2 gates. No additional A2 or A3 experiment
capture ran during this wrap.

## 2026-10-17

### Ship the Jev feasibility checkpoint

**Goal**: Preserve experimental evidence and human review before deciding whether to implement further runtime behavior.

**Key changes**: Added bounded local inventory and constructed baselines, retained two separately approved calibration
captures, and added diagnostic review with reusable answer identities and compact provenance. The capture runner refuses
known consumed proposals before credential access. A2 remains active; no runtime policy is enabled.

**Verification**: [PR #274](https://github.com/hapa1i/multi-forge/pull/274) merged as `09984440` after all five CI
checks passed on reviewed head `f51bcde8`; 453 focused tests passed locally. The
[handoff](retired/jev_rule_pack/evidence/pr-274-merge-handoff.md) preserves 92 diagnostic answers, three nulls,
unresolved wording and remaining feasibility gates. No further paid capture or native trial is authorized.

## 2026-10-16

### Ship Jev human review and feasibility handoff

**Goal**: Establish reviewed rule evidence before implementing runtime checks.

**Key changes**: Added evidence-bound human review export/import, retained 17 confirmed constructed judgments, and
clarified advisory wrapper semantics. Corpus-relative review references survive board moves. Real-action coverage,
warning usefulness and calibration now precede runtime implementation; exposed held-out scenarios support only a limited
output check.

**Verification**: [PR #272](https://github.com/hapa1i/multi-forge/pull/272) merged as `64317485` with all five CI checks
passing. Local validation passed 239 focused tests, full pre-commit across the sandboxed run and separate local EOF
rerun, and the 691-source Markdown link audit. All eight ledgers replay and retain report identity after relocation. The
[handoff](retired/jev_rule_pack/checklist.md#human-review-merge-and-feasibility-continuation) preserves remaining data,
quality and runtime gates. A2 remains active; no paid A2 evaluation or native trial ran.

### Restore prompt-cache reuse on translated routes

**Goal**: Preserve Claude Code's cacheable conversation prefix and report cache usage consistently.

**Key changes**: Translate mid-conversation system messages into user reminders, gate client markers on the resolved
backend, and preserve cache reads/writes plus streaming provider identity through responses and telemetry.

**Verification**: [PR #273](https://github.com/hapa1i/multi-forge/pull/273) merged as `3573c147` with all five GitHub
checks passing. Recorded checks include 11,029 unit tests, 1,904 regressions, full pre-commit and 66 passing targeted
integrations; one stale LiteLLM streaming-cost expectation remains deferred. The
[closeout](done/prompt_cache_correctness/checklist.md#merged-closeout) preserves the synthetic and native cache
evidence, scope comparison and provider-side limitations.

### Close the October 13 bug reconciliation

**Goal**: Record the merged session, supervisor, installer and QA fixes with their final verification boundaries.

**Key changes**: Restore bounded Stop evidence and reviewer isolation, preserve transcript and installation ownership,
and validate QA inputs and prerequisites; retain supported relative Codex homes.

**Verification**: [PR #266](https://github.com/hapa1i/multi-forge/pull/266) merged as `74eb9afa`, identical to reviewed
head `4db2656a`, with all five GitHub checks passing. The
[closeout](done/daily_bug_scan_reconciliation_2026_10_13/checklist.md#merged-closeout) retains the initial aggregate
results and the later correction's 946 focused tests, 666 clean-wheel tests and 25 Docker installer tests, without
attributing earlier aggregate results to the corrected head. Native and host-installation evidence limits remain.

## 2026-10-15

### Ship offline Jev rule evaluation

**Goal**: Evaluate saved rule judgments with explicit evidence and accounting before admitting runtime policy checks.

**Key changes**: Shared rule outcomes and host applicability now support an offline evaluator with model/content
identity, human/host comparisons, per-reason unavailability and reproducible report provenance. Human labels remain
separate from proposals; A2's quality, activation and native-delivery gates stay open.

**Verification**: [PR #271](https://github.com/hapa1i/multi-forge/pull/271) merged as `791d9872`, identical to reviewed
head `cd008613`, with all five CI checks passing. Local checks passed 148 focused tests, 11,076 unit tests (117
deselected), 1,924 regressions and full pre-commit. An initial watchdog timeout-test failure passed isolated and full
reruns without changes. See the
[merge handoff](retired/jev_rule_pack/checklist.md#offline-evaluation-merge-and-next-gate) for CLI fixture and
preparation evidence. No paid A2 evaluation or native trial ran.

### Ship Jev consent and offline evaluation foundations

**Goal**: Prepare session-scoped paid-data acknowledgment and reviewable evidence before enabling Jev policy checks.

**Key changes**: Bound consent to each session instance, revoked both stored grants on policy disable, and blocked raw
activation/reset bypasses. Added explicit judgment run identity and an offline wrapper corpus that excludes reviewer
notes from model evidence. A2 remains active; activation, quality and native delivery are not established.

**Verification**: [PR #270](https://github.com/hapa1i/multi-forge/pull/270) merged as `9442c1e5`, identical to reviewed
head `55ce6e24`, with all CI checks passing. Implementation checks passed 11,001 unit tests, 1,889 regressions and 46
distinct targeted integrations; final review passed 215 focused tests and seven policy CLI integrations. See the
[foundation handoff](retired/jev_rule_pack/checklist.md#foundation-merge-and-continuation). No paid/native trial ran.

### Preserve Claude permissions in policy feedback

**Goal**: Keep Write/Edit policy feedback from granting native Claude permission.

**Key changes**: Removed explicit approval from the shared feedback response while preserving context, blocks and audit;
documented Read-hygiene's existing input-correction exception and bounded the regression coverage claim.

**Verification**: [PR #269](https://github.com/hapa1i/multi-forge/pull/269) merged as `e9c144eb` with CI passing; 54
focused tests, 28 fixture-backed hook integrations and full pre-commit passed. The user authorized merge with paid
native testing skipped; native receipt and permission handling remain unverified. See the
[closeout](done/claude_policy_feedback_permissions/checklist.md#merged-closeout).

## 2026-10-14

### Ship the typed Jev Decisions client

**Goal**: Establish a shared typed judgment transport and measured contract before adding Jev policy consumers.

**Key changes**:

- Added Choice/Noul/Score validation, mandatory ZDR, conservative byte admission, caller-owned deadlines and bounded
  retries. Invalid answers and unexpected attempt failures retain independently valid usage without reporting success.
- Mapped Decisions tokens, reported cost and request IDs into existing telemetry schemas; preserved old history, unknown
  cost and per-attempt attribution. Kept fixture transports outside the package.
- Retained 29 authorized synthetic requests, latency/accounting evidence, answer variance and offline replay provenance.
  Closed A1 while keeping the Jev epic and its unimplemented consumers separate.

**Verification**: [PR #268](https://github.com/hapa1i/multi-forge/pull/268) merged as `9778007a`, identical to reviewed
head `d02627ab`, with all five GitHub checks passing. The PR passed 10,910 unit tests, 1,854 regressions, four targeted
integrations and full pre-commit. Closeout checks and supported limits are recorded in the
[A1 closeout](done/jev_client_probes/checklist.md#merged-closeout). No closeout inference ran.

## 2026-10-13

### Adopt Gemini 4 Argon defaults

**Goal**: Use Gemini 4 Argon for Gemini Pro-family defaults while preserving explicit older models and saved user
configurations.

**Key changes**:

- Added Argon catalog metadata, provider aliases, native thinking controls, and fresh Gemini Sonnet/Opus defaults;
  retained Flash and corrected local Pro routes for single-credential setups.
- Kept saved snapshots user-owned and checked loaded LiteLLM deployments before workflow launch. Preserved token-limit
  and content-filter termination through translation, including partial tool calls and streaming.
- Documented provider-specific migration and pricing, and verified fresh/saved configurations and native/mixed panels.

**Verification**: [PR #267](https://github.com/hapa1i/multi-forge/pull/267) merged as `42c150b7` with all five checks
passing. The PR passed 10,804 unit tests, 1,727 regressions, 23 targeted integrations, full pre-commit, build, and clean
wheel checks. The merged-main recheck passed 300 focused tests. See the
[closeout](done/gemini_4_argon/checklist.md#merged-closeout).

### Ship native Codex supervision and close the supervisor epic

**Goal**: Review complex work with explicitly selected native planning context while preserving plan authority, reviewer
isolation, bounded execution and attributable usage.

**Key changes**:

- Shipped immutable copied source/ancestor prefixes, dedicated reviewer login ownership, fresh native indexes and
  explicit model/auth admission. Separate completed sources support PreToolUse; shared/active context requires Stop and
  an approved plan. Recorded input identity and new-review usage without claiming complete history retention.
- Completed reviewed executor, policy recovery, lease queue, API-home ownership, hook dispatch and direct-command fixes.
  Closed B5 and the Codex supervisor epic with every member shipped and its native evidence limits preserved.

**Verification**: PR #265 merged as `de3efca8`, identical to tested head `e222c575`, with all five checks passing and
merged-main CodeQL green. Follow-ups on `main` are `f0d1d52c`: 10,774 unit tests, 1,618 regressions, 16 targeted
integrations, 66 offline clean-wheel checks and full pre-commit passed. The native round remains closed at 60/60 starts
and 3/4 authorized API starts; no closeout inference ran. See the
[B5 closeout](done/codex_fork_supervisor/checklist.md#merged-closeout) and
[integrated epic closeout](done/epic_codex_supervisor/checklist.md#merged-closeout).

## 2026-10-11

### Preserve global ignores in Stop evidence

**Goal**: Keep globally ignored untracked files out of Stop snapshots and reviewer evidence.

**Key changes**: Resolve effective Git exclusions as bounded data while preserving helper isolation, config precedence,
and normal tracked-file scope; refuse unreadable or invalid exclusion inputs.

**Verification**: 10,697 unit tests, 1,542 regressions, four targeted integrations, and full pre-commit passed.
[PR #264](https://github.com/hapa1i/multi-forge/pull/264) merged as `d33721a2`, identical to tested head `697bf553`,
with all five PR checks passing; the merged-tree recheck passed 35 tests. See the
[closeout](done/preserve_stop_global_ignores/checklist.md#merged-closeout).

### Review Codex turns once at Stop

**Goal**: Review completed Codex work against the approved plan with at most one reviewer dispatch per explicit turn.

**Key changes**:

- Added opt-in Stop supervision with durable dispatch/correction reservations, bounded raw evidence, source-aware
  feedback, exact hook enrollment, and manifest v4 only for non-default trigger state.
- Kept manual between-turn changes outside correction scope, retained partial-review exclusions as unreviewed, and
  isolated recreated sessions from historical journals. Deterministic pre-edit checks remain active.
- Closed B4 after merge and verified its tree and CI. The Codex supervisor epic remains active with B5 proposed.

**Verification**: 10,672 unit tests, 1,541 regressions, 60 targeted integrations (one real-inference control
deselected), 93 focused B4/link checks, full pre-commit, and clean-wheel verification.
[PR #263](https://github.com/hapa1i/multi-forge/pull/263) merged as `2045aea1`, matching tested head `5eecc6ff`, with
all five GitHub checks passing. The [merged closeout](done/codex_stop_review/checklist.md#merged-closeout) preserves the
two native rounds, source-drift qualifications, unverified quota exhaustion, and the native cancellation qualification.
No closeout inference ran.

### Deliver bounded Codex policy feedback

**Goal**: Make allowed policy findings visible to Codex and the operator while preserving verdicts and audit evidence.

**Key changes**:

- Added separate model/operator feedback, summary-off controls, and source-only verified plan quotations with fixed
  diagnostics. Preserved blocking guidance, atomic patch state, and readable full evidence.
- Bound feature admission to the managed executor process while preserving shim launch behavior. Accepted verified
  current Claude subscription metadata and repaired exported Docker runtime startup and cache invalidation.
- Closed B3, retained its evidence and runtime artifacts, and removed the independent fixture login. The Codex
  supervisor epic stays active; B4/B5 and Jev remain proposed.

**Verification**: 10,640 unit tests (117 deselected), 1,449 regressions, 31 affected Docker cases, and full pre-commit
passed, alongside the retained delivery/TUI/clean-wheel evidence. The Docker cases include two separately authorized
Haiku API checks. [PR #262](https://github.com/hapa1i/multi-forge/pull/262) merged as `f1019f6c`, matching tested head
`81c14448`, with all five GitHub checks passing. The
[merged closeout](done/codex_policy_warnings/checklist.md#merged-closeout) records the 16-control offline recheck,
fixture teardown, and host-state limits. No closeout inference ran.

## 2026-10-10

### Validate Codex 0.161.0 runtime contracts

**Goal**: Establish which existing hook, session, and native-fork contracts hold on a retained Codex binary.

**Key changes**:

- Raised the general validated ceiling to 0.161.0 after preflight, enrollment, product hook, resume, TUI, and native
  usage probes; preserved the blocking QA pin, shared QA provenance, and independent proxy floor.
- Published measured feedback, Stop, lifetime, and fork handoffs for B3-B5, including the parent-manifest isolation
  blocker, unverified quota/snapshot claims, and historical harness-source drift.
- Protected probe auth and enrollment, corrected operator environments and redaction, and added regression coverage and
  reproducible evidence export. Closed B2; the epic stays active and B3-B5 remain proposed.

**Verification**: Review fixes passed 10,600 unit tests (117 deselected), 1,400 regressions, 98 focused checks, 32
policy integrations, and full pre-commit. The original round also passed two subscription-backed Codex integrations,
build, and clean-wheel checks. [PR #261](https://github.com/hapa1i/multi-forge/pull/261) merged as `2a15c087`, matching
tested head `29ee539d`, with all five GitHub checks passing. The
[merged closeout](done/codex_0160_validation/checklist.md#merged-closeout) retains artifact identities and evidence
limits; optional fresh stage 88/97 reruns were not performed before merge.

## 2026-10-08

### Supervise approved plans with isolated reviewers

**Goal**: Review host Claude and Codex actions against an approved plan without requiring a planning conversation.

**Key changes**:

- Added plan-only supervision, explicit reviewer/model selection, read-only inspection of the action checkout, and a
  separate subscription-only auth opt-in that preserves existing bindings' inherited credentials and billing.
- Shared the hook deadline across reviews and retries, isolated watchdog helpers, retained computed verdicts on
  evidence-write failure, and separated shadow audits from live decisions.
- Preserved legacy timeout/proxy/override behavior and lossless v2 manifests; rejected incompatible sidecar images
  before launch. Recorded migration and recovery guidance in design and end-user docs.

**Verification**: 10,594 unit tests (117 deselected), 1,382 regressions, 41 targeted integration cases, build,
installed-wheel checks, and full pre-commit passed. Final GitHub CI also passed unit/regression suites and the
clean-wheel LiteLLM smoke. [PR #260](https://github.com/hapa1i/multi-forge/pull/260) merged through #259 and
[#258](https://github.com/hapa1i/multi-forge/pull/258) to `main` as `56d4b8f5`, matching tested head `2a3e7279` with all
five checks passing. The [B1 closeout](done/plan_file_supervision/checklist.md#merged-closeout) records subscription
probe limits and operational fail-open behavior. B2-B5 remain proposed under the active Codex supervisor epic.

### Partition runtime subprocess contracts

**Goal**: Give runtime routing and consumer-lane contracts room to evolve within the documentation size target.

**Key changes**:

- Moved complete subprocess transport and lane sections to `design_subprocesses.md`, retaining runtime lifecycle and
  configuration in the entry point; repointed inbound links and context routing.

**Verification**: Lossless reconstruction, Markdown links, and formatting/size checks passed. Partition-time Opus counts
were 16,864 for the runtime entry point and 8,286 for subprocess contracts, below the 23,000 partition target.
[PR #259](https://github.com/hapa1i/multi-forge/pull/259) reached `main` through #258; the
[completed checklist](done/partition_runtime_design/checklist.md) records the merged-stack checks.

### Partition session context and execution contracts

**Goal**: Split the session design into cohesive documents below the documentation size target.

**Key changes**:

- Kept durable session state in `design_sessions.md`; moved artifacts/resume/transfer to `design_session_context.md` and
  hooks/queues/Codex/journals to `design_session_execution.md`, preserving sections and updating inbound links.

**Verification**: Lossless reconstruction and Markdown formatting/size/link checks passed. Partition-time Opus counts
were 4,706, 10,816, and 10,541 respectively, all below 23,000. [PR #258](https://github.com/hapa1i/multi-forge/pull/258)
merged as `56d4b8f5`; the [completed checklist](done/partition_session_design/checklist.md) records the integrated
result. The oldest three changelog date blocks were archived verbatim during closeout.

## 2026-10-06

### Set session launch effort and forward guarded runtime arguments

**Goal**: Let managed Claude and Codex sessions choose effort and runtime flags for one launch while preserving
Forge-owned identity, routing, and artifact authority.

**Key changes**:

- Added per-runtime `--effort` and explicit `--` passthrough, with reserved-flag and advisory-authority refusals before
  mutation. Revalidated arguments against the locked authority manifest before launch events or active registration.
- Preserved launch arguments in route-recovery commands and kept them out of persisted session intent.
- Gated translated client effort on an explicit launch header, clamped it to model support, and scrubbed inherited
  opt-in headers from headless children.
- Upgraded Starlette to remove the AnyIO TestClient deprecation warning, with a fresh-interpreter regression.

**Verification**: 10,539 unit tests and 1,331 regressions passed without warnings; 73 HTTP-client tests passed with
deprecations treated as errors. Targeted session/authority and proxy integrations, pre-commit, build, and the
clean-wheel LiteLLM smoke passed. One earlier Claude-to-Codex integration attempt was blocked by a missing container API
key; the [completed checklist](done/session_launch_effort/checklist.md) retains that limitation and the successful
follow-up coverage. [PR #257](https://github.com/hapa1i/multi-forge/pull/257) merged as `845811c2`; its tree matches
verified head `54f320cf`, with all five GitHub checks passing.

## 2026-10-04

### Support Sonnet 5.5 and GPT-6.1 Sol

**Goal**: Adopt the current Sonnet model and add GPT-6.1 Sol while preserving saved routing choices.

**Key changes**:

- Promoted Sonnet 5.5 in direct aliases, workflow workers, and fresh Anthropic tiers; retained explicit Sonnet 5.
- Added GPT-6.1 Sol routes, alternatives, and pricing metadata; moved `sol`/`gpt-sol` to 6.1 and kept Astra defaults.
- Preserved native passthrough selection by limiting estimator pins to translated Messages routes. Rejected unsupported
  forced tool choices and incompatible `between_tools` effort floors before upstream dispatch.
- Corrected model-upgrade guidance and preserved existing proxy/backend snapshots. Gemini 4 remains deferred.

**Verification**: 10,396 unit tests, 1,315 regressions, 39 proxy/session integration cases, live workflow checks,
pre-commit, build, and clean-wheel snapshot/runtime checks passed.
[PR #256](https://github.com/hapa1i/multi-forge/pull/256) merged as `1ba9584c`; its tree matches verified head
`ffc1489f`, with all four GitHub checks passing. The [completed card](done/october_model_refresh/checklist.md) records
the evidence.

## 2026-09-23

### Refresh the model catalog and default to Opus 5.5

**Goal**: Add the major released models in existing provider families and make Opus 5.5 the default Opus.

**Key changes**:

- Added eleven models across Anthropic, OpenAI, DeepSeek, Qwen, and GLM with catalog routes, template alternatives, and
  workflow workers; retained explicit older models and existing user-owned proxy/backend snapshots.
- Completed Gemini 3.8 Flash support on LiteLLM, pinned the validated 1.102.0 runtime, and bundled missing native
  pricing and capability metadata.
- Preserved reasoning with tools on Sol/Luna Responses routes and rejected invalid tier temperature overrides at config
  load while retaining request-time filtering for model alternatives.
- Updated defaults, migration guidance, and QA expectations; added startup-log preservation to the wheel smoke check.

**Verification**: 10,368 unit tests, 1,266 regressions, 39 targeted integration cases, seven repeated live GPT-6 checks,
full pre-commit, build, two clean-wheel checks, native/mixed workflow panels, and snapshot-preservation checks passed.
[PR #255](https://github.com/hapa1i/multi-forge/pull/255) merged as `e107dd13` with all five GitHub checks passing. The
[completed card](done/september_model_refresh/checklist.md) records the evidence and remaining upstream Batch-pricing
limitation.

## 2026-09-06

### Close 1.0 release hardening

**Goal**: Close the merged enforcement, deletion-preview, and walkthrough hardening batch for release.

**Key changes**:

- Corrected Git diff attribution and exact-target recovery commands; preserved non-mutating deletion previews and
  truthful cleanup/retention results.
- Hardened walkthrough ownership, reset, package identity, and resume evidence, with matching QA state behavior.
- Closed the epic and its three members after PR #251 merged as `6f7cb64e`. The maintainer declined repeating the full
  manual walkthrough and QA runs for 1.0.0; their historical reports retain their original artifact identities.

**Verification**: The batch passed focused and aggregate suites, 11 targeted Docker integrations, build, installed wheel
checks, and all five PR checks. The final product tree passed 10,257 unit tests, 1,221 regressions, and 13
model/proxy/session integrations. The
[release disposition](done/epic_1_0_release_hardening/checklist.md#release-disposition) records the evidence accepted
instead of new manual runs.

### Add Claude Fable 5.1

**Goal**: Expose Fable 5.1 through direct Claude, proxy alternatives, and the named workflow worker.

**Key changes**:

- Added catalog and provider routes, repointed unversioned Fable aliases, and retained explicit Fable 5 selection.
- Preserved required-ZDR OpenRouter fallback behavior and synchronized model-selection guidance.

**Verification**: 10,149 unit tests, 1,180 regressions, targeted Docker tests, build, wheel-runtime checks, and all five
PR checks passed. PR #250 merged as `c3b7aa50`; the [card](done/claude_fable_5_1/checklist.md) is closed.

### Preserve explicit model selection and resume recovery

**Goal**: Preserve selected models, native effort, and complete recovery intent across proxy and session boundaries.

**Key changes**:

- Shared model-alternative resolution across planning and dispatch, normalized native `[1m]` effort, and retained
  complete fresh-resume options in recovery commands.

**Verification**: 403 focused tests, 10,216 unit tests, 1,211 regressions, six scoped Docker integrations, build,
pre-commit, and all five PR checks passed. PR #253 merged as `aedda8d7`; the
[card](done/close_daily_bug_scan_followups_2026_09_04/checklist.md) is closed.

### Make GPT-6 Astra the default GPT model

**Goal**: Add Astra and Astra Pro to the model catalog and promote standard Astra in existing GPT default roles.

**Key changes**:

- Updated OpenAI Sonnet/Opus tiers and workflow workers while retaining lightweight Mini, specialized Codex, and
  explicit Sol choices; Astra Pro routes through OpenRouter.
- Enforced catalog sampling capabilities on Responses requests and included effective model alternatives in workflow
  routing advisories. Added coverage for copied configuration examples, saved snapshots, and future default flips.
- Bundled offline Astra pricing with a LiteLLM support boundary test and isolated cost-cache tests; documented
  user-owned configuration upgrades and the removal of the `none` reasoning effort.

**Verification**: 10,257 unit tests, 1,221 regressions, 13 scoped proxy/Docker integrations, full pre-commit,
wheel/sdist build, and installed-wheel checks passed. [PR #254](https://github.com/hapa1i/multi-forge/pull/254) merged
as `2c1294d6` with all five GitHub checks passing; its tree matches the verified branch head `b7a4f97d`. The
[completed card](done/gpt_astra_defaults/checklist.md) records the commands and review-fix evidence.

## 2026-09-02

### Refresh the Day 1 walkthrough for v1.0.0

**Goal/outcome**: Replace the stale, QA-heavy walkthrough with a bounded and evidence-backed introduction to managed
sessions, continuity, routing, telemetry, and safe cleanup.

**Key changes**:

- Rebuilt the provider-neutral default journey around one direct managed Claude parent, one structured fresh-context
  continuation, explicit route intent/commit evidence, policy and telemetry orientation, and deterministic incognito;
  reduced it to seven human checkpoints and two paid operations.
- Added validated `--from` resume, package-bound reports and protected-path snapshots, plus optional Codex and sidecar
  chapters whose readiness, auth ingress, costs, and cleanup remain separate from the default verdict.
- Hardened the marked sandbox around isolated Forge/Claude/Codex state, explicit native-Claude settings exclusion,
  strict installation/trust registry handling, fail-closed reset, and repeatable ownership-aware cleanup.
- Synchronized the installation design, developer test contract, and Day 1 session, transfer, model-selection, skill,
  and manual-testing guidance.

**Verification**: 10,025 unit tests with 117 deselected; 1,104 regressions; 36 targeted lifecycle, sidecar, Codex, and
exact-wheel integration tests; build, clean-wheel runtime, pre-commit, link, size, and diff gates. The human default run
passed all 124 selected assertions with seven checkpoints and two paid operations; the maintainer accepted its recorded
package identity plus the corrected exact-wheel cleanup owner as composite final evidence. PR #249 merged as `fc015113`
with all five GitHub checks passing.

## 2026-09-01

### Refresh release QA for v1.0.0

**Goal/outcome**: Make release QA a bounded, exact-artifact gate with explicit automated and human ownership across
Claude- and Codex-runtime features.

**Key changes**:

- Replaced checkout-backed evidence with one prebuilt wheel installed in isolation, a byte-matched packaged QA driver,
  repository-pinned runtime identities, final drift probes, deterministic selection/budget metrics, and a separately
  classified non-blocking latest-client lane.
- Reduced the default run to 163 clean-wheel/human steps and mapped exhaustive contracts to automated owners while
  adding release seams for model routing, Codex sessions, adoption/repair, rewind, consumer lanes, backend lifecycle,
  provider trace, and both policy content sources.
- Closed clean-install defects surfaced by repeated RC runs, including venv hook launch resolution, missing-runtime
  errors, durable route reporting, non-mutating delete previews, container zombie classification, standalone Claude
  skill discovery, and multi-file policy enforcement.

**Verification**: The exact prebuilt wheel passed all 552 selected assertions with zero failures or skips under Claude
2.1.245 and Codex 0.149.1. The named integration owners passed 106 Docker tests plus one real host Codex 0.149.1 session
test; a non-blocking latest lifecycle passed with Claude 2.1.252 and Codex 0.152.0. Unit, regression, pre-commit, build,
clean-wheel runtime, exact-wheel lifecycle, link, size, and diff gates pass. The RC checklist records the maintainer's
explicit one-run paid-operation exception and two accepted manual-coverage limitations. PR #247 merged as `35dd157d`
with all five GitHub checks passing.

## 2026-08-24

### Close daily bug scan follow-ups

**Goal/outcome**: Close the six reproducible cleanup, model-route, and Markdown-enforcement gaps left after PR #245
without weakening locked transcript ownership, deterministic route replay, or resolved-containment link validation.

**Key changes**:

- Preserved a late sibling's shared native-relocate transcript while force-deleting a schema-invalid manifest, and
  reclaimed nested `<uuid>/subagents/` Claude agent logs through the same locked owner scan; nested discovery and
  raw-alias recovery require the exact canonical UUID spelling.
- Rejected model-route selection under flag- or config-derived sidecar mode before route side effects, and made bare
  replay reject blank stored proxy templates instead of acquiring same-URL registry identity, with `--host-proxy` and
  explicit `--proxy`/`--no-proxy` recoveries named in the refusals.
- Kept external repository aliases from erasing internal symlink spellings in manual Markdown validation, and made the
  repository-wide Markdown audit run for deletion-only commits.

**Verification**: 235 integrated focused cleanup/routing/Markdown tests plus 97 review-follow-up tests; 9,901 unit tests
with 117 integration-marked tests deselected; 1,073 regressions; two targeted Docker session-routing integrations; full
pre-commit including the 581-source Markdown audit. PR #246 merged as `6a4e7057` with all five GitHub checks passing.

### Correct post-merge session routing and cleanup defects

**Goal/outcome**: Close nine independently reproduced invariant gaps left by the transcript-safety and model-routing
merges without weakening publication locking, deterministic routing, or candidate-tree validation.

**Key changes**:

- Serialized aliased relocated-transcript and agent-log deletion with its final owner scan, and preserved validated
  Claude `[1m]` transport state across bare resume and inherited fork.
- Made stored proxy replay exact, applied the selected Claude tier, stopped at the first admitted automatic candidate,
  and let explicit replacement recover from malformed stored route state.
- Kept lexical Git identity separate from resolved Markdown containment, hardened manually supplied symlink spellings,
  and tightened route-catalog schema and direct Claude candidate validation.

**Verification**: 9,885 unit tests with 117 integration-marked tests deselected; 1,070 regressions; focused fail-first
coverage for all nine findings; two targeted Docker session-routing integrations; full pre-commit, Markdown, board-link,
and diff checks.

### Route interactive sessions by model

**Goal/outcome**: Let Claude-runtime sessions select any supported catalog model through one durable `--model` contract
without weakening explicit routes, bare resumes, or workflow routing determinism.

**Key changes**:

- Added one packaged, strictly validated route catalog shared by interactive sessions and non-runtime-native workflow
  workers; removed workflow-owned provider/template ordering after executable parity proof.
- Added strict manifest-v2 neutral route intent and a side-effect-free planner with explicit precedence, credential
  admission, tier resolution, selected-context preflight, single-candidate realization, and atomic intent transitions.
- Integrated model-first routing across start, resume, fork, and incognito, with exact-payload stderr evidence,
  fail-closed replay, no-launch persistence, and preserved Claude, Codex, adoption, and config-default boundaries.
- Synchronized the session/runtime designs, CLI reference, and end-user model, proxy, and session guides.

**Verification**: 399 final focused session/CLI tests plus two dual-ingress middleware cases; 9,865 unit tests with 117
integration-marked tests deselected; 1,068 regressions; targeted session, package-resource, workflow, proxy, and both
Docker routing integrations; full pre-commit; wheel/sdist build; and a current-head installed-package resource smoke
pass. PR #244 merged as `aff52243` with all five GitHub checks passing.

## 2026-08-23

### Correct daily review findings

**Goal/outcome**: Correct eight independently verified session, routing, recovery, design-reference, and repository-
validation defects without weakening the surrounding rollback, state-ownership, or compatibility contracts.

**Key changes**:

- Preserved Codex session, worktree, transfer, and completed-child state after successful route projection while
  retaining compensation before that boundary, and serialized the final relocated-transcript ownership decision with
  unlink.
- Recorded only Claude model pins actually applied to the child, added proxy wire shape to new route events while
  retaining legacy journal reads, and accepted authoritative runtime truth with empty known optional tiers when a usable
  mapping remains.
- Decoupled skill-invocation comparisons from unrelated config validation, rejected unrepresentable active-registry
  PIDs, validated Markdown links against the candidate Git tree, and repointed living references to their domain owners.

**Verification**: 121 final routing/authority tests; 9,764 unit tests with 117 integration-marked tests deselected;
1,068 regressions; required Codex start, direct Claude model-pin, Docker session-routing, and proxy runtime-truth
integration slices; full pre-commit; 567-source Markdown audit; and diff checks. PR #243 merged as `79342e99`.

### Record session route provenance and close its coordination epic

**Goal/outcome**: Make each managed launch's committed route inspectable without turning route or provider-declaration
evidence into authority, admission, authorship, or per-request attestation.

**Key changes**:

- Added a strict route journal and manifest projection that share the authority launch's root run identity, durable
  event seam, compensation vocabulary, and abort-aware presentation while remaining independently readable.
- Added `forge session model show|history`, the bounded `%session model show` summary, proxy runtime facts, and a
  default-off marking status-line segment backed by an intentionally all-unknown packaged declaration catalog.
- Validated proxy backend identifiers at their configuration boundary and preserved legacy launch-confirmation,
  tier-mapping, and sidecar callback semantics while recording the new route facts.
- Closed both independently shipped members and the Session Authority and Provenance epic after aggregate contract and
  retention verification.

**Verification**: 289 focused tests; 9,740 unit tests with 117 deselected; 1,067 regressions; targeted managed-launch,
proxy, and sidecar integration; one malformed-config Docker case; three real-runtime Docker cases (two Claude and one
Codex); clean-wheel and full pre-commit gates. PR #240 merged as `2a53397c` with all five GitHub checks passing.

## 2026-08-22

### Correct recent review regressions

**Goal/outcome**: Close five independently reproduced regressions in recent session, hook, authority, configuration, and
repository-policy changes without weakening the surrounding ownership, read-only, or latency contracts.

**Key changes**:

- Revalidated relocated-transcript ownership at the destructive unlink boundary and translated malformed active-registry
  reads into actionable, non-repairing authority errors.
- Redacted diagnostics before and after terminal rendering, kept ordinary streams on the bulk C0/DEL path, and preserved
  failure-excerpt semantics and the Stop overhead budget.
- Emitted extension-sync reminders only when config edit/reset changed invocation overrides, and narrowed the
  40,000-token historical exception to the two ratified checklist snapshots.

**Verification**: 171 focused tests before review and 66 focused Stop/hook tests after review; four required targeted
Docker boundaries, with the Stop boundary rerun after final remediation; 9,588 unit tests with 117 deselected; 1,067
regressions; full pre-commit, diff, board, and link checks. A 1.01 MB control-free diagnostic measured 29.5 ms median
(36.6 ms for full excerpt selection). PR #239 merged as `60af6b66` with all five GitHub checks passing.

### Put context limits and document ownership in the repository

**Goal/outcome**: Make context-size enforcement visible to contributors and leave every living context document with
room to grow, without shortening the design contracts or historical evidence that exceeded the old limits.

**Key changes**:

- Added a tracked file-size policy, family-tagged Opus-first counting, conservative local screens, and a batched
  pre-commit gate whose provider use and thresholds are repository-owned. Near-target provider evidence is cached by
  exact content hash so keyless CI and keyful contributors reach the same verdict; missing evidence fails visibly.
- Partitioned the core architecture, workflow memory, changelog, implementation notes, and whole-repository review by
  stable domains; all appendix links now target their canonical owners and the retired appendix path is gone.
- Added a repository-wide Markdown path-and-fragment audit and changed contributor context loading to route through the
  overview, active card, and implementation-note index before selecting only relevant domain documents.
- Preserved all 142 original design headings, 985 non-navigation paragraphs, 52 fenced examples, 26 changelog blocks, 46
  implementation-note sections, and 11 review sections under a recorded lossless-migration audit.

**Verification**: 108 focused policy/link tests; 9,583 unit tests with 117 deselected; 1,057 regressions; all 566
tracked Markdown sources pass the link audit; the all-files size gate passes in 3.2 seconds; full pre-commit and diff
checks pass. The 20 living/context documents measured with `claude-opus-5` are below 25,000 tokens, and all migrated
canonical design documents are at or below the 23,000-token migration target.

### Validate artifact authority through real runtimes

**Goal/outcome**: Close the shipped authority feature's real-model gap by proving its production launch, hook, denial,
and journal chain inside disposable Docker identities.

**Key changes**:

- Versioned the runtime test image by both installed Claude Code and Codex CLI versions and installed both real runtimes
  in the cached toolchain layer.
- Added paid release tests for a real Claude advisory denial, its producer control, and a real Codex advisory denial;
  each uses the public session CLI and asserts filesystem plus correlated journal evidence instead of model prose.
- Recreated only Codex's non-secret hook trust hashes at their original absolute paths; no host config was mutated and
  no `auth.json` was copied.
- Synchronized the bundled QA image identity, isolated the installer's no-Codex boundary, bounded hung runtime
  processes, and moved paid credentials from process arguments into atomic owner-only stdin writes.

**Verification**: Three real-model Docker cases; 437 non-slow integration tests with 10,615 deselected plus 13
current-head canonical Docker-helper cases; 207 focused authority tests; 9,447 unit with 117 deselected; 1,057
regression; full pre-commit, diff, and 1,227-link checks. PR #235 merged as `8e47f017` with all five GitHub checks
passing; the card closed to `done/` on 2026-08-22.
