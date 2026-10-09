# Codex runtime validation checklist

Card: [card.md](card.md). Epic: [Codex supervisor](../../doing/epic_codex_supervisor/card.md), member **B2**.

## Current focus

Closed 2026-10-10 after [PR #261](https://github.com/hapa1i/multi-forge/pull/261) merged as `2a15c087`. The
[merged closeout](#merged-closeout) records verification and the [results](evidence/README.md) retain the 2026-10-09
round's limitations. Execution used `test/codex-0160-validation`, selected 2026-10-08 from `79563944`. B3-B5 remain
proposed on separate future branches; the epic remains active.

Establish which existing Forge contracts and proposed hook/fork behaviors hold on the installed Codex version selected
at round start. Keep that executable fixed throughout the round. The result is a dated evidence matrix and a justified
compatibility decision. Warning delivery, Stop supervision, and native-fork supervision remain owned by B3, B4, and B5
respectively. The card slug and branch name remain unchanged.

The [B1 closeout](../../done/plan_file_supervision/checklist.md#merged-closeout) supplies narrow enforcement, isolation,
auth, and deadline evidence. Its [runtime captures](../../done/plan_file_supervision/evidence/README.md) include
API-backed Docker tests and one Claude subscription scenario; they do not establish B2's Codex subscription route or
replace this probe matrix.

## 0. Activation

- [x] Create the separate execution branch from `79563944`; move B2 to `doing/` with `git mv`.
- [x] Add this checklist and update the epic's selection, member state, and inbound card links.
- [x] Record passing Markdown, size, repository-link, and diff checks for this planning change.

## 1. Establish the runtime, auth, and fixture baseline

### Runtime and Forge identity

- [x] Select the Codex version installed when the round starts. Record its resolved executable path, SHA-256, version,
  OS, selected model/effort, and relevant CLI help. Preserve a private copy outside the repository, including required
  companion resources and their layout; verify the copy's hash/version and use its absolute path or fixture-local PATH
  in every probe terminal. Require the version recorded in this item for the whole round, including preflight,
  enrollment, and fork children. Recheck identity before/after each stage; changing the selected executable starts a
  separately recorded round.
- [x] Export `FORGE_DEV=<absolute checkout root>` in every probe environment, including the operator's second terminal;
  invoke that checkout's `.venv/bin/forge` for direct commands. In the same isolated environment, require
  `forge extension doctor --json` to report `hook_dispatcher.dev_override.effective: true` and the expected target.
  Capture hook-side launcher and imported-module paths outside stdout to prove dispatch actually reached the checkout.
  Keep registered command bytes unchanged when adding fixture instrumentation. Version `1.0.2` alone cannot identify the
  build: the global tool and post-B1 checkout share it.
- [x] Record `git rev-parse HEAD` and any dirty source diff/hash with each stage. Require direct commands and dispatched
  hooks to resolve the same build. A final installed-wheel check records a separate artifact identity and proves its own
  dispatcher target; it must not inherit `FORGE_DEV` and accidentally test the editable checkout.

### Auth and reviewer fixtures

- [x] Give the persistent Codex fixture its own operator-completed `codex login`, with
  `cli_auth_credentials_store="file"` in its isolated home. Do not copy the host's `auth.json`, use the real-home escape
  hatch, or clone a refreshing credential into per-stage homes. Adapt `probe_auth`, fixture construction, and EXIT
  cleanup before running stages: retain the fixture's refreshed auth in place across the round. A stage requiring
  another home needs its own login. Serialize ordinary stages against that store; isolate the deliberate
  concurrent-source case and classify any auth interference as inconclusive. Keep credential files private and outside
  captures; never read or log their contents.
- [x] Verify the selected Codex subscription auth in the exact isolated child environment. Remove competing API/auth and
  provider selectors; prevent Forge dotenv/credential hydration from restoring paid auth. Record only non-secret posture
  and token/turn evidence. Ambiguous auth or exhausted quota stops the probe without an API fallback.
- [x] Default nested semantic supervision to a deterministic Claude stub for E5 timings, E9 recursion, and E4 lifetime
  checks. Use a direct Claude lane with cascade and shadow sampling disabled. The stub must answer `--version` with an
  admitted major-2 version at least 2.1.248, pass the exact `READ_ONLY_FLAGS` help probe, and expose separate
  fast-verdict and sleeping-descendant modes. Reuse the admission pattern in
  `tests/integration/docker/test_plan_file_supervision.py`. Resolve only the fixture stub, strip real reviewer
  credentials, and allow no fallback to real Claude, a proxy, or an API checker. Do not replace the executor's `codex`.
- [x] Record stub admission separately from actual review entry: the review arm writes a marker with run identity,
  timestamp, PID, and process group before responding or sleeping. Label stub usage synthetic. A real Claude reviewer is
  allowed only for a named row that needs it, using `--auth-mode subscription-only`, B1's verified direct route and
  account prerequisites, and a separately budgeted Claude quota allocation. Native Codex fork subjects remain real Codex
  under the fixture's subscription; nested reviewers inside those forks still use the stub by default.

[OpenAI's refresh guidance](https://learn.chatgpt.com/docs/auth/ci-cd-auth) documents failures when another job rotates
a shared token first and requires preserving refreshed credentials. A separate fixture login avoids sharing the host's
refresh chain. Unchanged host file bytes alone cannot establish that a duplicated credential remains usable; no host
logout was reproduced here.

### Budget, enrollment, and cleanup

- [x] Audit the [existing harness](../../../../scripts/experiments/codex-hooks/README.md) before selecting stages.
  Record a per-stage model-turn estimate, a total turn ceiling, timeout bounds, and interactive operator steps. Include
  setup/control turns, subagents, retries, explicit enrollment verification, and the extra enrollment turn on every
  advisory Codex launch, including each `resume --task`. Count any real Claude reviewer calls against a separate Claude
  quota allocation; stop at the declared ceilings.
- [x] Prepare the selected stages from sections 2–5 with explicit selectors, positive controls, bounded cleanup, and the
  revised turn budget. Check shell syntax and offline result classifiers before model turns. Record new stage names in
  the acceptance table and harness README; preserve historical captures and version-qualified findings.
- [x] Use disposable projects and isolated `CODEX_HOME`/`FORGE_HOME`, with raw captures outside the repository. Preserve
  host hook/trust configuration and account settings. Keep the independent fixture login separate from disposable
  project and capture cleanup.
- [x] Reuse an operator-enrolled fixture only when its exact config paths and hook definitions still match. Otherwise
  prepare the isolated fixture and complete its interactive trust ceremony. No trust bypass counts as enrollment
  evidence. Re-enroll changed command, matcher, timeout, or config-location definitions before testing their delivery.
- [x] Revalidate wrapper-body replacement at stable paths and stamp each run's capture destination. Archive each attempt
  before rerunning a stage: `lib.sh` currently clears that stage's capture directory on initialization.
- [x] Require GNU `timeout` with a recorded TERM-to-KILL grace (`--kill-after`) and an independent fixture cleanup
  owner. Register child PID/start-time/process-group identities as they spawn, including the invoker's detached group
  and B1's watchdog/anchor/reviewer groups. After the observed deadline, sweep fixture-owned survivors, TERM then KILL
  after a bounded grace, and verify none remain. Do not signal unrelated processes or recycled PIDs. Capture survivors
  before emergency cleanup so a harness sweep cannot make a product cleanup failure pass. Refuse an unbounded fallback.

**Execution prerequisites:** confirmed isolated subscription auth, a usable enrolled fixture, a declared turn budget,
and operator access for UI/trust cases. Missing prerequisites leave dependent rows pending or inconclusive; an
unsuccessful model turn cannot prove non-delivery. These prerequisites were established for the executed round.

## 2. Recheck the contracts Forge already relies on

- [x] Map existing stages `00`, `05`, `10`, `60`, `61`, `81`, and `84`-`87` to the retained assertions before running
  them. Retain the current ceiling's Forge-preflight plus `00`/`10` baseline, with stage 10's bypass arm explicitly
  labelled diagnostic; it never proves enrollment. Use individual stages and positive controls rather than default/all
  bundles whose legacy auth/trust behavior has not been adapted.
- [x] Run `forge runtime preflight codex --json` against the retained binary and independently logged-in fixture. Assert
  `ready=true`, doctor-backed `auth_method=chatgpt_tokens` / `auth_source=codex_store`,
  `billing_mode=subscription_quota`, and `hook_seam=enrollment_gated`. This proves auth presence and hook capability;
  successful turns and receipts must establish validity and enrollment. Record the expected re-probe notice before the
  ceiling changes; stage 00 does not run Forge's preflight.
- [x] Run `forge runtime preflight codex --verify-enrollment --json` and prove the current user-scope SessionStart
  registration fires. Retain the correlated observation receipt before the temporary probe directory is removed, through
  fixture instrumentation, plus `attempted=true`, `codex_succeeded=true`, and `enrolled=true`. A registration-only check
  or failed turn is insufficient; account for the model turn in the budget.
- [x] Exercise current user-scope registrations through the installed absolute `forge-hook` dispatcher, including its
  catch-all policy row and 60-second timeout. Existing stages 85-87 use older direct `forge hook ...` registrations;
  adapt or supplement them so old fixture success is not reported as current installation evidence.
- [x] Prove SessionStart delivery with a nonce that appears only in hook context and is consumed by the model. Check
  delivery receipts and reconciled `confirmed.codex` facts, including an undelivered control.
- [x] Prove a product `apply_patch` deny prevents the requested filesystem change and an allow control performs it.
  Cover multi-file patches, tests-first evaluation, `updatedInput`, malformed output, and absent/untrusted hooks; record
  actual allow/deny/error behavior without assuming malformed output fails closed.
- [x] Recheck native start/resume, cross-CWD resume, JSONL thread/rollout identity, and the relevant managed TUI paths.
  Record interactive start, reattach, active-session refusal, and context-delivery observations separately.
- [x] For a real headless Forge turn, compare `turn.completed.usage` with exactly one correlated usage event:
  `route=codex_exec`, `reporter=codex_jsonl`, matching tokens, subscription billing, and unavailable dollar cost.
  Preserve runtime-error handling even at exit zero; use `tests/integration/core/test_codex_exec_smoke.py` as the
  existing owner.
- [x] Preserve authority-before-policy coverage for non-patch tools. Use enrolled advisory deny and unmarked/producer
  controls; a semantic-policy skip must not disable artifact authority.

**Compatibility gate:** a regression in a relied-on contract blocks the general validated-ceiling increase. Investigate
and fix within the card's scope, or record an explicit compatibility limitation and board disposition. B1 evidence may
be linked with its exact tested scope; it cannot stand in for missing B2 rows.

**Quota detection limit:** do not exhaust the account deliberately. Mark real Codex subscription-exhaustion detection
unverified unless it occurs naturally; fixture/parser coverage remains distinct. A ceiling increase does not establish
that live exhaustion or every runtime capability was tested.

## 3. Measure allowed feedback and catch-all coverage

- [x] Compare three allow responses: today's empty product stdout, `CodexHookResponder.allow_feedback()` with explicit
  `permissionDecision: allow`, and the candidate documented `additionalContext` response. The helper exists but is not
  emitted by the current command. Give each arm a fresh hook-only nonce; verify both the action and later model use.
- [x] Probe `systemMessage` and stderr separately in headless events and the interactive UI. Retain event captures and
  operator observations; neither alone establishes model-context delivery. Include a no-message control.
- [x] Capture actual payload names and counts for `apply_patch`, `update_plan`, a disposable MCP tool, `spawn_agent`,
  shell commands, and long-running `exec_command`/`write_stdin` sequences. Record unsupported tool surfaces explicitly.
- [x] Measure repeated per-tool dispatcher duration with semantic supervision disabled and configured, keeping fixture
  conditions comparable and using the fast Claude stub. Separate cold admission, uncached patches, and cache hits; patch
  samples need not all dispatch because the supervisor caches results. Report sample count and latency distribution
  separately from stub time, model latency, and quota use. Non-patch semantic skips must make zero reviewer calls;
  instrument dispatch to prove it.
- [x] Capture complete `update_plan` payloads, ordering, thread/turn/tool IDs, and repeated updates. Identify missing or
  truncated evidence. An agent plan event is not user approval and must not become a plan-source admission rule.

**B3 handoff:** identify the exact tested response shape, versions, model-visible channel, and operator-visible channel.
Negative delivery results constrain B3; they do not authorize a product response change in B2. Any matcher proposal must
account for the authority guard and the enrollment cost of a changed registration.

## 4. Probe timeout, background delivery, and Stop continuation

- [x] Compare a hook that exceeds the registered 60 seconds with a controlled earlier Forge deadline. Use a bounded
  sleeping Claude stub/descendant fixture that has passed admission. Count reviewer-lifetime evidence only after its
  review-entry marker proves dispatch and correlates to a durable attempt. `ReviewAttempt` is written before admission;
  a pending attempt alone proves neither process start nor inference. Capture timestamps, signals, tool effects,
  warnings, and reviewer/descendant survival through the cleanup grace.
- [x] Keep natural runtime expiry separate from production-budget evidence. B1 normally stops review within 55 seconds;
  use an explicitly instrumented fixture to exceed 60 seconds, preserving registration bytes. Label that arm as runtime
  timeout evidence, and exercise the ordinary earlier deadline through unmodified B1 code. Do not attribute a bare
  sleeping hook's behavior to a reviewer that never dispatched.
- [x] Separate natural expiry from executor cancellation and hook-only death. Confirm a completed positive-control turn;
  label early cancellation inconclusive for the natural-timeout claim. Inspect durable attempt/usage evidence and
  `forge policy supervisor status --json` / `forge telemetry activity <session> --json` after interruption.
- [x] Record pending, unavailable, and incomplete attempts without treating missing terminal records as aligned or
  zero-cost. Keep the operational failure result distinct from any computed alignment verdict.
- [x] Test background hook completion during a live turn and after turn completion, plus cancellation and ordering. Use
  a nonce and timestamps to distinguish model delivery, operator notification, and whether a new turn starts. Background
  delivery never counts as enforcement of the triggering action.
- [x] Trigger exactly one controlled Stop block in the isolated fixture, followed by an allow. Capture continuation
  prompt/context, `stop_hook_active`, thread/turn IDs, repeated Stop events, and a no-block control. Bound the harness
  against loops independently of the runtime's Stop guard.

**B4 handoff:** specify which observed IDs and continuation markers can support one review per user-initiated turn, and
what remains unidentifiable. Record timeout/delivery limits; B4 must choose its own Stop timeout and account for edits
made after the reviewed snapshot. A Stop block cannot undo an edit.

## 5. Probe native forks and shared source threads

- [x] Create a planning source with a unique sentinel, then fork with `codex exec fork`, `--ephemeral`, and
  `--output-schema` together. Record exact option placement, source/fork identities, schema validation, terminal status,
  and persisted artifacts; exit zero alone is insufficient evidence of a successful review.
- [x] Prove inherited context using a source-only sentinel absent from the fork prompt and accessible files. Compare
  source rollout hashes and identity before/after a quiescent fork; the review must not append to or rebind the source.
  State what was actually retained, including any observed compaction limit.
- [x] Put different file sentinels in planner and action checkouts. Launch the fork to inspect the action checkout,
  require the corresponding read result, and attempt a controlled write. Compare filesystem snapshots and an isolated
  workspace-write positive control; accepted read-only flags or model promises are not enforcement evidence.
- [x] Observe hooks inside the fork under Forge depth/consumer markers. Record actual deliveries, recursion suppression,
  reviewer dispatch count, and whether any unintended session adoption or parent-state mutation occurs. Keep any nested
  semantic review on the admitted Claude stub, and identify its events separately from the real Codex fork.
- [x] Add a later implementation sentinel and reasoning that contradicts an explicit approved plan to a shared source.
  Record which context the fork inherits and whether the supplied plan takes precedence. This behavioral observation
  does not establish reviewer independence or create an earlier-turn fork selector.
- [x] Fork while the controlled source is active. Separate expected source writes from fork-induced changes using tagged
  events and prefix snapshots; a whole-file hash change during source execution is not by itself a failure. Record a
  reproducible fork boundary or mark concurrent-source behavior unsupported/inconclusive.

**B5 handoff:** record supported option combinations, context and checkout selection, read-only evidence, hook behavior,
source immutability, and concurrency limits. Failed new-feature probes are valid outcomes; B5 must refuse unsupported
cases rather than infer support from CLI help or silently use another source.

## Acceptance evidence

Every row needs an exact command, Forge revision/build provenance, Codex path/hash/version, fixture and auth identity,
positive control, result, and sanitized capture reference. Use `pass`, `fail`, `unsupported`, or `inconclusive`; retain
exit status separately. The [results matrix](evidence/README.md#results-and-downstream-decisions) links the retained
artifacts for every row. E1 combines explicit Forge preflight/enrollment/usage assertions with the listed stages.

| ID  | Area                | Fixture / control                            | Observable assertion                        | Evidence owner                                           |
| --- | ------------------- | -------------------------------------------- | ------------------------------------------- | -------------------------------------------------------- |
| E1  | Existing paths      | Enrolled/untrusted homes; allow/deny         | Readiness, receipt, usage, hook/resume      | Forge checks; stages 00/05/10/60/61/81/84/88/89/91/92/97 |
| E2  | Allowed warnings    | Three response arms; unique nonces           | Action executes; model consumes context     | 90 feedback captures                                     |
| E3  | Operator warnings   | UI/events; no-message control                | `systemMessage` and stderr visibility       | 90 + 97 TUI captures                                     |
| E4  | Hook timeout        | 60-second expiry; earlier deadline           | Tool outcome, child cleanup, attempt state  | 95 lifetime captures                                     |
| E5  | Catch-all cost      | Tool matrix; supervision off/on              | Counts, latency, zero skipped-review calls  | 93 coverage captures                                     |
| E6  | Background          | Live/finished/cancelled turns                | Delivery ordering and next-turn behavior    | 96 + 97 background captures                              |
| E7  | Planning fork       | Source-only nonce; quiescent parent          | Context, schema, identity, unchanged source | 94 fork captures                                         |
| E8  | Shared source       | Plan/implementation sentinels; active source | Inherited boundary and concurrency limits   | 94 fork captures                                         |
| E9  | Read-only/recursion | Different checkouts; write control           | Correct read, blocked write, bounded calls  | 94 fork captures                                         |
| E10 | Plan events         | Multiple updates; independent approval       | Complete payloads and observed IDs          | 93 coverage captures                                     |
| E11 | Stop continuation   | Block once; no-block control                 | Continuation markers and repeat counts      | 81 Stop capture                                          |

## 6. Record results and apply the compatibility decision

- [x] Run `sanitize.sh`, inspect its secret scan, and review fixture candidates before adding them. Publish a dated
  results matrix under this card's `evidence/` and promote only reusable sanitized fixtures to `tests/fixtures/codex/`
  with provenance. Do not retain auth files, real account identifiers, or raw private rollouts.
- [x] After the selected relied-on contracts pass, advance `CODEX_VERSION_VALIDATED` to the version recorded in section
  1 and change only `tracks.pinned.codex.general_probe_ceiling` in the QA runtime matrix to match. Keep the release pin,
  both runtime probe records, shared `validated_forge_revision`/`validated_on`, and blocking track unchanged. Record
  B2's revision, date, scope, and exhaustion limitation in B2's evidence. A release-pin change needs its own probe and
  provenance decision. Keep `CODEX_PROXY_CONTRACT_VALIDATED` and `proxy_contract_floor` at 0.141.0; this round does not
  validate proxy transport. Re-run preflight to prove the retained binary is no longer above the updated ceiling.
- [x] The selected relied-on contracts passed. Record unsupported plan tools, parent-manifest mutation, concurrency
  limits, and unverified live quota exhaustion without claiming support for those cases.
- [x] Update focused tests for any changed preflight, hook, fixture-parser, or QA-matrix contract. Reuse
  `tests/src/core/runtime/test_codex_preflight.py`, `tests/src/cli/hooks/test_codex_policy*.py`,
  `tests/src/install/test_codex_hooks.py`, and `tests/src/skills/test_qa_checklist_contract.py` where applicable. Every
  product bug fix gets a failing-before/passing-after regression; do not weaken existing assertions to obtain a pass.
- [x] Run affected integration paths through `./scripts/test-integration.sh <selected-paths>`. Candidate owners are
  `tests/integration/core/test_codex_exec_smoke.py`, `test_codex_session_start.py` in that directory, and the relevant
  Docker policy/authority/plan-supervision cases. Inspect auth requirements before selecting them: API-backed tests are
  separate evidence and must not silently spend against the subscription-only probe plan. Add or adapt the required
  isolated subscription coverage when existing fixtures select paid credentials.
- [x] Update the narrow normative owners with measured behavior: `design_session_execution.md` for runtime/hooks,
  `design_session_context.md` for context facts, and workflow/subprocess/telemetry/installation docs only where their
  shipped contracts change. Update end-user policy/session/setup guidance when a user's required action changes. Correct
  obsolete runtime-limit wording in touched living docs; preserve dated historical findings.
- [x] If packaged QA assets or runtime behavior change, run `make build` and verify the relevant behavior from that
  wheel in a clean install. Run applicable aggregate unit/regression and full pre-commit gates before the execution
  commit/PR; rerun affected probes only when fixes or unresolved observations justify it.

## Closeout

- [x] Before opening B2's PR, fetch `origin/main`, publish the separate B1 closeout `79563944` from local `main` with a
  normal fast-forward push, and verify it is an ancestor of `origin/main`. On remote divergence reconcile first; never
  force-push. Inspect the PR's `origin/main...HEAD` diff so it contains only B2 work. `79563944` was pushed normally to
  `origin/main` before execution closeout; no force-push was used.
- [x] Every E1-E11 row has retained evidence and an explicit disposition; no pending observation is called supported.
- [x] Link the B3/B4/B5 decisions and captures from their cards and the epic checklist; keep each member proposed until
  selected separately. Record any required dependency or scope change on both sides.
- [x] Record focused/aggregate tests, integration auth posture, runtime versions, installed-wheel results when required,
  and all non-passing outcomes. Verify Markdown, size, repository links, and working/staged diff checks.
- [x] After PR review/merge, record merge coordinates and completed work in the changelog. Promote implementation notes
  only after human review. Move B2 to `done/` after verification and closeout, repoint inbound links, and leave the epic
  active. Explicitly update the evidence path in the `src/forge/core/runtime/codex_preflight.py` comment and the B2
  evidence link in `docs/design_session_execution.md` §I.3; the Markdown link check does not inspect Python comments.
- [x] Verify the fixture process sweep is empty. Record the host-check limitation: no whole-round host-file hash
  baseline was captured, so byte-for-byte equality is unverified. Commands used isolated homes and did not copy host
  auth. Remove only the fixture-owned login store at final teardown; do not restore a stale auth copy or run host
  logout. Retain sanitized evidence and the runtime identity record before cleaning raw captures and fixture state.
  Host-file equality is not evidence of account-session validity.

## Execution record

2026-10-08 planning: inspected the card, epic, board contract, current responder, harness registration/auth/timeout
helpers, preflight constants, QA matrix, and existing test owners. Product code, runtime registrations, credentials, and
validation ceilings are unchanged. `make pre-commit-md` passes after formatting; the repository link audit passes for
645 Markdown sources, and working-tree/staged `git diff --check` pass. Only activation assertions are complete.

2026-10-09 review correction: the installed executable is `/opt/homebrew/Caskroom/codex/0.161.0/bin/codex`, SHA-256
`12ac11d2c7eee27cfae34393986d7b7c9ed0dea537cb749831cdd7033893e6de`. Homebrew's metadata timestamp is
`20261008193407.902` (2026-10-08 21:34 Europe/Berlin); only the 0.161.0 cask remains. The earlier planning pass had
checked Forge's constants but not this binary. Selection now follows the installed version at round start; a retained
copy and stage evidence remain pending.

`runtime.json` names `~/.local/bin/forge`, resolving to the uv-tool 1.0.2 installation. Its B1 reviewer-admission and
attempt modules are absent, and tag `v1.0.2` does not contain `56d4b8f5`. The checklist now requires checkout dispatch
provenance, admitted reviewer stubs, independent fixture login, the missing preflight/enrollment/usage assertions,
enrollment-aware budgets, a ceiling-only QA update, and cleanup across detached groups. GNU coreutils `timeout` 9.11 is
installed, but `with_timeout` supplies no KILL escalation. Revision validation: `make pre-commit-md` passes after
formatting, including repository size and link checks; working-tree/staged `git diff --check` pass. No model turn or
auth mutation was performed during this correction.

2026-10-09 execution: retained Codex 0.161.0, completed the E1–E11 matrix, and recorded the ceiling-only decision in
[evidence/README.md](evidence/README.md). Stage 84's credential-deleting trap, weak login admission, and the smoke
integration's empty-home fixture were corrected; failed attempts are retained separately. TUI driver and concurrency
detector failures were rerun with completed controls. B3–B5 have explicit measured handoffs and remain proposed. Final
test, wheel, cleanup, and PR details are in [validation.md](evidence/validation.md). B2 stays active until merge.

2026-10-10 review follow-up: protected enrolled fixtures from baseline resets, retained custom-hook response outcomes,
fixed second-terminal environment and path redaction, moved auth regressions into the regression suite, and published
the missing helper sources, export selection and source-drift audit. Native feedback and Stop handoffs now describe the
observed message roles and evidence limits. Validation: 10,600 unit tests, 1,400 regression tests, 98 focused checks and
32 policy integration tests pass. Fresh committed-harness 88/97 captures await an independent fixture login; no new
model turn has been launched. See [the review validation record](evidence/validation.md#review-follow-up-2026-10-10).

## Merged closeout

[PR #261](https://github.com/hapa1i/multi-forge/pull/261) merged to `main` as `2a15c087ce988d4ae05a3617790c53940278bdbf`
at 2026-10-09 23:51:44 UTC (2026-10-10 Europe/Berlin). Its tree matches tested head
`29ee539ddf36640eaa3d4acceee26d13a772c13c`; all five GitHub checks passed. Local `main` fast-forwarded to that merge
before closeout.

The general Codex ceiling is 0.161.0. The blocking QA pin stays 0.149.1, its shared Claude/Codex provenance is
unchanged, and the independent proxy floor stays 0.141.0. The original live captures pre-date the committed harness; the
[source-drift audit](evidence/validation.md#harness-and-publication-provenance) remains part of every downstream claim.
The optional fresh stage 88 and 97 reruns were not performed before merge: fixture credentials had been removed at
teardown and no follow-up login was confirmed. They are recorded as unperformed checks, not passing evidence; the
reservation ledger remains 95/100. Live quota exhaustion, general concurrent-fork guarantees, and the earlier-turn
selector remain unverified. B5's parent-manifest isolation blocker remains explicit.

Moved B2 to `done/`, repaired inbound links and the Python evidence-path comment, and recorded completed work in the
[changelog](../../change_log.md#2026-10-10). Promoted reviewed probe-identity and hook-state lessons to the
[session implementation notes](../../impl_notes/sessions.md). The epic's B2 handoff and the B3-B5 cards point to the
completed evidence; the epic remains in `doing/` and those members remain proposed. Normative session design reflects
the ceiling-only change; no end-user setup or downstream feature contract changed. Historical JSON captures, B1's dated
handoff, and the epic research record are preserved.

Closeout validation: full `make pre-commit` passes after Markdown formatting, including size and secret checks.
`./scripts/check-markdown-links.py` passes for 647 Markdown sources; working-tree and staged `git diff --check` pass.
All 18 historical JSON/text artifacts remain byte-for-byte identical to the merged tree. The preflight Python AST is
unchanged. A repository search confirms the only remaining old B2 lane path is inside the preserved historical exporter
source in `helper-sources.json`. Existing changelog entries, implementation notes, B1's dated handoff, and epic research
remain unchanged. No new model turn or runtime test was needed for this documentation/comment closeout.
