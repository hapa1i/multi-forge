# Plan-file supervision with a fresh `claude -p`

Epic: [Codex supervisor](../../doing/epic_codex_supervisor/card.md). Member **B1**, first product card. No product-card
prerequisite; [B2](../../done/codex_0160_validation/card.md) can proceed alongside it. The
[session](../../done/partition_session_design/card.md) and [runtime](../../done/partition_runtime_design/card.md) design
partitions precede B1's normative documentation updates.

Status: **done**, 2026-10-08. [PR #260](https://github.com/hapa1i/multi-forge/pull/260) merged into the runtime
partition [#259](https://github.com/hapa1i/multi-forge/pull/259); the stack reached `main` through
[#258](https://github.com/hapa1i/multi-forge/pull/258) as `56d4b8f5`. The [closeout](checklist.md#merged-closeout) and
[retained evidence](evidence/README.md) record passing checks and runtime limits. Optional source-only feedback is
deferred to B3.

## Problem and outcome

Supervisor setup currently requires a Claude planning conversation even when an approved plan file already exists. Allow
`forge policy supervisor set --plan <file>` without a target, then supervise a Codex executor through a fresh, read-only
`claude -p` invocation. Add an enforced read-only boundary; the existing Claude supervisor does not have one. The
everyday route uses the user's Claude login without paid fallback, conditional on usage credits being disabled on the
account. Subscription-only auth is a separate explicit opt-in; existing `claude-max` bindings retain their inherited
credential selection and billing semantics. Explicit paid routes remain available for complex projects.

The existing Codex `apply_patch` deny path is the enforcement boundary. This card does not depend on new Codex fork,
background-hook, or model-visible warning behavior. It does require its own current-runtime deadline and isolation
tests. Verified source pointers and billing qualifications are in the
[epic research](../../doing/epic_codex_supervisor/research.md).

## Scope

- Introduce one shared semantic-supervisor configured/active predicate that understands conversation-backed and
  plan-file-backed configurations. Apply it to hooks, evaluation, status, lifecycle, cascade and shadow entry points.
  Keep genuine conversation lookup and dependent-session queries source-specific; do not invent a dummy `resume_id`.
- Make the CLI target optional when `--plan` is supplied. Resolve and validate the plan path, persist its source, and
  define reload/change behavior with content identity so cache entries cannot survive a changed plan unnoticed. Diagnose
  absent, empty, unreadable, or incompatible inputs before mutating configuration. Specify the meaning of target plus
  `--plan` consistently with existing plan overrides.
- Run fresh Claude with the approved plan in the prompt, without resume/fork arguments, in the **action's checkout**.
  Preserve recursion/depth controls, verdict validation and single usage emission. Keep conversation-backed supervision
  supported and read-only; its auth restriction applies only when separately opted in. Resumed review, including
  target-plus-plan, keeps planner-CWD lookup and passes `--add-dir <action checkout>` with absolute action paths. Prove
  inspection of the executor sentinel and write prevention in both directories; access alone does not choose the correct
  file context.
- Support plan-only supervision for both host Claude Write/Edit and host Codex `apply_patch` executors, with either
  supported reviewer runtime. Refuse plan-file review in a sidecar at setup/launch and guard inherited configurations at
  dispatch. Do not assume that a host plan path or subscription login exists inside the container.
- Support `--plan <file> --runtime codex` without a target through the existing fresh, read-only Codex reviewer. Keep
  runtime/backend selection explicit and validate model/effort capabilities; reject incompatible options rather than
  ignoring them. This does not introduce native forks or require B5.
- Add an explicit supervisor model setting. Pass the selected model to the subprocess and keep actual model identity,
  effort validation, lane binding/freeze rules, cache identity, status and telemetry consistent. Do not add a setting
  that changes only a nominal lane record. Changes to the shared lane format or other consumers' resolution semantics
  belong in a separately accepted epic member, not this card.
- Version shadow candidates to freeze source, concrete reviewer model/effort, and auth policy along with existing plan
  snapshots and lane identity. Invalid or insufficient old records finalize visibly without a model call; never recover
  an unverified replay route by choosing the default paid-capable lane.
- Optionally support source-only feedback: validated plan passages plus fixed Forge diagnostics, omitting Claude's
  generated explanation and suggested fix from Codex's context. Source validation must reject fabricated quotations.
  This option makes no watermark guarantee.
- Correct stale runtime comments in the touched launch/supervisor code. Update workflow, session, CLI and end-user
  policy/lane documentation when the behavior ships.

## Isolation and subscription-only dispatch

- A supervisor-local auth opt-in defaults to inherited behavior when absent. Keep existing frozen `claude-max` bindings
  and all three auxiliary consumers unchanged. An explicit change of auth policy after supervisor binding requires
  remove/reconfigure; migration guidance distinguishes that action from merely upgrading Forge.
- Restrict both fresh and resumed Claude supervisors to an explicit read-only tool set. On the installed 2.1.291,
  `--tools` can limit built-ins to inspection tools such as `Read`, `Glob` and `Grep`. Disable MCP, delegation and
  executable customizations that could bypass that set. Verify the combined flags against the supported binary.
- `--restricted` is useful settings isolation, but is not itself read-only: file-edit tools remain, and managed settings
  and explicitly supplied settings still apply. Add the actual tool restriction. Do not rely on the prompt, permission
  defaults, or Forge's authority hook, which requires a separately enrolled authority-marked session.
- Build a subscription-only child environment without hydrating Forge API credentials. Clear competing auth/routing
  selectors and skip user, project and local settings. Cover cloud-provider flags, `ANTHROPIC_AUTH_TOKEN`,
  `ANTHROPIC_API_KEY`, `apiKeyHelper`, `CLAUDE_CODE_OAUTH_TOKEN`, profile/federation selection and inherited proxy/base
  URLs. Reject managed settings, a configured gateway, or an unverified effective auth source in this mode. Inspect only
  non-secret metadata exposed through supported interfaces; never read Claude login tokens.
- Evaluate `claude auth status --json` as the preflight interface. Run it with the supervisor's exact child environment,
  binary, working directory, config directory and auth-relevant settings flags. Prove that it honors the selected
  settings isolation and matches headless credential selection. Run it after Forge's dotenv/configuration loading and
  credential resolution; later dispatch must not reintroduce stripped credentials. Fail on an unverified source,
  malformed result or failed check, within the shared deadline.
- Require evidence that the selected configuration uses the user's CLI-managed subscription login. Include active and
  default profiles, stored Console credentials and expired/missing-login fallback in the checks; an unset
  `ANTHROPIC_PROFILE` is insufficient. An explicit OAuth token can itself represent a subscription, but this mode
  deliberately accepts only the CLI-managed login. `--bare` is unsuitable because it disables OAuth login.
- Parse `loggedIn`, `authMethod`, `apiProvider` and conditional `apiKeySource`; allowlist recorded metadata instead of
  retaining the whole response. The tested login response also includes `subscriptionType`, while the API-key response
  omits it. Treat any plan field as reported metadata, not credential validity or proof of current billing. Keep the
  explicit `claude-max` lane declaration and account usage-credits condition.
- Refuse ambiguous or incompatible auth before inference, and never retry on an API route after quota/auth failure.
  Apply this to any runtime-degrade fallback as well. Per-run selection leaves the unmodified binary's authentication
  options available for other modes. `--backend claude-max` is not a spending guarantee.
- Document **usage credits disabled on the Claude account** as a user-side prerequisite. Forge cannot verify that
  account condition or promise future billing policy. Distinguish this condition from checks Forge actually enforces.

## Deadline and unavailable-review contract

The Claude policy-check presets and Codex PreToolUse registration use 60-second timeouts. Probe the signal,
process/group scope, descendant survival, and subsequent tool disposition for both executors. Validate setup and
dispatch against the executor's actual supported hook registration. Budget the whole invocation: startup, all files,
checker/reviewer calls, retries, cancellation and durable recording. A per-review timeout below 60 seconds alone is
insufficient. Keep a completion margin, reject an oversized configured timeout, and stop scheduling reviews when the
remaining budget is exhausted. Changing Codex's hook timeout requires enrollment of the changed trusted registration; do
not raise either timeout silently. The execution checklist selects an independently running deadline watchdog to own
reviewer cleanup; its survival and process-group cancellation must be demonstrated, including a hook-only SIGKILL on
macOS.

Persist a review-attempt record before dispatch and distinguish completed, unavailable and interrupted/incomplete
outcomes. A hook killed before finalization must leave detectable incomplete work, not a fabricated verdict or zero-cost
claim. Reuse existing telemetry where possible and avoid duplicate usage records.

Before B3, Codex allowed actions have no proven in-session feedback. B1 must expose the latest review state, reason and
time through `forge policy supervisor status [--json]`, and unavailable/incomplete attempts through
`forge telemetry activity [session]`, extending those surfaces where needed. Hook stderr alone does not satisfy this
contract. Model-visible feedback and operator UI warnings are B3.

## Implementation order

First evaluate auth-status isolation without a model call. Run negative auth cases in disposable Docker identities or,
for Keychain-specific behavior, a separate macOS user/VM. Reserve the maintainer's login for one positive host scenario;
verify login selection and settings are unchanged afterward. The checklist maps every auth case to its test location.

After establishing the intended subscription route, create a real disposable planning conversation in its recorded
planner directory, using that same route for successful `Edit` and `Bash` calls. This necessary fixture-creation turn is
recorded separately; it is not the **first inference compatibility probe**. That probe resumes and forks the real
history under the proposed read-only tools with the executor checkout added. Do not assume a synthetic transcript is
resumable. Establish compatibility and write prevention before selecting the mechanism for both modes.

If removing tool definitions breaks resume, evaluate a supported deny/permission mechanism that preserves history while
blocking new writes. `--disallowedTools` or a permission mode are candidates, not assumed solutions. Prove the same
boundary under permissive settings, including Bash, MCP and delegation; do not restore writable tools merely to make
resume succeed. Fresh and resumed runs may use different mechanisms with the same enforced contract. Preserve the source
conversation and record the tested version, argv policy and outcome in sanitized fixtures.

## Acceptance and validation

- A plan-only configuration survives resume, supports status/JSON, on/off/remove/reload, and registers a supervisor
  without a Claude target. Invalid setup leaves existing state intact. Suspended configuration remains distinguishable
  from absent or unusable configuration.
- Unit and regression tests cover the shared predicate at current call sites, model/effort identity, plan changes,
  missing inputs, legacy targets, lane freeze, timeout/quota behavior and recursion suppression. Use coherent session
  fixtures for indexed states. Cover plan-only Claude and Codex reviewers, their failures and incompatible options.
- Host Claude Write/Edit runs plan-only and target-plus-plan review with either reviewer. Sidecar plan-file and
  subscription-only setup refuse without mutation; inherited unsupported configurations dispatch no reviewer and report
  unavailable. Keep a conversation-only sidecar control on its existing explicit route under the read-only restriction.
- Existing frozen `claude-max` supervisors with API keys retain API selection until explicitly reconfigured. Exercise
  lane and billing controls for all four consumers; subscription-only remains a supervisor-local opt-in.
- Targeted integration tests and a hands-on Codex test use trusted Forge hooks: an aligned patch lands; a clearly
  divergent patch is denied and does not land. Put the approved plan file in the main checkout and the executor in a
  worktree with different sentinel content; prove inspection uses the executor worktree. Do not claim coverage of shell
  writes or deleted-only patches that the adapter skips.
- With permissive `acceptEdits`/Bash settings, direct the reviewer to attempt writes and prove reviewed checkout files
  remain unchanged, including untracked files. Exercise fresh and resumed Claude runs, tool/MCP/delegation bypass
  attempts, and the fresh Codex sandbox. CLI-owned session metadata is separate from the reviewed checkout.
- Test over-budget setup rejection, multi-file/cascade/retry cumulative time, cancellation of child processes, and a
  deliberately killed hook. Status/activity must distinguish unavailable or incomplete review from a successful allow,
  including before B3 ships. Confirm the actual installed hook timeout and trust state.
- Use fixtures for every auth source and settings precedence case, with and without `.env`; refusal must precede any
  paid request. Include Forge loading a key from `.env` after a plain-shell status check, then confirm the final cleaned
  child and auth preflight agree. Test optional/missing plan metadata and use positive controls for every settings
  source; ignored untrusted project settings do not prove isolation. Confirm missing/expired login cannot fall through
  to stored paid credentials. Run one explicitly selected subscription review under the documented account condition and
  inspect attribution without claiming a measured invoice or quota decrement. Confirm the existing Claude-target path
  still works under the new restrictions.

## Boundaries

Allowed-action model-visible feedback is [B3](../../doing/codex_policy_warnings/card.md), turn-completion review is
[B4](../../proposed/codex_stop_review/card.md), and native planning forks are
[B5](../../proposed/codex_fork_supervisor/card.md). Jev and team supervision are separate.
