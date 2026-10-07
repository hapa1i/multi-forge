# B1: Plan-file supervision execution checklist

Card: [plan-file supervision](card.md). Epic: [Codex supervisor](../epic_codex_supervisor/card.md). Branch:
`feat/plan-file-supervision`, based on `main` at `6e0d1f4c`.

## Current focus

Execution plan revised after source verification on 2026-10-07. Product implementation, auth probes, and inference
probes have not started. Phase 1 begins with non-inference auth isolation; fixture creation precedes the first resumed
reviewer compatibility probe and is recorded as a separate model turn.

B1 ships `forge policy supervisor set --plan <file>` without a planning target, for fresh Claude and Codex reviewers. It
also owns real model selection, isolation of existing Claude supervision, a whole-hook deadline, and durable review
outcomes. Host Claude executors are explicitly supported too; sidecar plan-file review is refused. B2 is not a product
prerequisite. The documentation partitions below precede normative updates. Model-visible allowed-action feedback, Stop
review, native Codex forks, Jev, and team supervision remain with their separate cards.

## Baseline and contracts

The activation pass checked these source seams at `6e0d1f4c`:

- [Policy operations](../../../../src/forge/core/ops/policy.py) require `target: str` and validate a Claude-backed
  session; lifecycle and cascade operations also use `resume_id` as a configured-state check.
- [Semantic supervision](../../../../src/forge/policy/semantic/supervisor.py) rejects missing `resume_id` before either
  runtime dispatch. Claude resumes in the planner's CWD; Codex already runs fresh with `sandbox="read-only"` in the
  action checkout, but passes `model=None`.
- [The Claude runner](../../../../src/forge/core/reactive/session_runner.py) adds no tool restriction and gives its
  output-format retry another full timeout. [Environment construction](../../../../src/forge/core/reactive/env.py)
  hydrates Forge credentials before bare-mode selection.
- [Supervisor configuration](../../../../src/forge/session/models.py) defaults to 45 seconds;
  [Codex registration](../../../../src/forge/install/codex_hooks.py) and the
  [Claude Write/Edit presets](../../../../src/forge/install/preset.py) use 60 seconds. Codex checks the exact timeout as
  part of registration identity. Signals, kill scope, and post-timeout tool disposition remain unprobed.
- Both executors use [shared registration](../../../../src/forge/cli/hooks/policy.py), and both hook commands also have
  their own `resume_id` early-exit check. Shared-predicate changes therefore affect Claude as well as Codex.
- [Billing resolution](../../../../src/forge/core/usage/billing.py) lets a resolvable key win over `claude-max`.
  [Shadow v4](../../../../src/forge/policy/semantic/shadow.py) already stores a plan snapshot/hash and `lane.model`, but
  no explicit source/auth policy or effective supervisor model/effort. Its
  [reader](../../../../src/forge/policy/semantic/shadow_runner.py) defaults missing/malformed lanes to Claude.
- [Status](../../../../src/forge/cli/policy.py) exposes configuration and lane facts; existing
  [activity aggregation](../../../../src/forge/core/ops/usage_summary.py) does not by itself establish visibility of a
  hook killed before outcome recording.

Read the [epic research](../epic_codex_supervisor/research.md) as dated evidence. Its Claude 2.1.291 / Codex 0.160.1
observations and auth-status experiments are not a completed inference, isolation, or billing guarantee. Implementation
follows [workflow policy ownership](../../../design_workflows.md#16-policy-state-and-ownership),
[runtime routing](../../../design_runtime.md#g-subprocess-routing-reference),
[Codex hook registration](../../../design_installation.md#c6-codex-hook-registration-hooks-codex-owned-half), and
[activity semantics](../../../design_telemetry.md#per-session-usage-read-surface).

## Phase 0: Activation

- [x] Create the B1 branch and move B1 plus its coordinating epic to `doing/`; keep B2-B5 proposed.
- [x] Inspect the setup, dispatch, credential, timeout, and status seams above and create the fixture-grounded plan.
- [x] Record passing documentation checks for the activation change.

## Selected decisions

- **Auth compatibility:** add supervisor-local `auth_mode`, exposed as `--auth-mode inherit|subscription-only`.
  Absent/`inherit` preserves existing credential selection and the billing rule for every consumer, including frozen
  `claude-max` supervisors. `subscription-only` is an explicit direct Claude/`claude-max` opt-in; reject incompatible
  runtime/proxy/backend choices. It is not inferred from the backend name. Changing this policy on a bound supervisor
  requires remove/reconfigure; an upgrade performs no conversion. Read-only enforcement still applies to both modes.
- **Resumed checkout:** keep the existing planner-CWD history lookup, add `--add-dir <absolute action checkout>`, and
  render action-file paths against that checkout. Prove correct reads and no writes in both directories. The flag only
  grants access; it does not select the right branch. If the combined boundary cannot be established, refuse the
  cross-checkout configuration. Current upstream cross-project resume documentation is recorded in the
  [research update](../epic_codex_supervisor/research.md#planning-verification-2026-10-07); it is not a tested shortcut.
- **Executor scope:** support plan-only and target-plus-plan review for host Claude Write/Edit and host Codex
  `apply_patch`, with either supported reviewer runtime. Refuse plan-file-backed review in sidecars, including inherited
  configurations. Also refuse subscription-only auth in sidecars; do not mount host login material or silently remap
  host plans. Preserve conversation-only sidecar review on its existing explicit route with the new read-only guard.
- **Lane boundary:** keep the shared `LaneRecord` format and other consumers' `allowed_lanes` semantics unchanged. B1
  may select concrete supervisor candidates and persist supervisor-owned options. If Phase 2 proves that a shared
  format/resolution change is necessary, stop that slice, create a separate epic member with its own checklist/PR, and
  record the dependency before proceeding. Do not hide a four-consumer migration inside B1.
- **Shadow compatibility:** introduce a versioned replay contract that freezes plan source, snapshot digest, concrete
  reviewer model/effort, and auth policy. New captures must represent the resolved default lane explicitly. Older
  candidates replay only when a deterministic conversion proves the complete contract; otherwise finalize unavailable
  without dispatch. Malformed/newer candidates never select a default lane or read current session config as a guess.

## Documentation prerequisites

The SHA-256-matched Opus cache reports `design_sessions.md` at 25,797 tokens and `design_runtime.md` at 24,978 on
2026-10-07. The checker warns above 25,000 and fails above 30,000; a green hard-limit check does not satisfy this plan.

- [ ] Complete [Partition the Session Design](../../doing/partition_session_design/card.md) and
  [Partition the Runtime Design](../../todo/partition_runtime_design/card.md) on separate documentation branches/PRs
  before B1's first normative design update. Phase 1 probes can proceed without these content moves.
- [ ] Bring the merged partitions into B1 and repoint its design references to the resulting owners. Require the
  lossless-content/link audits and at most 23,000 Opus tokens per partition; after B1 additions, every touched living
  design stays at or below 25,000. No target warning is pre-accepted as debt.

## Commit slices

Each slice carries its focused tests and the matching shipped-contract documentation after the partition prerequisites.
Keep one B1 PR with these reviewable commits; this table does not authorize another member on the same branch.

| Slice | Phase | Review concern                                                           |
| ----- | ----- | ------------------------------------------------------------------------ |
| S1    | 1     | Probe harness, fixture provenance, sanitized compatibility evidence      |
| S2    | 2     | Plan source, configured predicate, lifecycle, executor/sidecar admission |
| S3    | 2-3   | Explicit auth policy and backward-compatible billing selection           |
| S4    | 2-3   | Effective supervisor model/effort and supervisor-only lane validation    |
| S5    | 3     | Fresh/resumed read-only dispatch and action-checkout access              |
| S6    | 3     | Versioned shadow replay; refuse unverified route reconstruction          |
| S7    | 4     | Shared deadline, bounded retries, independent reviewer cleanup           |
| S8    | 5     | Durable attempts and status/activity readers                             |
| S9    | 6     | Integrated runtime/wheel evidence and documentation reconciliation       |

S3-S5 may use validated probe-only runner controls before production wiring. Keep intermediate commits testable; do not
expose a new mode before its admission and isolation guards land. A required shared-lane redesign leaves this sequence
as a separate member under the lane-boundary decision above.

## Phase 1: Establish auth and resumed-review feasibility

Complete these gates before choosing the production Claude isolation mechanism. Keep sanitized commands, versions,
selected metadata, and filesystem assertions with the card; never retain secrets or full auth-status responses.

- [ ] Record both runtime versions, flag composition, actual Claude Write/Edit hook timeouts, and Codex's exact trusted
  PreToolUse registration. Local help was rechecked for Claude 2.1.291; this is flag evidence only. Do not change
  registration bytes or a runtime validation ceiling to make a probe pass.
- [ ] Evaluate `claude auth status --json` without inference in the exact proposed supervisor child: same binary, final
  environment, working/config directories, and auth-relevant settings flags, after Forge dotenv/config loading.
  Demonstrate that dispatch cannot rebuild the environment and reintroduce stripped credentials afterward.
- [ ] Execute the auth-location matrix below with positive controls. Establish status/headless selection equivalence;
  unsupported or ambiguous combinations refuse before inference. An untrusted project ignoring its settings proves
  nothing about trusted settings isolation. Synthetic invalid credentials prove selection/refusal, not valid login.
- [ ] Create the real-history fixture as specified below. Make its resumed, forked, inspection-only review the **first
  supervisor inference compatibility probe** after creation. Keep planner and executor sentinels different; assert the
  executor sentinel is inspected and both directories' tracked/untracked files remain unchanged during review.
- [ ] Attempt new writes through file tools, Bash, MCP, and delegation under permissive `acceptEdits`/Bash settings.
  Verify the proposed built-in tool restriction, settings isolation, and MCP/customization restrictions together for
  fresh and resumed runs; a cooperative prompt is not enforcement evidence.
- [ ] If removing tool definitions breaks resume, compare supported deny/permission mechanisms that preserve history
  while blocking new writes. Record the selected fresh/resumed mechanisms separately if necessary; do not restore
  writable capabilities to make resume pass.
- [ ] Probe runtime-enforced hook expiry for **both executors** using sleeping fake reviewers and descendants. Record
  delivered signals, hook/reviewer PID and process-group survival, pipe closure, and whether the requested tool runs
  afterward. Exercise natural 60-second expiry plus injected hook-only and hook-group termination; missing terminal
  output is not evidence of cleanup or a deny. Pair disposable Docker runtime probes with macOS process-lifetime tests.
- [ ] Before and after the sole real-host auth scenario, compare supported non-secret login/account-source metadata and
  protected settings/config digests; retain only allowlisted metadata and equality results. Assert the same login
  remains usable and settings are unchanged. Do not repair a failed preservation check by logging the user in/out.

### Auth probe locations

| Cases                                                                             | Location                                               | Control                                             |
| --------------------------------------------------------------------------------- | ------------------------------------------------------ | --------------------------------------------------- |
| Env API/bearer/OAuth tokens; dotenv; Forge credential hydration                   | Unit fixtures, then Docker with disposable HOME/config | Synthetic values; no inference on negative routes   |
| User/project/local/explicit settings; `apiKeyHelper`                              | Docker with trusted disposable projects                | Loaded-source canaries; helper invocation count     |
| Cloud selectors, base URLs, subprocess proxies, federation/organization selectors | Docker with disposable HOME/config                     | Fake endpoints and recorded route selection         |
| Active/default profiles; stored Console credentials; missing/expired login        | Disposable Docker identity; test doubles for expiry    | Supported setup with disposable credentials only    |
| Managed settings and gateway policy                                               | Docker-owned policy paths and fake gateway             | Positive policy detection; no host admin writes     |
| macOS Keychain isolation/fallback                                                 | Separate disposable macOS user/VM                      | Separate Keychain; no access to maintainer identity |
| Positive subscription selection, fixture creation, and resumed/fresh review       | One real-host scenario with disposable workspaces      | Existing login untouched; before/after checks       |

Do not use a disposable `HOME` or `CLAUDE_CONFIG_DIR` alone as proof of Keychain/profile isolation. If a real
expired/profile/gateway case cannot be produced safely with disposable credentials, retain it as missing runtime
evidence and refuse that unverified auth combination. Never create expiration, revoke credentials, switch profiles, log
out, or install managed policy on the maintainer's account. Raw login tokens are neither read nor copied. Docker results
establish Linux behavior; they do not substitute for the Keychain-specific gate.

### Real-history fixture provenance

After the cleaned host auth preflight and the account-credits prerequisite, create a disposable Git repository at
`<probe-root>/planner` and a worktree at `<probe-root>/executor`. Use the same verified direct subscription child to
create a new native Claude conversation in the planner directory, with a recorded UUID. A minimal fixture-creation turn
performs a successful `Edit` on a pre-created fixture file and a successful harmless `Bash` operation inside that
directory. Verify the native tool results, not just the assistant's claim. Record the creation call and billing posture
separately; it deliberately uses fixture-write permissions and is not a supervisor compatibility result.

Resume that UUID from the same planner directory with `--fork-session`, the proposed inspection-only controls, and
`--add-dir <probe-root>/executor`. Preserve the original native transcript and directory identity until the probe is
complete; a synthetic or manually relocated transcript is not the fixture. Keep raw captures outside the repository and
commit only sanitized provenance/evidence. Later paid Docker fixtures recreate real history independently and are
labelled API-route evidence.

The environment cases include `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, `CLAUDE_CODE_OAUTH_TOKEN`, all three
cloud-provider selectors, `ANTHROPIC_PROFILE`, federation/organization selectors, and inherited Forge/base-URL routing.
Exercise with and without `.env`, including a key loaded after an earlier clean shell-status check.

**Gate:** effective-auth equivalence and resumed read-only compatibility remain unproven. A failed or inconclusive probe
keeps the affected production path unavailable until a supported mechanism is established. Account usage credits must be
disabled for the intended everyday subscription exercise; Forge cannot inspect that account condition. Subscription
evidence uses the user's unmodified published CLI and its login, without reading or copying login tokens.

## Phase 2: Plan source, lifecycle, and reviewer identity

- [ ] Define shared configured/active predicates for conversation and plan-file sources. Distinguish absent,
  configured-but-suspended, active, and configured-but-unusable states. Replace semantic-supervisor presence checks in
  hooks, lifecycle/status, on-demand evaluation, cascade, shadow capture/replay, and session-context presentation;
  retain source-specific conversation/dependent-session queries and separate team-supervisor semantics.
- [ ] Make the `set` target optional only with `--plan`. Resolve paths relative to the command CWD, store the absolute
  source, and validate missing, empty, unreadable, non-file, or incompatible inputs before configuration or proxy
  mutation. Preserve existing state on invalid setup, including frozen lanes and overrides.
- [ ] Apply the executor-scope decision at configuration and managed launch, then recheck actual hook execution context.
  Test host Claude Write/Edit and host Codex `apply_patch`; a shared predicate must not enable sidecar plan-file review
  implicitly. Refuse known unsupported setup before mutation; inherited/bypassed configurations report unavailable
  without spawning, preserving ordinary policy failure behavior and the earlier authority guard.
- [ ] Add the explicit auth policy with absent=`inherit` compatibility. Prove an existing frozen `claude-max` supervisor
  with a resolvable key still uses and reports API auth after upgrade; explicit subscription-only configuration changes
  require the documented reset. Preserve all three auxiliary consumers and reject subscription-only sidecar setup.
- [ ] Preserve target-plus-plan semantics: the explicit plan supersedes the conversation's plan, while the target
  remains available as conversation context. Plan-only setup never resolves, registers, or fabricates a Claude UUID.
- [ ] Preserve the live-file override behavior explicitly: load one plan snapshot per review, hash the bytes used in the
  prompt, and use that same identity for caching and outcome evidence. Test same-size edits with restored mtimes. An
  explicit plan disappearing or becoming unreadable yields unavailable review, not fallback to stale context.
- [ ] Define bare reload for plan-only configuration to revalidate its stored source; `reload --from` replaces it
  atomically. Keep the existing approved-snapshot search for conversation sources. Test reload while suspended and
  configuration survival across ordinary resume and existing derivation paths.
- [ ] Add an explicit supervisor model setting and runtime-aware effort validation. Resolve the model used by each
  subprocess; reject incompatible runtime/backend/model/effort/proxy combinations. Preserve proxy-owned tier mappings
  and validate selected alternatives without changing saved proxy configuration. Define legacy decoding explicitly: an
  old nominal lane model is not proof of an earlier explicit model choice or permission to repin a frozen lane.
- [ ] Make model identity agree across argv, lane selection, cache keys, status, and telemetry. Keep requested/resolved
  identity separate from observed runtime identity when observations are unavailable. Reconcile the current finite
  supervisor candidates without changing the common `LaneRecord` schema or other consumers. Apply the separate-member
  gate if this cannot satisfy the model contract; do not store a model that dispatch ignores.
- [ ] Preserve confirmed-first lane resolution, first-registered-check freezing, and the under-lock stale-write guard.
  Changing a frozen model/runtime/backend must follow the same refusal/reset rules as changing the lane; cache-only and
  cascade-only checks still preserve the existing freeze trigger.
- [ ] Extend terminal commands through UI-free policy ops and keep existing `%policy` lifecycle behavior consistent.
  Define plan/model parity for direct setup if exposed; keep Codex launch `--supervise` parity outside this card.
  Specify whether one-shot `evaluate` accepts a plan directly without changing its documented three-way exit contract.

**Decision to settle in this phase:** the supervisor-local source/model representation, strict legacy decoding, and the
one-shot/direct setup option shape. Preserve valid existing conversation configurations; do not mechanically rewrite
every `resume_id` reference. The optional source-only feedback mode may be implemented for covered deny feedback here or
explicitly deferred to B3; any implementation must validate quotations against the exact plan snapshot and suppress
generated explanations/fixes from executor context without claiming a watermark property.

## Phase 3: Isolated runtime dispatch and billing route

- [ ] Run plan-only Claude fresh, without resume/fork flags, in `context.repo_root`. Feed the approved snapshot in-band
  and use the Phase 1 inspection-only mechanism. Keep existing conversation-backed review functional and preserve its
  source conversation. For resumed/target-plus-plan review, add the action checkout, render absolute action paths, and
  prove inspection of its sentinel plus write prevention in both directories, including added-directory customizations.
- [ ] Support plan-only `--runtime codex` through the existing fresh read-only invoker. Pass the selected model and
  supported effort instead of nominal lane metadata; report cold/stale/unready preflight as unavailable with the
  existing refresh command, without probing Codex readiness inside the hook.
- [ ] Make explicit `--auth-mode subscription-only` select the guarded direct Claude/`claude-max` child path. In that
  mode skip Forge credential hydration, remove competing auth/routing selectors, skip user/project/local settings, and
  reject unverified managed settings or gateways. Keep the proof and argv/environment construction together; `--bare`
  cannot provide this login path.
- [ ] For the subscription-only mode, run auth preflight inside the invocation budget before inference. Accept only
  verified CLI-managed subscription metadata using an allowlist of `loggedIn`, `authMethod`, `apiProvider`, conditional
  `apiKeySource`, and optional `subscriptionType`; missing optional plan metadata alone is not failure, and its presence
  is not billing proof.
- [ ] Keep explicitly selected paid direct/proxy modes available with the same read-only boundary. Refuse conflicting
  subscription/proxy/cloud selectors before starting a proxy or reviewer. Everyday subscription supervision leaves the
  API checker off; an API cascade or other paid operation requires explicit route selection.
- [ ] On quota/auth failure, record unavailable review without an API retry. Reconcile the existing Codex-to-Claude
  degrade overlay with the selected auth policy: inherited configurations keep their documented behavior, while an
  opted-in configuration cannot lose its guard through fallback. Subscription-only is Claude-only in B1 and refuses an
  incompatible Codex lane. Preserve overlay visibility, reset semantics, and frozen-lane provenance.
- [ ] Version shadow capture/reconstruction together. Freeze explicit source, exact plan bytes/hash, effective
  supervisor model/effort, auth policy, and resolved lane; validate schema versions and snapshot integrity. Missing or
  malformed lane/auth/source data must not default to `anthropic-direct`, hydrate an API key, or read mutable live
  config. Test older records and finalization without dispatch, plus a valid explicit inherited paid-route control.
- [ ] Preserve depth/recursion suppression, run-tree attribution, verdict parsing, and the high-confidence/cited deny
  threshold. Runtime/setup/parse failures remain failures, not aligned verdicts or cached allows.
- [ ] Preserve one usage emitter per actual model call: Claude's dispatch emitter, Codex's invoker emitter, and the
  shadow worker's existing ownership. Base billing classification on the final child route; an ambient parent key must
  not relabel the isolated subscription child, and unknown usage/cost must not become zero.
- [ ] Add opt-in runner controls without changing unrelated memory/team/workflow callers. Correct stale comments only
  where touched behavior changes, and run the adjacent runner/environment contracts.
- [ ] Add a failing-then-passing regression for the shipped unrestricted resumed reviewer. Pair argv/runner assertions
  with real-runtime adversarial writes; the absence of a requested write alone is not an isolation assertion.

## Phase 4: Whole-hook deadline and cancellation

- [ ] Establish one monotonic deadline at the hook entry and reserve a measured completion margin. Thread remaining time
  through all normalized files, deterministic setup, auth preflight, tier-1 checker, frontier calls, retries,
  cancellation, and durable finalization; neither a new file nor escalation resets the budget.
- [ ] Validate positive reviewer limits against the executor's actual supported hook registration at setup and again at
  dispatch. Cover generic session overrides and stale saved configuration, not only `supervisor set --timeout`. Do not
  silently increase either executor's hook timeout or rewrite Codex's trusted registration.
- [ ] Stop scheduling when the remaining budget cannot support a stage and finalization. Preserve deterministic deny
  precedence and the established supervisor fail-open policy while recording exactly which review work is incomplete.
- [ ] Bound output-format negotiation retries by remaining time; do not retry unsupported effort at a default effort.
  Add a failing-then-passing regression for the shipped double-timeout retry, including separate hook processes whose
  capability latches start empty. Test cumulative multi-file/cascade time with a controlled clock and sleeping children.
- [ ] Implement and prove the watchdog design below for each supported executor. Test natural expiry, hook-only SIGKILL,
  original-process-group kill, reviewer grandchildren, a hung termination handler, and completion/kill races. A killed
  hook leaves incomplete evidence and no reviewer running past the watchdog's bounded cleanup grace.

**Selected cleanup design, subject to Phase 1 proof:** a separate-session watchdog owns reviewer creation, the reviewer
process group, and an absolute monotonic deadline. Arm it before spawning the reviewer. It watches a hook-owned control
pipe; EOF or deadline initiates group termination, a bounded grace period, then force-kill and reaping. The reviewer
must not inherit a writer that masks hook death. Cleanup cannot depend on code running in the killed hook or on a macOS
parent-death signal. Capture process identity safely to avoid PID-reuse mistakes. If runtime teardown kills the watchdog
while leaving its reviewer alive, this design fails the gate and needs executor-specific containment before shipping.

Set the numeric completion reserve and termination grace from measurements. Manual evaluation and deferred shadow work
arm their own explicit deadlines. The process-local JSON-capability latch does not protect a later hook process;
regression coverage starts fresh processes and proves a negotiation retry consumes remaining time, not another full
45-second budget.

## Phase 5: Durable attempt evidence and operator read surfaces

- [ ] Choose the durable attempt owner using existing session/telemetry storage where compatible. Persist identity
  before dispatch: session/root run, hook/action, plan digest, reviewer route/model/auth policy, start time, and budget.
  Define the append/finalization failure policy; missing required evidence cannot silently produce a successful review
  claim.
- [ ] Record terminal completed/unavailable outcomes separately from the alignment verdict. Detect live pending versus
  interrupted/incomplete attempts using supported liveness/deadline evidence; never invent a terminal verdict for an
  attempt whose hook died. Cover concurrent hooks, late completion, and repeated read/recovery.
- [ ] Keep cache hits, no-call auth refusals, parse failures, quota exhaustion, and partial multi-file completion
  distinguishable. Correlate attempts with existing usage/upstream outcomes without duplicate calls or costs; preserve
  unknown cost for dispatched work lacking final usage.
- [ ] Extend `forge policy supervisor status [--json]` and shared policy status JSON with the latest review state,
  reason, time, and source/model identity. Preserve suspended/unusable configuration visibility and read-only behavior;
  successful JSON stays one stable stdout object, diagnostics stay on stderr.
- [ ] Extend `forge telemetry activity [session]` to show unavailable/incomplete attempts, including the killed-hook
  case with no usage row. Deduplicate existing failure events and preserve operation-versus-model-call counts.
- [ ] Cover attempt artifacts in existing session retention/delete and telemetry-reset ownership rules; do not leave
  stale derived status after its underlying records are reset. Document the selected owner and read semantics.

## Acceptance tests

Paths marked **new** are planned test owners; add them when implementing the corresponding phase. Other paths are
existing owners to extend. Indexed-session fixtures use `tests.fixtures.session_state`; corrupt-state fixtures explain
the intentionally broken invariant. Each fixed baseline defect gets a failing-then-passing regression.

| Test                         | Fixture                                                                                     | Assertion                                                                                                                           | Test file                                                                                                                  |
| ---------------------------- | ------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| Plan-only lifecycle          | Published host Claude/Codex sessions; absolute plan; no target                              | Set/status/off/on/reload/remove; no UUID lookup                                                                                     | `tests/src/core/ops/test_policy_ops.py`, `tests/src/cli/test_policy_supervisor.py`                                         |
| Invalid setup                | Existing supervisor; bad path/options                                                       | Manifest/lane/proxy state preserved                                                                                                 | `tests/src/core/ops/test_policy_ops.py`                                                                                    |
| Presence predicate           | Plan/target/absent/suspended/unusable states                                                | Consistent hook, cascade, shadow, and status behavior                                                                               | `tests/src/policy/semantic/test_supervisor.py`, `test_plan_check.py`, `test_shadow.py`                                     |
| Source precedence            | Target plus plan; changed/missing plan                                                      | Explicit snapshot authoritative; unavailable on loss                                                                                | `tests/src/policy/semantic/test_supervisor.py`                                                                             |
| Content identity             | Equal-size replacement; restored mtime                                                      | Changed digest; no stale frontier/checker allow                                                                                     | `tests/regression/test_bug_b1_plan_content_identity.py` (**new**)                                                          |
| Resume and lane freeze       | Coherent sessions; concurrent repin                                                         | Persisted source; exact frozen dispatch identity                                                                                    | `tests/src/session/test_consumer_lanes.py`, `tests/src/cli/test_consumer_lane_freeze.py`                                   |
| Auth compatibility           | Existing frozen `claude-max` supervisor plus key; absent auth mode; all four consumers      | Key still selects API; opt-in requires explicit reset; other consumers unchanged                                                    | `tests/src/cli/test_consumer_lane_freeze.py`, `tests/src/cli/test_session_lane.py`, `tests/src/core/usage/test_billing.py` |
| Model and effort             | Both runtimes; paid proxy alternative                                                       | Actual argv and attribution agree; invalid pairs refuse                                                                             | `tests/src/policy/semantic/test_supervisor.py`                                                                             |
| Fresh and legacy Claude      | Real Edit/Bash history created in recorded planner CWD; separate setup turn                 | Fresh/resumed read-only review; source history preserved; route-labelled evidence                                                   | `tests/integration/docker/test_real_claude_supervisor.py`; Phase 1 provenance                                              |
| Host Claude executor         | Write/Edit; plan-only and target-plus-plan; both reviewer runtimes                          | Shared hook registers and reviews; aligned/denied actions behave as specified                                                       | `tests/src/cli/hooks/test_policy_check_cascade.py`, `tests/integration/docker/test_plan_file_supervision.py` (**new**)     |
| Sidecar admission            | Plan-only/target-plus-plan/subscription-only setup and inherited config; no host plan/login | Setup refuses atomically; dispatch records unavailable with no reviewer; conversation-only explicit-route control remains read-only | `tests/src/core/ops/test_policy_ops.py`, `tests/integration/sidecar/test_sidecar_hook_inject.py`                           |
| Fresh Codex reviewer         | Plan-only config; ready/stale preflight                                                     | Read-only action CWD; selected model; no implicit fallback                                                                          | `tests/src/policy/semantic/test_supervisor.py`, `tests/integration/docker/test_plan_file_supervision.py` (**new**)         |
| Auth isolation               | Phase 1 location matrix; trusted settings; positive controls                                | Opt-in preflight/dispatch agree; no paid fallback; real login/settings unchanged                                                    | `tests/src/core/reactive/test_supervisor_auth.py` (**new**); isolated runtime and host evidence                            |
| Late dotenv injection        | Clean shell status; CLI loads synthetic key                                                 | Opted-in child stays isolated; inherited consumers retain intended hydration                                                        | `tests/src/core/reactive/test_supervisor_auth.py` (**new**), `tests/src/core/reactive/test_env.py`                         |
| Unrestricted legacy reviewer | Resumed Claude supervisor with permissive settings                                          | Baseline write-capable launch reproduced; fixed runner enforces inspection-only access                                              | `tests/regression/test_bug_b1_supervisor_write_access.py` (**new**); real-runtime adversarial tests                        |
| Adversarial writes           | Permissive settings; tools/MCP/delegation attempts                                          | Tracked/untracked files unchanged; real denial evidence                                                                             | `tests/integration/docker/test_plan_file_supervision.py` (**new**); Phase 1 host evidence                                  |
| Actual checkout              | Planner plus executor worktree with different sentinels; fresh and resumed target-plus-plan | Executor file read via absolute path; both directories resist writes, including added-directory customizations                      | `tests/integration/docker/test_plan_file_supervision.py` (**new**)                                                         |
| Trusted Codex enforcement    | Aligned and clearly divergent patches                                                       | Aligned patch lands; divergent patch does not                                                                                       | `tests/integration/docker/test_plan_file_supervision.py` (**new**); hands-on run                                           |
| Deadline admission           | Both executors; oversized timeout; changed registration                                     | Actionable refusal before dispatch                                                                                                  | `tests/src/core/ops/test_policy_ops.py`, `tests/src/cli/hooks/test_codex_policy_check.py`, `test_policy_check_cascade.py`  |
| Cumulative deadline          | Multiple files; checker escalation; JSON retry                                              | One budget; bounded cancellation/finalization                                                                                       | `tests/src/core/reactive/test_session_runner.py`, `tests/src/cli/hooks/test_codex_policy_check.py`                         |
| Retry deadline defect        | Fresh hook processes; unsupported output format followed by sleeping retry                  | Retry uses remaining budget; a new process cannot spend 45 seconds twice                                                            | `tests/regression/test_bug_b1_supervisor_retry_deadline.py` (**new**), `tests/src/core/reactive/test_headless_json.py`     |
| Killed hook                  | Both executors; natural 60-second expiry; hook-only/group kill; child and grandchild        | Signals, survival and subsequent tool disposition captured; watchdog bounds cleanup; incomplete evidence without invented usage     | `tests/integration/docker/test_plan_file_supervision.py` (**new**); macOS process-lifetime harness                         |
| Quota and degrade            | Explicit subscription-only reviewer fails; parent has key; inherited Codex degrade control  | Opt-in never falls back to API; legacy explicit-route behavior and billing preserved                                                | `tests/src/policy/test_supervisor_lane_degrade.py`, `tests/src/core/usage/test_billing.py`                                 |
| Shadow reconstruction        | New complete record; older/malformed/newer schemas; key in ambient env                      | Frozen source/model/auth replayed; unverified contract finalized unavailable with no dispatch; explicit paid control works          | `tests/src/policy/semantic/test_shadow.py`, `tests/src/policy/semantic/test_shadow_runner.py`                              |
| Policy composition           | Deterministic deny; low confidence; malformed verdict                                       | Existing deny bar and failure behavior retained                                                                                     | `tests/src/policy/semantic/test_supervisor.py`, `test_verdict.py`                                                          |
| Outcome visibility           | Completed/unavailable/incomplete; concurrent attempts                                       | Latest state/reason/time; deduplicated activity                                                                                     | `tests/src/core/ops/test_usage_summary.py`, `tests/src/cli/test_activity.py`, `test_policy_supervisor.py`                  |
| Recursion and usage          | Nested hooks; shadow replay; both runtimes                                                  | No recursive review; one usage row per call                                                                                         | `tests/src/policy/semantic/test_shadow_runner.py`, `test_supervisor.py`                                                    |
| CLI streams                  | Human/JSON status; invalid configuration                                                    | Results stdout; diagnostics stderr; stable shape                                                                                    | `tests/src/cli/test_output_streams.py`                                                                                     |

The Codex enforcement claim covers the existing adapter's supported `apply_patch` operations. Shell writes and
deletion-only patches skipped by that adapter are not supervised by this feature. Runtime capability claims require
filesystem/structured evidence; a model saying it complied is insufficient. If source-only feedback is included, add
fabricated-quotation and generated-text leakage fixtures before marking it complete.

## Phase 6: Integration, documentation, and final verification

- [ ] Run focused tests after `make deps` and targeted integration as the affected slices land. Extend the existing
  supervisor and policy-CLI suites plus the new plan-file suite; do not defer hook/auth/runtime integration to closeout.
- [ ] Reuse or extract the trusted-config hash recreation from `tests/integration/docker/test_real_authority.py`
  (`_codex_identity_config` / `_prepare_real_codex`) into a shared fixture. Preserve original absolute config paths,
  disposable identities, and existing authority tests. Do not copy native `auth.json`, reenroll the maintainer, or give
  supervisor fixtures an authority marker to obtain read-only behavior.
- [ ] Run the current-version trusted Codex allow/deny and cross-checkout tests, plus fresh/resumed Claude and fresh
  Codex write-refusal tests. Include host Claude Write/Edit execution and sidecar refusal/legacy controls. Keep
  subscription-host evidence separate from explicitly paid Docker tests; do not copy native login tokens into Docker or
  present an API-key Docker run as subscription evidence.
- [ ] Complete one explicitly selected Claude subscription review under the documented account condition. Inspect
  runtime/model/billing attribution and preserve the no-invoice/no-measured-quota limitation. Verify missing/expired
  login and quota failures in the isolated locations, and existing Claude-target supervision under the new restrictions.
- [ ] Exercise `forge session lane set|show|clear --consumer <consumer>` for **all four** consumers: `supervisor`,
  `memory_writer`, `shadow_curation`, and `team_supervisor`. Verify inherited key/API, keyless direct subscription, and
  proxy/unknown billing controls plus the supervisor-only opt-in; preserve each consumer's freeze rules.
- [ ] Exercise `forge policy supervisor status --json`, `forge telemetry activity <session>`, and both
  `forge policy check --bundle coding_standards --file <path>` and
  `git diff | forge policy check --bundle coding_standards --diff` to preserve surrounding operator contracts.
- [ ] After both documentation partitions, update `AGENTS.md`, the relocated owner of `docs/design_runtime.md` §G, and
  `docs/design_telemetry.md` §3.14 and §A.13 explicitly. Keep the resolvable-key rule for inherited routes/all four
  consumers and describe the supervisor opt-in's final child route; do not redefine `claude-max` globally.
- [ ] Update `docs/design_workflows.md`, the new session/runtime owners, installation guidance, and
  `docs/cli_reference.md` as their changes ship. Update `docs/end-user/policy.md` and `docs/end-user/session.md` with
  plan/model/auth setup, credits prerequisite, sidecar refusal, hook cleanup, and recovery. Migration notes must say
  existing frozen bindings keep inherited auth; opting in requires remove/reconfigure. Explain sidecar plan refusal for
  pre-existing/inherited configurations and the disposition of old shadow records.
- [ ] Run `make test-unit`, `make test-regression`, and `make pre-commit` on the final implementation. Record counts,
  failures, and limitations with the tested head; fix failures rather than skipping tests.
- [ ] Run `make build` and verify plan-only configuration/status and packaged runtime behavior from a clean wheel.
  Exercise extension doctor/user hook setup/project setup if registration or installer ownership changes. Run
  `./scripts/test-wheel-runtime.sh` if the proxy dependency set or LiteLLM compatibility changes.
- [ ] Run the repository Markdown-link and file-size checks plus `git diff --check`; confirm the epic and sibling
  dependencies still describe what B1 actually ships. Refresh content-matched Opus counts for touched living designs;
  every document must meet the 25,000 target, even when the checker only warns.

Targeted integration entry points (extend selectors as fixtures are implemented):

```bash
./scripts/test-integration.sh tests/integration/cli/test_policy_cli_contract_integration.py
./scripts/test-integration.sh tests/integration/docker/test_supervisor_e2e.py tests/integration/docker/test_real_claude_supervisor.py
./scripts/test-integration.sh tests/integration/docker/test_plan_file_supervision.py
./scripts/test-integration.sh tests/integration/sidecar/test_sidecar_hook_inject.py
```

The plan-file suite is planned above. Real-runtime prerequisites and any paid route must be identified before those
runs; credentials or fixtures missing from a run are recorded as missing evidence, not a pass.

## Closeout

- [ ] Review the final implementation against every required acceptance assertion and resolve the Phase 1 gates and
  inline decisions. Record the explicit disposition of the optional source-only mode.
- [ ] Commit by reviewable intent and open a B1 PR with the actual behavior, verification commands, and material limits.
- [ ] Verify merge/check results against the tested tree and synchronize normative/end-user docs.
- [ ] Record completed work in `docs/board/change_log.md`; propose only durable lessons for human review before updating
  the relevant implementation-note ledger.
- [ ] Move B1 to `done/`, repoint inbound links, and update the epic's next-member decision. Keep the epic active until
  its coordinated outcome is shipped and verified.

## Execution evidence

2026-10-06: planning activation only. Source inspection establishes the baseline above; no product tests, auth checks,
or model calls have run for B1. `make pre-commit-md` passes, including file-size limits;
`./scripts/check-markdown-links.py` passes for 635 Markdown sources; working-tree and staged `git diff --check` pass.

2026-10-07: revised the plan after verifying the twelve review points against source, cached document hashes/counts,
Claude 2.1.291 help, and current upstream documentation. No product implementation, auth-status calls, or inference
probes ran in this revision. `make pre-commit-md` passes after reviewing formatter-only changes; the standalone link
audit passes for 636 Markdown sources, and working-tree/staged diff checks pass. Runtime gates remain unchecked.
