# Codex fork supervisor checklist

Card: [card.md](card.md). Epic: [Codex supervisor](../epic_codex_supervisor/card.md), member **B5**.

## Current focus

Review the implemented [runtime contract](gate-decision.md) on `codex/codex-fork-supervisor`, rebased onto synchronized
`main` at `225ab3dd`. The user authorized B5 execution after the separate global-ignore fix merged and separately
authorized four API starts. The [evidence](evidence/README.md) records 60/60 starts, including 3/4 API starts. The user
approved the source/home/trigger decision on 2026-10-11. Installed admission, leases, accounting and native product
controls and aggregate verification passed on `1b0f01cf`; PR #265's review fixes are locally verified. The user approved
keeping one login and waiting within review deadlines on 2026-10-12. [Review-fix evidence](evidence/review-fixes.md)
qualifies the new paths separately from the closed native round. B1 and B2 remain the prerequisites. B3 and B4 are
shipped integration contracts: native context must preserve their feedback provenance, turn attribution, dispatch cap,
and failure behavior. Their completed captures do not establish native-fork isolation. Jev, native team orchestration,
general session fork/resume, and the proposed Codex source adapter remain outside this card. The separate
[Stop global-ignore fix](../../done/preserve_stop_global_ignores/card.md) shipped in PR #264 (`d33721a2`). Its merged
tree matches the tested fix and its five PR checks pass; B5 still verifies native Stop composition.

### Verified starting point

- B2's [fork captures](../../done/codex_0160_validation/evidence/forks.json) and
  [interpretation](../../done/codex_0160_validation/evidence/README.md) establish ephemeral, structured, read-only forks
  on Codex 0.161.0 for short sources. A planning sentinel survived; a shared source also included later executor
  reasoning. Only one controlled concurrent boundary was observed. Earlier-turn selection, arbitrary concurrency, and
  complete long-context retention remain unverified.
- B2's fork command supplies the prompt as an argv argument and has no explicit model selector. Fork stdin delivery,
  different-model history loading, and switching source/reviewer auth routes need new evidence; resume stdin evidence
  does not establish fork behavior.
- The same captures record zero nested reviewer calls but unexpected parent policy decisions and `confirmed_at` changes.
  `sanitize_codex_child_env()` still retains `FORGE_SESSION` and other ambient context; raising `FORGE_DEPTH` alone does
  not isolate ownership. B4 now installs additional turn hooks, so B2's hook inventory is insufficient.
- `SupervisorConfig.resume_id`, target validation, and reload resolution are Claude-specific. Codex dispatch is fresh
  and plan-fed; `prepare_codex_request()` supports fresh execution and resume, with no typed fork request. Some
  supervisor comments incorrectly describe native resume as unavailable.
- `validate_reviewer()` admits `subscription-only` only for direct Claude/`claude-max`. Codex dispatch consumes cached
  preflight and reestablishes its resolved credentials. A `chatgpt` lane name alone does not prevent API billing.
- Manifest readers accept versions 1–4; `manifest_for_write()` emits v2 for legacy configuration, v3 for explicit
  reviewer/auth identity, and v4 for Stop intent or overrides. Shadow schema v6 freezes a Claude conversation or plan
  source. Neither format currently represents a native Codex source boundary.
- The shared invoker owns Codex usage emission. `ReviewAttempt` records execution state; B4's separate operational
  journal owns turn spending across telemetry reset. Native forks must not create another budget or usage emitter.
- B4 requires a nonempty approved plan for Stop. Its 60-second hook has a 55-second internal deadline; the 10-second
  completion reserve and elapsed setup/evidence capture further reduce the configured maximum 45-second review window.
- B4's effective-config fix is already on this base: `supervisor_set()` validates the replacement after overrides and
  rechecks during mutation; generic session set/reset call `validate_supervisor_transition()`. B5 must extend these
  paths, not describe the earlier PR finding as an unfixed shipped bug.
- The planning fixture reproduced lost global-ignore exclusions on `5613b185`. PR #264 corrected that issue before this
  rebase. All 35 focused evidence/global-ignore checks pass on merged `main`, and its post-merge CI passes.

## 0. Activate and review

- [x] Create the separate execution branch from `5613b185`; move the B5 directory from `proposed/` to `doing/`.
- [x] Write this checklist, update the epic's current cursor, and repair inbound and outbound lane links. Preserve B1/B2
  dependency ownership and historical evidence.
- [x] Run `make pre-commit-md`, the repository link audit, file-size checks, and staged/working-tree diff checks; record
  the planning results below.
- [x] Review this plan, including the proposed configuration, source boundary, auth policy, and native probe budget,
  before starting section 1. User authorized execution on 2026-10-11 after PR #264 merged; API slots retain their
  separate authorization requirement.

## Proposed contract for review

The runtime round adds a [decision supplement](gate-decision.md). The original surface below is not sufficient to own a
dedicated reviewer login, copied ancestry, an attempt-lifetime lease or comparable native usage baselines. The user
approved that supplement before sections 2–6 began; it supersedes these original proposals where they differ.

The proposed setup is
`forge policy supervisor set <source> --source-runtime codex --runtime codex --model <model> --auth-mode subscription-only|api`
with `--plan <approved-plan>` required for Stop and shared or unverifiable source lineage. Native setup requires an
explicit auth mode; omission or `inherit` is rejected. These are proposed additions, not shipped commands.

- **Source identity:** introduce a dedicated runtime-qualified native-source record; keep legacy `resume_id` semantics.
  Accept a managed name or full Codex thread ID only after resolving on-disk evidence. Persist the confirmed thread ID,
  source scope, and resolution provenance independently of the executor and reviewer lane. Do not auto-select the
  current/latest thread, adopt the source, or depend on the unshipped source-adapter framework.
- **Plan authority:** preserve B4's Stop plan gate; native history supplements the approved snapshot. Only an admitted
  PreToolUse review with a separate, verifiable source lineage may omit the plan file. Shared thread, known shared fork
  ancestry, or unknown ancestry requires a plan and reports reduced or unverified independence. An explicit approved
  plan always wins. Different IDs alone do not prove independent context, and a model's recollection does not prove
  complete source retention.
- **Billing:** extend the supervisor-local auth policy for the native Codex path: `subscription-only` requires verified
  subscription auth; `api` explicitly selects a verified API route. Enforce the selection in the child, not only in
  cached preflight. Model and auth selection is available only for source/reviewer combinations proved by the gate;
  unknown compatibility is unavailable, not an implicit model or billing fallback. Keep `LaneRecord` and the other
  consumers unchanged; report actual billing posture separately.
- **Fallbacks and delayed work:** native mode has no automatic Claude, fresh-plan, or paid-route fallback. Refuse
  cascade and shadow sampling for native sources in this first implementation: the current shadow format cannot freeze
  their context. An unavailable native review remains visible under existing supervisor fail-open behavior, not an
  aligned verdict. An operator may explicitly reconfigure to a supported plan-only reviewer.
- **Runtime support:** candidate PreToolUse support covers host Claude and Codex; Stop remains host-Codex-only. Gate
  results decide whether native PreToolUse is practical for each admitted source class, or whether the first release
  must be Stop-only. Record and review that scope decision before implementation. Sidecars refuse native sources. Do not
  expand the general validated ceiling or blocking QA pin from feature-specific evidence.

Proposed auth-mode matrix; no new semantics for legacy reviewer/source combinations:

| Reviewer/source                 | `inherit` or omitted | `subscription-only`                  | `api`                              |
| ------------------------------- | -------------------- | ------------------------------------ | ---------------------------------- |
| Claude, existing sources        | Existing behavior    | Existing direct `claude-max` guard   | Reject                             |
| Codex, existing fresh plan path | Existing behavior    | Reject in B5                         | Reject in B5                       |
| Codex, native source            | Reject               | Verified, child-enforced login route | Verified, child-enforced API route |

The matrix must hold for CLI setup, decoded config, overrides, reset and inheritance. A source's historical model or
account may be unavailable; do not infer it from its thread ID, current login, or last model alone. Admit only source
forms for which the tested compatibility rule can be enforced.

## 1. Prove the runtime boundary before product work

Only experiment helpers and disposable fixtures implement candidate behavior in this phase. Complete the gate before
adding product flags, serialized configuration, or installed hook behavior. Checked items below refer to experimental
controls and their recorded qualifications, not installed product acceptance. The final scope/go decision awaits review
of the [contract supplement](gate-decision.md).

- [x] Retain the tested Codex package, resolved executable, launcher, version, and executable hash. Record the Forge
  revision plus dirty diff/hash and effective configuration with every capture. Build a fresh round with isolated HOME,
  CODEX_HOME, FORGE_HOME, planning/action checkouts, and independently established fixture login; do not copy ordinary
  login secrets or reuse a closed B2–B4 credential store. Disable dotenv and remove ambient API/proxy credentials for
  subscription cases. Account extra usage must be off; record unverifiable billing limits without asserting measured
  quota or invoice changes.
- [x] Reproduce B2's actual composition once with a synthetic argv prompt and no model override. Then prove fork stdin
  delivery with explicit model/effort, including multiline/large bounded action evidence and schema output. Inspect
  child argv to prove review content is absent; do not fall back to argv for product prompts. Keep exact source ID,
  action checkout, read-only sandbox and ephemeral semantics. Verify a source-only sentinel absent from prompt/files,
  distinct child ID, no persistent child rollout, and unchanged quiescent source bytes.
- [x] Fork between two explicitly selected, available models in both directions. Separately test subscription-created
  source to API reviewer, API-created source to subscription reviewer, and a combined model/auth switch. Record the
  source fixture's model/auth provenance, actual reviewer model/auth, structured outcome, context sentinel and preserved
  parent. Distinguish an auth route switch from a different-account test; do not claim cross-account compatibility
  without a separately verified fixture. Move these cases before the go/no-go decision; unapproved API calls remain
  unrun and block admission of those compatibility cells, not silently deferred product tests.
- [x] Probe child-side auth enforcement with non-secret status and mixed-credential negatives before live dispatch.
  Strip API/proxy variables and key hydration for subscription mode, isolate auth-bearing config, and test the retained
  binary's login-method restriction if available. Establish that it constrains execution, not merely login UI. An
  API-only child must not fall back to stored subscription login. Use controlled failure fixtures where possible;
  finding or accepting a configuration key is not proof. If billing cannot be constrained, refuse that mode.
- [x] Create a long source with distributed early/middle/late sentinels and a genuinely compacted source with retained
  compaction metadata, tool history and a later approved plan. Run repeated forks for each; synthetic JSON truncation is
  not compaction evidence. Record source bytes/turns, reported context size, time to first event, full reviewer latency,
  input/cached-input/output tokens and sentinel survival or omission. Missing usage fields remain unknown. Local replay,
  cached input and billed input differ; do not assert full uncached history cost on every review.
- [x] Measure both candidate triggers with representative checkout/evidence cost. For Stop, record the actual remaining
  review time under the 55-second internal deadline minus elapsed setup/capture and 10-second completion reserve; never
  grant a fresh 45 seconds after capture. Use the long/compacted results to admit bounded source classes and triggers,
  or propose Stop-only/no-go. Do not raise hook timeouts to make the experiment pass.
- [x] Prove reviewer-specific hook isolation with every installed B4-era event enabled in the fixture. Test a candidate
  that disables native hooks and strips parent session/root/launch/authority/executor identities while passing review
  attribution out of band. Verify the combined fork invocation actually suppresses hooks; CLI help is insufficient.
  Include CWD-based session discovery and subprocesses launched by the reviewer. Compare manifests, active indexes,
  authority state, session-event journals, pending work, and telemetry: no adoption, rebinding, policy append, memory
  work, turn reservation, or nested reviewer caused by the child. Do not globally strip identity needed by ordinary
  managed Codex invocations.
- [x] Compare flag-based isolation with a disposable copied-prefix source. Reuse validated rollout discovery, copy only
  complete JSONL records from an observed prefix, hash the exact bytes, and verify that Codex actually loads that copy
  without reading/appending the original. A newline boundary alone may leave an incomplete tool exchange or compaction
  state; test/refuse those boundaries. Verify native catalog/index requirements and all config/hook origins, including
  the action checkout. An empty CODEX_HOME alone is not proof that no customization can execute. Use independently
  established fixture login or an explicitly selected API credential; never copy or symlink the user's `auth.json`.
  Record token-refresh/login effects. This alternative remains an experiment until source loading, credential isolation
  and lifetime are proved; do not replace native context with an untested transcript-import path.
- [x] Test read-only enforcement against patch and shell writes in the source checkout, action checkout, and another
  directory. Include permissive project/user customization, MCP and delegation paths; disable unsupported executable
  customizations for this reviewer. Use a disposable writable control to distinguish a real refusal from a model that
  never attempted the write. Prove normal parent hooks still run.
- [x] Exercise different-checkout review with distinguishing file contents and a newer approved plan. Then use a shared
  source containing contradictory later implementation reasoning. Verify current-plan precedence, visible reduced
  independence, and refusal before dispatch when the shared source lacks a readable approved plan.
- [x] Inspect actual native fork ancestry metadata using a source forked from the executor and a shared-ancestor
  fixture. Reuse available rollout metadata; bound traversal and reject cycles/ambiguous identity. If ancestry is absent
  or incomplete, report independence unknown and require the approved plan. Do not call distinct IDs independent.
- [x] Probe active sources at the actual supported PreToolUse and Stop hook boundaries, not only B2's shell-sleep
  boundary. Record the observed native IDs, source prefix/hash and timing before/after fork, parent progress, and
  absence of child content in the source. Establish which context prefix can be claimed and how dispatch recognizes that
  case. A hashed observed prefix identifies bytes available at capture; only a proved copied-prefix load can identify
  the input artifact selected for review, and neither proves every byte reached the model after native compaction. Keep
  native verdict caching disabled in B5. Do not treat mtime or an idle scan as an atomic snapshot guarantee.
- [x] Use an admitted stub reviewer with real sleeping descendants for deterministic timeout, cancellation and
  hook-only-death cases; these consume no Codex model calls. Add one real native-fork hook-death control to confirm the
  actual process shape and cleanup. Preserve the shared 1–45-second ceiling and 60-second registrations, including
  Stop's reduced remaining budget. Test absent/malformed verdicts and exit-zero runtime errors with deterministic
  fixtures. Quota-shaped fixtures validate classification; they do not establish live quota exhaustion. Preserve B4's
  recorded native cancellation and quota qualifications unless new captures replace them.
- [x] Record a go/no-go decision with links to each capture. Parent isolation, read-only enforcement, useful context,
  bounded lifetime, stdin transport, and an enforceable model/auth/context-size support matrix are required before
  product work. A shared/active source may dispatch only for a demonstrated, enforceable boundary; otherwise report it
  unsupported before inference. If that prevents this card's shared-source acceptance, return the scope decision for
  review instead of silently dropping that acceptance or claiming B5 done.

### Proposed probe allocation

**60 Codex invocations total: 49 allocated and 11 retry/setup reserve.** Both parent/executor and nested reviewer starts
are inside this ceiling, including failed starts and enrollment turns. The table allocates native starts, not tool
calls. Auth status, local fixture checks and admitted stub processes use no model calls. No Claude inference is planned.

| Case | Source/executor starts | Reviewer starts | Purpose                                                                  |
| ---- | ---------------------- | --------------- | ------------------------------------------------------------------------ |
| G0   | 11                     | 0               | Enrollment; short, API, long, compacted and fork-lineage sources         |
| G1   | 0                      | 2               | Exact B2 control; stdin plus explicit model/effort                       |
| G2   | 0                      | 2               | Different-model forks in both directions                                 |
| G3   | 0                      | 2               | Different-auth forks in both directions                                  |
| G4   | 0                      | 1               | Combined model/auth switch                                               |
| G5   | 0                      | 2               | Long-source repeated forks and usage/latency                             |
| G6   | 0                      | 2               | Compacted-source repeated forks and retention                            |
| G7   | 0                      | 2               | Flag isolation; CWD discovery and reviewer subprocesses                  |
| G8   | 0                      | 2               | Copied-prefix isolation and incomplete-boundary control                  |
| G9   | 0                      | 2               | Read-only patch/shell matrix and writable control                        |
| G10  | 0                      | 1               | Different checkout and newer plan                                        |
| G11  | 0                      | 2               | Shared-source precedence and shared lineage                              |
| G12  | 2                      | 2               | Actual PreToolUse and Stop boundaries                                    |
| G13  | 0                      | 1               | Native-fork hook death; other lifetime cases use stubs                   |
| G14  | 0                      | 1               | Exact Stop copy with fresh native SQLite state after stale-index refusal |
| P1   | 4                      | 4               | Product allow/deny, plan refusal and trigger composition                 |
| P2   | 2                      | 2               | Clean-wheel product controls                                             |
| R    | 11 combined            |                 | Failed attempts, fixture growth and retries                              |

Each start has one owning case, binary/model/auth identity and outcome in the ledger. A rejected case that never starts
Codex costs zero; an unexpected nested reviewer or attempted startup consumes a slot. G0 includes the API-source seed;
G3/G4 include API reviewers: at most three successful API starts are planned, plus at most one explicitly budgeted API
retry from R. Those four API slots are inside the 60 and do not inherit B3's consumed API exceptions. The user
separately authorized them during execution on 2026-10-11; the earlier planning discussion alone did not authorize them.

Allocation revision before G14, 2026-10-11: transfer the unused twelfth G0 setup slot to G14. The final R start failed
before a thread started because a reused native index remembered a longer rollout than the selected Stop prefix. G14
tests a fresh `sqlite_home` with the same dedicated fixture login. The total remains 60, API authorization remains four,
and all twelve P1/P2 product slots remain reserved. The wrapper enforces the revised case limits; no failed slot is
refunded and no product slot is borrowed.

If source construction/compaction or the required matrix cannot fit, stop and revise the allocation before dispatch; do
not counterfeit long/compacted evidence, omit a required cell, or borrow unrecorded calls. Use fixtures first and reuse
measured cases where their assertions truly overlap. No live calls are part of this planning turn.

## 2. Add runtime-qualified source and configuration ownership

- [x] Implement the reviewed source contract in `session/models.py`, shared policy operations, target resolution, and
  reviewer validation. Reuse `core/runtime/codex_rollouts.py` and the ambiguity rules in
  `core/ops/codex_adopt.py:find_adoptable_rollout`; extract shared read-only resolution where needed. Use
  `find_rollouts_by_thread_id`, not `find_rollout_path`'s newest-mtime winner, for binding. Resolve the source's
  recorded directory independently of the action checkout; adoption's current-CWD constraint cannot be copied unchanged.
  Use confirmed Codex identity and native-store evidence, not a UUID shape or the Claude UUID field. Reject missing,
  ambiguous, mismatched-runtime, deleted, or changed sources without partial config/lane writes; revalidate the stored
  binding before dispatch and never silently follow a renamed/recreated managed session.
- [x] Add the source selector to terminal and direct-command setup through shared operations. Validate combinations
  before proxy startup or durable mutation: Codex source requires Codex reviewer, supported host executor, admissible
  boundary, appropriate auth policy, and no native `fork_session=False`, cascade, or shadow sampling. Keep
  omitted-source behavior for existing conversation-backed Claude and fresh plan-only reviewers.
- [x] Validate the complete effective candidate after applying retained/replaced overrides on every authoring path:
  `supervisor set`, `forge session set policy.supervisor.*`, `forge session reset <key>|--all`, lane changes, inherited
  intent/overrides, and lifecycle `on`/reload. Include source, reviewer runtime, auth, trigger, required plan, sidecar,
  cascade and shadow combinations. Repeat identity-sensitive checks under mutation/launch, and reject malformed
  persisted combinations at dispatch without crashing. Extend B4's effective-config regressions for masking overrides,
  reset exposing invalid intent, frozen identity, and concurrent changes; do not validate only authored intent.
- [x] Encode new source/auth semantics with a new manifest version only when needed, including effective overrides. Keep
  ordinary v2/v3 writes and existing Stop-only v4 writes compatible. Cover strict reads, unknown fields/versions,
  generic override application/removal, frozen reviewer identity, malformed records, and old supported readers. Do not
  serialize new null/default fields into older manifests.
- [x] Freeze source resolution and auth/model/effort identity consistently with the existing lane commitment. Make
  source replacement explicit, invalidate related state, and prevent a failed replacement from erasing working config.
  Cover `set`, `off`, `on`, `remove`, and `reload`, including suspended and frozen sessions.
- [x] Keep plan reload runtime-aware. Reuse one immutable `PlanSnapshot` for the prompt, citation verification, attempt,
  and cache identity. A configured but missing/unreadable plan makes review unavailable; never fall back to conversation
  instructions. Detect source/executor equality through confirmed IDs, including name-versus-ID aliases and resume;
  apply the verified lineage rules and unknown-independence handling to different IDs. Require a nonempty approved
  snapshot for every native Stop setup and dispatch, preserving B4's gate.
- [x] Preserve supported session lifecycle behavior: Codex children use `session start --runtime codex --resume-from`
  and receive fresh policy; `session fork` is not a Codex path. Recheck equality and admission on resume and on any path
  that inherits supervisor intent. Refuse incompatible inheritance before transfer inference or child publication.

## 3. Dispatch an isolated native reviewer

- [x] Add a typed fork request to the shared Codex invoker without changing managed fresh/resume behavior. Use the newly
  demonstrated fork stdin/argument composition, protected schema/output files, runtime admission, action CWD, read-only
  sandbox, and ephemeral semantics. Clean temporary artifacts on success, failure, timeout, and cancellation.
- [x] Apply the tested reviewer-specific hook/environment isolation before launch. Keep source access available without
  binding the child to the parent Forge session. Carry the outer attempt, session and run-tree attribution explicitly;
  distinguish legitimate outer review bookkeeping from child hook mutations in integrated assertions.
- [x] Bind cached readiness and auth verification to the actual executable, configuration/account location, child
  environment, and selected billing mode. Refuse cold/stale/unready or mismatched evidence without probing in the hook.
  Subscription cases must not hydrate a key or fall through to paid settings; API cases must not fall back to login.
  Enforce the gate-proved login/API restriction in the launched process, including negative stored-credential cases; do
  not treat preflight alone as an enforcement boundary. Preserve the other consumers' inherited-credential contracts.
- [x] Supply bounded action evidence and the current approved snapshot after native source selection, with explicit plan
  precedence and untrusted conversation/action content. Record unavailable or compacted context honestly. Validate
  structured verdicts and citations through existing rules; do not promote remembered text into verified plan quotes or
  reinterpret model confidence as calibrated probability.
- [x] Persist source runtime/ID/provenance, boundary evidence or its limits, child ID when returned, action checkout,
  plan digest, independence, effective reviewer/auth identity, and outcome in the review record. Version record changes
  explicitly and preserve readable older records. Failed launches may have no child ID; do not invent one.
- [x] Disable native verdict-cache reuse in B5. Preserve the source artifact/prefix hash for audit, with native loading
  and compaction qualifications; a hash alone does not prove model-visible context. Recheck plan/source/config/action
  identity under the chosen boundary contract before applying the verdict. A changed live source invalidates review;
  later appends to a proved immutable copy are reported separately from that copy's identity. Keep existing cache
  behavior for other source modes.
- [x] Reuse the whole-hook deadline and parent-death watchdog. Record a durable attempt before dispatch, preserve an
  incomplete outcome after interruption, and emit usage once through `CodexHeadlessInvoker` with `operation=None`.
  Detect quota/runtime errors even on exit zero; suppress native-mode sticky degrade and alternate-context retries.

## 4. Preserve policy, feedback, and operational contracts

- [x] Exercise native review with host Claude Write/Edit and host Codex `apply_patch`. Deterministic checks and artifact
  authority retain their current order and effect. Source/refusal/runtime failures remain unavailable reviews under the
  existing failure policy, never synthetic alignment or unexpected engine-construction errors.
- [x] Compose with B4 Stop review: the outer journal reserves the single dispatch; source failures and uncertain starts
  cannot reopen spending. Keep one correction, no per-edit semantic calls, no cascade/shadow or transport retry, current
  checkout attribution, partial-evidence limits, and persistence across telemetry reset. Native fork hooks must neither
  reserve a second turn nor mutate the parent's watermark.
- [x] Keep native Stop product admission blocked on the separate
  [global-ignore evidence fix](../../done/preserve_stop_global_ignores/card.md). Add a composition regression using a
  synthetic file ignored only through global `core.excludesFile`: it must not enter snapshots or outgoing evidence.
  Scope this to incidental untracked-file capture; global ignore is not a secrecy guarantee for tracked files or
  explicit tool payloads. Do not bypass the issue by asserting B4 evidence is already safe or by loading arbitrary
  global Git execution settings. Runtime experiments use disposable synthetic content throughout.
- [x] Preserve B3 normal/source-only audience rules and summary-off behavior. Only verified approved-plan passages may
  enter source-only model feedback; an admitted conversation-only PreToolUse review without a verifiable quote uses
  fixed diagnostics while full generated evidence remains operator-readable. Stop always has an approved snapshot.
  Native history is not a new authority for injected instructions.
- [x] Show source runtime/ID, available boundary facts, approved-plan digest, shared-source reduced independence, actual
  reviewer/billing route, and unavailable/incomplete reasons in supervisor status/JSON and review/activity evidence.
  Preserve stable result streams and source-vs-reviewer distinctions in lane `set|show|clear` and telemetry surfaces.
- [x] Reject unsupported manual-evaluate and shadow reconstructions explicitly or extend them through the same verified
  source contract; never silently substitute a fresh prompt. Keep native cascade/shadow configuration refused,
  historical audits readable, and live enforcement evidence separate from shadow evidence. Correct stale dispatch
  comments in touched code.

## 5. Acceptance tests

Use `tests.fixtures.session_state` to publish coherent indexed fixtures. The table maps the reviewed acceptance matrix
to automated tests and retained native evidence. Live compatibility claims use the gate/product captures, not stub
delivery alone.

| Test                       | Fixture                                                        | Assertion                                                               | Test file                                                                                                   |
| -------------------------- | -------------------------------------------------------------- | ----------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------- |
| Source identity            | Managed name, full native ID, duplicate/missing/Claude source  | Confirmed binding or refusal without mutation                           | `tests/src/core/runtime/test_codex_review_source.py`                                                        |
| Schema compatibility       | Legacy v2/v3, Stop v4, native config and overrides             | Conditional new version; old writes remain readable                     | `tests/src/session/test_store.py`                                                                           |
| Setup and lifecycle        | Set/reset, masking overrides, inherited intent, frozen/sidecar | Effective combinations validated atomically; reset cannot expose bypass | `tests/src/cli/test_policy_supervisor.py`, `tests/regression/test_bug_b4_effective_config.py`               |
| Native request             | Explicit source, schema, action CWD, model/effort              | Fork arguments; fresh/resume requests unchanged                         | `tests/src/core/invoker/test_codex_invoker.py`                                                              |
| Fork transport             | Multiline bounded prompt via stdin                             | Exact payload received; no prompt content in argv                       | `tests/integration/core/test_codex_fork_supervisor.py` and native gate/product evidence                     |
| Model/auth compatibility   | G2–G4 source/reviewer matrix                                   | Context loads or admission refuses; no model/route substitution         | `tests/integration/core/test_codex_fork_supervisor.py` and native gate/product evidence                     |
| Long/compacted context     | G5–G6 with repeated forks and sentinels                        | Retention, cached input and real remaining deadline recorded            | `tests/integration/core/test_codex_fork_supervisor.py` and native gate/product evidence                     |
| Hook ownership             | Parent markers plus CWD discovery and B4 hooks                 | No child adoption, parent mutation or recursive review                  | **new** `tests/regression/test_bug_codex_reviewer_parent_mutation.py`                                       |
| Read-only and context      | Planning sentinel, separate checkouts, writable control        | Source preserved; action checkout read; attempted writes denied         | `tests/integration/core/test_codex_fork_supervisor.py` and native gate/product evidence                     |
| Shared source              | Later conflicting reasoning; with/without approved plan        | Plan wins; reduced independence; absent plan means no dispatch          | `tests/integration/core/test_codex_fork_supervisor.py` and native gate/product evidence                     |
| Source lineage             | Same ID, known fork ancestry, missing ancestry                 | Shared/unknown independence visible; plan required                      | `tests/src/core/runtime/test_codex_review_source.py`                                                        |
| Active boundary            | Parent suspended in supported hook; source changes             | Only proved boundary admitted; no invented snapshot guarantee           | `tests/integration/core/test_codex_fork_supervisor.py` and native gate/product evidence                     |
| Auth and accounting        | Login, explicit API, ambient key, stale preflight              | Selected billing only; one usage event; no paid fallback                | `tests/src/core/runtime/test_codex_review_source.py`                                                        |
| Runtime failures           | Exit-zero error, quota, malformed verdict, cold cache          | Unavailable reason; no alignment or alternate-context retry             | `tests/src/policy/semantic/test_supervisor.py`                                                              |
| Lifetime                   | Sleeping reviewer/descendant; hook-only kill                   | Bounded cleanup and durable incomplete attempt                          | **new** `tests/integration/core/test_codex_fork_supervisor.py`                                              |
| Context freshness          | Live source advances, immutable copy, changed plan             | Native cache disabled; audit identifies selected input and limits       | `tests/src/core/runtime/test_codex_review_source.py`                                                        |
| Stop composition           | Duplicate hooks, correction, telemetry reset, partial work     | One dispatch/correction; exclusions and journal ownership preserved     | `tests/integration/core/test_codex_stop_review.py`                                                          |
| Stop plan gate             | Separate native source with absent/empty plan                  | Setup rejects; persisted invalid config cannot dispatch                 | `tests/src/policy/semantic/test_stop_review.py`                                                             |
| Stop evidence prerequisite | Synthetic untracked file ignored only globally                 | Excluded from capture and reviewer evidence after separate fix          | `tests/src/policy/semantic/test_turn_evidence.py`                                                           |
| Feedback and observability | Normal/source-only, no quote, summary off                      | Audience/provenance limits; accurate status and streams                 | `tests/src/cli/hooks/test_codex_policy_feedback.py`, `tests/src/cli/test_policy_status.py`                  |
| Legacy control             | Claude planner; fresh Claude/Codex; old shadow records         | Existing routing, auth, cache and audit behavior preserved              | `tests/integration/docker/test_plan_file_supervision.py`, `tests/src/policy/semantic/test_shadow_runner.py` |

## 6. Product verification and documentation

- [x] Run focused unit/regression checks for each changed contract, then `make test-unit`, `make test-regression`, and
  `make pre-commit` on the integrated head. Every corrected bug gets a reproducer; do not count fixture-only delivery as
  native proof.
- [x] Run new Docker and real-process integration files through `./scripts/test-integration.sh <path-or-pytest-args>`;
  also target `tests/integration/docker/test_plan_file_supervision.py`,
  `tests/integration/core/test_codex_policy_feedback.py`, and `tests/integration/core/test_codex_stop_review.py` for
  compatibility. Keep paid/native cases explicit and within the approved ledger; report missing prerequisites or
  deselections rather than treating them as passes.
- [x] Refresh `forge runtime preflight codex` outside hooks and verify enrollment when needed. Exercise source setup,
  lifecycle controls, `forge policy supervisor status --json`,
  `forge session lane set|show|clear --consumer supervisor`, and `forge telemetry activity <session>`. Test the
  no-`.env` subscription path and explicit API configuration separately. Verify unavailable-source and
  unsupported-version recovery commands apply to the selected mode.
- [x] Build one candidate with `make build` and exercise native review from a clean wheel install, including packaged
  schema/resources, hook registration/trust, action-checkout selection, and parent preservation. Retain exact wheel and
  binary hashes and compare captured product code to the final head; qualify any later source drift.
- [x] Update shipped contracts in `docs/design_workflows.md`, `docs/design_subprocesses.md`,
  `docs/design_session_execution.md`, and the session state design where serialization ownership changes. Update
  `docs/end-user/policy.md`, relevant runtime guidance, and `docs/cli_reference.md` with the tested setup, billing,
  support/refusal matrix, independence limits, and recovery. Do not turn proposed behavior into normative documentation
  before implementation passes.
- [x] Export sanitized commands, versions, assertions, dispatch counts and negative results under this card's
  `evidence/`. Preserve B2–B4 captures unchanged. Tear down only the B5-owned login, processes and fixtures; verify
  normal login/settings/source state remains unchanged where evidence permits. Teardown removed both owned logins and
  product input copies, with no fixture processes left. Ordinary credentials were not accessed; all selected original
  source prefixes stayed intact. The earlier unexplained ordinary config hash change prevents a whole-round settings
  preservation claim and remains documented in the evidence.

## Closeout

- [ ] Complete or explicitly disposition every acceptance item, including active/shared-source limits; record the exact
  tested head and passing aggregate checks. Resolve any scope reduction with review before marking the card complete.
- [ ] Open the per-card PR, verify CI, and reconcile the epic's native-fork outcome against its shared contract. Run its
  integrated plan-file, feedback, Stop and native-context acceptance; closing the last member alone does not prove the
  coordinated outcome.
- [ ] After merge, sync `main`, verify the merged tree against the tested head and CI, record completed work in the
  changelog, move B5 to `done/`, and repair links. Close the epic only after its remaining integrated checks pass.
- [ ] Promote durable implementation lessons only after human review; retain evidence limits in the card closeout.

## Planning validation

2026-10-11: `PYTHON_DOTENV_DISABLED=1 make pre-commit-md` passes, including formatting, file-size limits, and links.
`./scripts/check-markdown-links.py` passes for 658 source files; staged and working-tree `git diff --check` pass. Only
board documents changed. Implementation and live probes remain gated on the requested review.

Review revision, 2026-10-11: verified the supplied findings against B2's argv and current Stop/setup/rollout code. Added
gate cases for stdin, model/auth switching, long and compacted sources; preserved Stop's approved-plan requirement;
specified effective-config paths and an explicit auth matrix; replaced the aggregate 32-call estimate with a 60-start
case allocation. Native verdict caching stays disabled. Copied-prefix isolation remains a measured alternative, not a
guarantee that a new home eliminates every hook or that a file hash proves complete model-visible context.

A temporary Git repository with synthetic content reproduced the global-ignore issue: ordinary untracked enumeration
returned no files, capture included `.env`, and comparison emitted its changed diff. The fixture was removed. The
separate proposed fix blocks native Stop product admission. B4's effective-config correction is already merged; its
regression is an extension point, not an outstanding shipped finding.

Revision checks passed: `make pre-commit-md`, the 659-file link audit, and both diff checks.

## Execution record

2026-10-11: rebased planning commit `a5428554` as `0aca9c7e` onto `225ab3dd`, after PR #264 merged as `d33721a2`. The
merge matches tested tree `697bf553`; all five PR checks and the post-merge main run pass. The 35 focused Stop
capture/global-ignore tests pass on that merged tree. Removed the superseded proposed fix card and repointed its links
to the completed correction. Starting section 1 with a fresh owned fixture; no product implementation is admitted yet.

The user completed two independent fixture logins, confirmed extra usage is off, and authorized four short-source API
starts. The retained Codex 0.162.1 round now records **48/60 starts, 3/4 API starts**. All five hooks delivered at their
60-second registrations. Transport, model/auth switches, repeated long/compacted context, isolation, copied ancestry,
read-only writes, current-plan precedence, actual active boundaries and lifetime controls are captured in the
[evidence index](evidence/README.md). No product source changed.

The [gate decision](gate-decision.md) records the proposed login lifecycle and trigger limits for review. Leaf auth
controls are necessary, wrong stored auth may be logged out, a copied paginated source requires its ancestor, and an
unfinished tool exchange loads without native refusal. The shipped watchdog left a detached native descendant; a
cancellation-first prototype passed the native control and corrected stub controls. Terminal usage includes inherited
source counters, so direct emission would double-count historical tokens. The original dispatch plan cannot proceed
unchanged. The compacted copied-source control proves a comparable terminal baseline; its delta matches new request
usage exactly. Offline admission replays the actual Stop boundary and rejects unfinished PreToolUse. Real-process lease
tests retain ownership after hook death, including simultaneous watcher death. These prototypes do not implement
installed product behavior. A reused native index rejected the exact Stop prefix as a shrunken rollout; G14 loaded that
prefix with fresh SQLite state and unrelated copies held aside. The gate allocation transferred the unused G0 setup slot
to this control before dispatch, preserving the 60-start ceiling and twelve product slots.

Thirty-nine offline admission/harness/watchdog and seventy existing Codex invoker/stream checks pass. Four targeted Stop
recovery/global-ignore integration checks pass through the integration runner. One legacy-executor retry is inconclusive
because it timed out and its final source check overlapped the copied-lineage quarantine. Original files were restored.
An ordinary Codex config hash changed early in the round for an unverified reason; it was left untouched and the
evidence does not claim settings preservation. A local test rerun needed authorized process inspection after the outer
sandbox refused `ps`; all 39 checks then passed.

Gate handoff validation: the combined focused admission, harness, watchdog and Codex invoker/stream run passes **109
tests**. `PYTHON_DOTENV_DISABLED=1 make pre-commit` passes, including mypy, pyright, gitleaks, file-size limits and
Markdown formatting. The Markdown link audit passes for 662 source files; working-tree and staged diff checks pass. The
final allocation is 48/60 starts and 3/4 API starts, leaving only the twelve product slots. Both original-rollout and
copied-rollout holding directories are empty, and the export contains no fixture account identifiers. The contract
supplement is ready for the scope review required before product implementation; B5 and the epic remain in `doing/`.

Contract approval, 2026-10-11: the user approved the dedicated reviewer login, copied histories with fresh native
indexes, separate completed-source PreToolUse, and approved-plan Stop for shared/active sources. Proceeding with
sections 2–6; the remaining twelve native starts stay allocated to product and clean-wheel verification.

Product verification, 2026-10-11: implemented conditional schema v5, effective source/auth/lane validation, dedicated
reviewer login, copied native ancestry with fresh indexes, cancellation-first lifetime ownership, new-review usage
deltas and uncached native dispatch. Runtime support follows the approved gate matrix. The six product reviewers passed
separate-source allow/deny, shared active Stop with approved-plan precedence, source-only feedback and global-ignore
composition. Each emitted exactly one attributed usage event. Both Stop controls allowed one correction and left that
correction unreviewed. The [product export](evidence/product.json) records **60/60 total starts, 3/4 API starts**, wheel
identity and installed-source hashes matching the final working tree; there will be no additional native calls in this
round.

The final targeted integration runner passed **14 tests**, with **11 legacy native cases explicitly deselected** because
they require separate fixtures or more inference. New B5 native controls compose those installed paths within the
budget. `make test-regression` passed **1,546 tests**. The Claude adapter control used a synthetic Write payload with a
real Codex reviewer, not a live Claude executor; explicit product API configuration used a dummy key without inference,
with route evidence supplied by the three earlier API starts. Source/config/plan races, malformed output, quota errors,
override/reset/inheritance admission and lease cleanup have deterministic or real-process coverage.

Final verification: `make test-unit` passes **10,770 tests, 117 deselected**; `make test-regression` passes **1,546**;
full `make pre-commit` passes, including type checks, lint, secret scan, formatting, file-size limits and Markdown
links. The user explicitly approved counting the three changed large guides through Anthropic's token-count endpoint.
Their refreshed cache entries and the previously failing exact-byte cache assertion now pass. No model generation was
used for that refresh, and the native-start ledger remains closed at 60.

The deterministic policy CLI file and diff paths both pass for `coding_standards`, each reporting one checked file.
`origin/main` remains `225ab3dd`, and installed product source hashes still match. The implementation, tests, documents
and sanitized evidence are ready for per-card PR review. CI and merged-tree verification remain closeout obligations.

The [fixture teardown](evidence/product-teardown.json) logged out both independently authenticated fixture stores,
verified all fixture auth files absent and removed copied product inputs. No fixture processes remained, and the round
is marked closed. Sanitized evidence and credential-free private captures remain for review. B5 and the epic remain in
`doing/` until review, merge and shipped-tree closeout.

PR #265 review fixes, 2026-10-12: executor ancestry now reads bounded headers independently of copied-source admission,
so large and TUI executors can use a separate source. Subscription reviews wait within their deadlines; readiness reads
do not acquire the lease. Policy set/reset is structural only, and active on/reload preflights outside the session lock.
Configured home aliases, lifecycle diagnostics, direct help JSON and native status identity have regression coverage.
The [new validation record](evidence/review-fixes.md) preserves the original live captures at `1b0f01cf` and does not
claim new native compatibility. The user retained the single-login contract; concurrent subscription inference remains
outside B5.

Review-fix verification on `aa86eb5d`: aggregate unit **10,770 passed, 117 deselected**; aggregate regression **1,587
passed**; targeted integration **16 passed, 11 legacy native cases deselected**. A clean installed wheel matched all 386
Forge Python files and passed offline admission, ownership and CLI smoke checks. No additional native/API starts were
used.

CI follow-up: preserve ordinary on/reload prerequisites while retaining native readiness outside the lock. Four added
regressions forbid ordinary runtime probes and preserve Stop enrollment; 158 targeted tests pass. The wheel evidence was
refreshed. See the [validation record](evidence/review-fixes.md) and PR #265 for the final aggregate checks.
