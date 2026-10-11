# Once-per-turn Stop review checklist

Card: [card.md](card.md). Epic: [Codex supervisor](../epic_codex_supervisor/card.md), member **B4**.

## Current focus

Planning on `codex/codex-stop-review`, based on published `main` at `897ed95c` (B3 closeout), 2026-10-11. B1, B2, and B3
are done. B4 adds an opt-in Codex Stop trigger with at most one semantic reviewer dispatch per explicit user turn,
including automatic continuations. It reviews changes already made; deterministic PreToolUse checks and artifact
authority remain active. B5 and Jev are outside this branch.

This checklist is the implementation plan. Product implementation and new live probes have not started.

### Verified starting point

- `get_builtin_codex_entries()` installs only SessionStart and PreToolUse. Codex recognizes Stop and UserPromptSubmit,
  but Forge has no Codex turn-review handler. The existing `forge hook stop` is Claude's
  transcript/verification/deferred work pipeline; wiring Codex into it would import different behavior.
- B2's [Stop capture](../../done/codex_0160_validation/evidence/stop.json) on 0.161.0 shows one controlled correction:
  stable thread/turn IDs, `stop_hook_active` false then true, and a user-role
  `<hook_prompt hook_run_id="stop:22:<fixture-config-path>">`. This does not establish ID stability across resume,
  duplicate delivery, or launch boundaries. User-role messages are not necessarily new human turns.
- B2's [lifetime cases](../../done/codex_0160_validation/evidence/lifetime.json) exercised B1 PreToolUse review and its
  watchdog. They are useful controls, not proof of a Stop review budget. Its
  [publication qualifications](../../done/codex_0160_validation/evidence/validation.md#harness-and-publication-provenance)
  still apply.
- B1's `ReviewAttempt` uses a fresh UUID and a writer lock per attempt. It detects incomplete reviews but does not
  reserve a unique turn. Its retention is bounded; pruning telemetry must not reopen a turn's spending allowance.
  `deadline.validate_timeout()` verifies three existing PreToolUse registrations, not Stop.
- `register_supervisor_and_restore()` registers either the frontier supervisor or the checker/frontier cascade for
  per-action evaluation. Stop mode must exclude both semantic paths and shadow scheduling from those actions without
  excluding deterministic policies. The Claude runner also has a format-rejection retry to account for.
- `forge runtime preflight codex --verify-enrollment` currently observes SessionStart only. A successful receipt does
  not prove that a new Stop or turn-start hook fired. Manual `supervisor evaluate` currently checks one file against a
  conversation target; it is not a whole-turn re-review command.
- B3 supplies process-bound executor admission and bounded, source-aware findings. Its supported feedback versions
  (0.161.0 and 0.162.1) concern PreToolUse. Stop needs separate admission and wire evidence. On this planning date,
  `/opt/homebrew/bin/codex --version` reports 0.162.1; execution must retain and identify the version installed then.
- `session_fork_preflight.py` refuses Codex parents. The supported child path is
  `forge session start <child> --runtime codex --resume-from <parent>`. It transfers context and inherits artifact
  authority, but currently starts with fresh supervisor policy. Codex start also rejects `--no-launch`.
- Manifest readers accept versions 1–3. `manifest_for_write()` chooses v2 for legacy supervision and v3 for explicit
  reviewer identity/auth or their overrides. Adding a serialized trigger to either version would break older strict
  readers. The session-event journal has locked, durable appends under project artifacts; telemetry reset leaves it
  alone, but its append API does not implement conditional reservations or bounded replay.

## 0. Activate B4

- [x] Create a separate branch from clean, synchronized `main` at `897ed95c`; move B4 to `doing/` with `git mv`.
- [x] Add B3's shipped feedback/provenance contract as an explicit dependency on B4 and the epic, with a downstream
  handoff on B3. Keep B1/B2 evidence historical and repair inbound lane links.
- [x] Validate this planning change with `make pre-commit-md`, repository links, file-size limits, and staged/working
  tree `git diff --check`; record results below.

## 1. Establish runtime evidence and decide whether to proceed

Run this section before changes to product configuration, CLI flags, manifest versions, or installed handlers. Only
experiment helpers and disposable fixtures implement candidate behavior here. Product/wheel rows in the budget are
reserved for section 6; they are not prerequisites for this gate.

- [ ] Create a new B4 round root with dedicated HOME, CODEX_HOME, FORGE_HOME, checkout fixtures, and wrapper. Retain the
  installed Codex package/binary, selected launcher, resolved executable, version, and streaming SHA-256 for the whole
  round. Record Forge revision and dirty diff/hash for every capture. Never reuse B3's closed credential store or copy
  the normal `auth.json`; obtain an independent fixture login when execution starts.
- [ ] Disable dotenv loading in probe environments and remove API/proxy credential sources. Default to an admitted
  Claude stub which answers version/help/auth checks and records actual dispatch before sleeping or returning a verdict.
  A PATH stub must not replace the Codex executor. Use one real Claude subscription-only review solely for the completed
  aggregate-review control, with explicit model, no API fallback, and account extra usage disabled. The two Haiku API
  exceptions used during B3 are consumed, not authorization for B4. Use deterministic `--strategy structured` for
  `--resume-from` probe launches: the default `ai-curated` transfer can itself make an API call. The single real
  aggregate review belongs to section 6 after product implementation.
- [ ] Export `FORGE_DEV=<absolute checkout>` in every development probe terminal, including the operator's. Assert
  `forge extension doctor --json` reports `hook_dispatcher.dev_override.effective: true`; capture the hook's actual
  launcher/module path. The clean-wheel row later unsets this override and proves installed-wheel provenance instead.
- [ ] Before inference, enumerate the live cases and reserve a ceiling of **32 Codex turn units**: 4 enrollment checks,
  6 identity/boundary controls, 4 product/evidence controls, 4 failure controls, 4 wheel/TUI controls, 2 correction
  continuations, and 8 retries. Count every submitted start/resume and enrollment probe, including automatic advisory
  enrollment checks and any initial transfer-prompt turn; conservatively count a correction continuation even when Codex
  retains its turn ID. Share cases where assertions fit, track failed launches, and stop before expanding this ceiling.
  Reserve at most **one real Claude subscription review**, without an automatic retry; all other reviewers are stubs.
  This is a future execution budget, not evidence of work performed or paid-API authorization.
- [ ] Record `forge runtime preflight codex --json` and Codex doctor readiness/auth/billing facts. Enroll exact
  registrations with their selected timeout, retain config hashes, and inspect the existing SessionStart receipt. Add
  event-specific observations for every new event the design relies on. Pin config after enrollment: destructive probe
  initialization refuses an enrolled fixture unless explicitly reset, followed by re-enrollment.
- [ ] Capture a normal Stop, multi-prompt TUI session, headless start/resume, no-change turn, and controlled correction.
  Correlate raw hook stdin/stdout/stderr/exit status with native rollout events and working-tree outcomes. Establish
  which IDs identify a human turn, how missing/duplicate events behave, and whether the baseline event occurs before any
  tool mutation. Replayed duplicates test Forge idempotency but do not prove native retry behavior.
- [ ] Probe the chosen Stop block/allow/operator shapes on the retained version, including source-only feedback and
  summary-off candidate payloads from fixture helpers. Repeat them through the product in section 6. Distinguish emitted
  output, model receipt, and TUI rendering. Identify hook-generated user messages by verified metadata, not merely their
  role or text. Do not assume `hook_run_id` is a global deduplication key or that B3's PreToolUse `systemMessage`
  behavior applies to Stop.
- [ ] Record a Stop-specific go/no-go decision with capture references before beginning sections 2–5. Admit only
  measured versions with a verified invoking executor; inherited environment identity, nested runtimes, or old rollout
  metadata are insufficient. Unknown identity or missing required events reports review unavailable and spends no model
  call. Preserve B3's shim basename/child-cwd launch behavior. Leave the general QA ceiling, release pin, and shared QA
  provenance unchanged.

Blocking decision: record whether the captures support turn identity, baseline timing, Stop response delivery, native
timeout handling, and the promised one-dispatch cap/evidence scope. A go records the measured limits and permits product
implementation in sections 2–5. A no-go stops those sections until the card is revised to a supported contract. Do not
substitute background notification for Stop review. This is distinct from the completed board activation in section 0.

## 2. Implement the trigger, spending, and failure contracts

Begin only after section 1 records a go. These are the resulting product requirements, not prerequisites for the probes.

- [ ] Add `SupervisorConfig.review_trigger=pre-tool-use|stop`, defaulting to existing per-edit behavior. Expose the
  opt-in through `forge policy supervisor set --trigger stop`, with `pre-tool-use` selecting the existing mode and an
  omitted flag preserving the saved choice. Cover strict overrides, status JSON, suspend/on, reload, resume, and
  switching modes. A mode change during a turn must not reset its allowance or manufacture a baseline; report when a new
  explicit turn is required.
- [ ] Add schema v4 and accept v1–v4 reads. Keep the existing v1/v2-to-v3 migration separate; default the absent trigger
  to `pre-tool-use` without rewriting on read. In `manifest_for_write()`, emit v4 only when stored intent or a
  supervisor override requires a non-default trigger. Include `review_trigger` in override compatibility checks; inspect
  stored intent and overrides, not only the effective value. Preserve an explicit default override masking a stored Stop
  trigger. For ordinary/default-only state, omit the new default field from both serialized locations and retain the
  existing v2/v3 choice and shape, including B1's auth/model fields. Do not let changing `SCHEMA_VERSION` promote every
  existing v3 writer to v4. Keep required-field validation synchronized for v4 and reject trigger fields in older
  schemas; test that a v3 reader refuses v4 by version, not an unknown-field traceback. Returning to the default must
  restore the appropriate compatible v2/v3 encoding when no non-default trigger remains.
- [ ] Exercise `forge session start <child> --runtime codex --resume-from <parent>` and subsequent
  `forge session resume <child>`, through both TUI and headless paths. Preserve its current fresh-policy behavior;
  configure Stop on the child explicitly, and never copy a parent's spent-turn records. Start the TUI without `--task`,
  allow any initial transfer-prompt turn to finish, then set the idle child's supervisor with `--session <child>` from a
  second terminal before submitting the next explicit prompt. That next turn is the first supervised one; the bootstrap
  turn is not retroactively reviewed. Use the configured child for later headless resumes. Do not advertise
  `--no-launch` or `forge session fork` for Codex. If a path that does inherit policy or an override would give a
  non-Codex/sidecar child Stop mode, refuse before publishing the child, transfer inference, or launching a runtime.
  Preserve the parent and offer explicit recovery: select a supported host Codex path, or explicitly change the source
  trigger to `pre-tool-use` before retrying. Never silently downgrade an inherited trigger or erase supervision.
- [ ] Reject Stop mode for unsupported executor/sidecar combinations and absent/unverified hook prerequisites with
  actionable recovery. Treat the executor and reviewer runtimes separately: a host Codex executor can retain B1's
  supported reviewer lanes and plan sources; this does not add native Codex planner context from B5.
- [ ] Define the cap as one frontier model dispatch, not one wrapper invocation. In Stop mode reject cascade and shadow
  sampling combinations atomically, and suppress automatic dispatch retries/fallbacks after a dispatch may have begun.
  Capability/auth checks without inference are allowed. Missing/malformed verdicts and quota failures consume the
  reservation; duplicate hooks cannot retry them. Preserve existing per-edit and explicit manual-review behavior.
- [ ] Preserve B1's operational fail-open semantics: unavailable or incomplete review is not an allow/aligned verdict. A
  completed divergent result may request one correction. A later continuation must terminate without another review or
  correction block, with any changed work marked unreviewed. Stop failure cannot undo edits or claim enforcement against
  already-written files. Deterministic PreToolUse denies retain their existing behavior.
- [ ] Carry unreviewed continuation changes into the next explicit turn's review scope with their original evidence
  provenance, alongside that turn's new changes. A no-change skip requires no outstanding work; a later result clears
  only the exact snapshot it assessed. Lost/changed provenance remains visibly unreviewed. Document this explicit-turn
  recovery path without adding a new manual review command; existing single-file `evaluate` cannot clear whole-turn
  status. Ordinary pre-existing dirty work is still excluded.

## 3. Capture a bounded turn snapshot

- [ ] Introduce explicit turn-evidence ownership separate from Claude's Stop pipeline. Use the measured turn-start event
  and launch/session identity, not SessionStart alone for a multi-turn TUI. Snapshot repository/worktree identity, HEAD,
  index, tracked working files, and relevant untracked state before mutations, with byte/file/time limits. Do not modify
  the user's index, stash, files, or commits to obtain a baseline.
- [ ] Evaluate a private-index/tree implementation: copy the index to a temporary `GIT_INDEX_FILE`, write snapshot
  objects with `GIT_OBJECT_DIRECTORY` in Forge-owned storage, expose source objects read-only as alternates when needed,
  and compare before/after trees with `git diff-tree -M`. `git add -A` plus `write-tree` is a candidate, not yet a safe
  capture contract. Account for split/sparse indexes, configuration, attributes, and normalization; verify the real
  index/object store/worktree stay unchanged. Disable executable Git helpers, hooks, external diff/text conversion, and
  fsmonitor in the capture path. Detect clean/process filters before staging, including Git LFS. Either capture bounded
  raw bytes without running them or refuse that scope visibly; private index/object paths do not sandbox filters.
- [ ] Derive the turn delta from before/after content, including edits on top of pre-existing dirty/staged files. Cover
  additions, deletion, rename, executable-bit changes, shell writes, and edit-then-revert outcomes. Keep action outcomes
  distinct from net changes. Final assistant prose or a diff against HEAD is not sufficient evidence of this turn.
- [ ] Define handling for binary/oversized files, ignored paths, symlinks, submodules, non-Git roots, external writes,
  concurrent editors, and changed HEAD/index. Never follow an unsafe path or silently truncate evidence into a
  full-review claim. Attribute only proven changes; report omitted/unsupported scope and ambiguity. Missing baseline or
  incomplete coverage cannot produce a clean whole-turn verdict. Include a synthetic clean/process filter that attempts
  an external marker write and an LFS-like attribute fixture; the product capture must leave the marker absent, make no
  network call, and report its coverage accurately. Keep the observed side-effect demonstration separate from the
  product's no-side-effect assertion.
- [ ] Freeze bounded evidence plus B1's approved `PlanSnapshot`, source digest, reviewer/lane/auth identity, and config
  identity for the call. Adapt the prompt to already-applied multi-file changes, rather than pretending they are one
  pending `Write`. Inspect the executor checkout read-only. Recheck relevant state when the review finishes: changed
  evidence, plan, configuration, or checkout invalidates current approval without deleting the historical result.
- [ ] Choose storage/retention and exclude Forge-owned evidence from its own change capture. Keep prompt/evidence text
  private by default, bound artifacts, and sanitize publication. Persist explicit coverage and omission counts. A
  no-change skip requires complete evidence and remains distinguishable from unsupported or missing evidence.

## 4. Reserve one review and survive interruption

- [ ] Prefer a `review` domain in `forge.session.events` for the operational journal, reusing its containment, locking,
  append/fsync, and strict-envelope mechanics. Add domain-owned validation and any required origin values explicitly.
  Extend it with a conditional reserve operation under one domain lock: the existing independent read and locked append
  do not prevent two owners. Avoid recursively acquiring the append lock or holding it across inference. The current
  reader loads the entire unbounded journal, so pair it with the bounded watermark/compaction contract below before
  using it on the hook path; do not create another journal solely to duplicate these mechanics.
- [ ] Define a durable turn key scoped to Forge root/session, native thread, explicit user turn, and validated launch
  ownership where needed. Correlate turn IDs with continuation markers; malformed/unverifiable input must not create a
  new spending allowance. Bound paths/IDs and reject another checkout or nested reviewer's inherited session identity.
- [ ] Reserve the turn atomically before dispatch and link the reservation to B1's attempt record and immutable evidence
  digest. Concurrent Stop processes must yield exactly one owner. Record no-change/unavailable outcomes explicitly. Do
  not hold the general session lock across inference or use a timeout cache as the idempotency mechanism.
- [ ] Exercise crash boundaries before reservation, between reservation and attempt creation, after dispatch starts,
  after verdict persistence, and before response output. An uncertain dispatch stays spent/incomplete after recovery;
  duplicate delivery cannot spend again. Readers must not turn inspection into a retry or rewrite historical outcomes.
- [ ] Persist correction-request consumption before emitting its response so a replay cannot request another automatic
  correction. A stale deny is not replayed against a changed snapshot. A lost response may remain unconfirmed; do not
  infer delivery from a saved verdict. Later Stop events compare evidence and report any unreviewed continuation delta.
- [ ] Preserve the cap after process restart, rapid user prompts, suspend/resume, config reload, and attempt-log
  pruning. Define a bounded durable watermark/tombstone policy or equivalent that cannot reopen old turns. Test stale
  hooks after a new turn begins, independent worktrees with the same session name, and session cleanup without touching
  others. Operational spending state must survive telemetry reset; test reset in disposable fixtures without preserving
  deleted telemetry as purported audit evidence. Define crash-safe review-domain checkpoint/compaction with bounded
  hot-path reads and storage, preserving the spent watermark before removing old entries. It must not truncate other
  session-event domains or mistake damaged/missing history for an unused turn allowance. Test it against concurrent
  reservation and restart.
- [ ] Establish separate Stop wall-clock and reviewer budgets from the measured controls. Start the deadline before
  loading/capture, include lock waits, auth/admission, subprocess setup, inference, serialization and recording, and
  leave a measured cleanup margin below the registered timeout. Reuse B1's 1–45-second reviewer limit unless an explicit
  measured change is needed; do not make `validate_timeout()` accidentally validate Stop against PreToolUse alone.
- [ ] Test ordinary deadline, executor cancellation, hook SIGKILL, and actual native Stop expiry only after dispatch is
  recorded. The watchdog must reap reviewer descendants even across process groups. Bound harness cleanup with TERM,
  then KILL, plus a fixture-owned PID/start-time sweep; retain pre-sweep survivors so cleanup does not hide product
  leaks. A hook killed before finalization remains incomplete and observable without stdout. Use an admitted stub and
  labelled fault instrumentation for native expiry if the product deadline normally prevents reaching it;
  restore/re-enroll changed hook definitions and keep that control distinct from ordinary deadline proof.

## 5. Integrate policy, feedback, and installation

- [ ] In Stop mode, keep deterministic policy and catch-all artifact authority checks active on every applicable action.
  Skip frontier/checker registration and shadow enqueueing there, even for multi-file patches; do not produce a false
  per-edit semantic "aligned" summary. Preserve default per-edit supervision, blocked-patch state atomicity, and all
  Claude Stop verification/transcript/deferred-work behavior.
- [ ] Reuse B1 reviewer admission, plan/source verification, read-only permissions, explicit model/effort, auth
  isolation, usage emission, and durable attempts. Preserve planner-history lookup versus executor-checkout inspection.
  Prevent reviewer hooks from opening parent turn records or mutating parent manifests; depth suppression alone is
  insufficient.
- [ ] Render Stop through its measured response schema. Normal mode attributes bounded findings; source-only admits
  verified plan quotations and fixed Forge diagnostics into every model-visible field, including the block reason. The
  reason has user authority in the observed runtime, so never interpolate raw provider errors or unverified quotations.
  Apply B3's provenance and byte limits without assuming its PreToolUse wire shape. Keep full audit evidence.
- [ ] Specify summary-off for Stop: optional non-blocking model feedback is suppressed, while necessary correction/block
  guidance and truthful operator/status evidence remain. Do not emit a success notice for skipped, incomplete, stale,
  unavailable, or partly unreviewed work. If Stop has no measured operator channel, use durable status/activity and
  state that limitation rather than relying on exit-zero stderr as a visible warning.
- [ ] Extend `forge policy supervisor status [--json]` and `forge telemetry activity` with trigger, turn/evidence
  identity, coverage, reservation/dispatch/correction state, assessed snapshot, and unreviewed changes. Keep one usage
  event per actual review, using the actual route and model. Preserve the four-consumer lane contract. Stub usage is
  labelled synthetic; subscription attribution is not a measured invoice or quota change.
- [ ] Register dedicated Codex handlers with exact timeout/command identity, updating dispatcher/install ownership,
  registration status, and event-specific enrollment verification together. Unmanaged/disabled sessions are inert.
  Enable/sync/disable for `--runtime codex|claude|all` preserves other runtime ownership and user hooks. Changed
  CODEX_HOME and changed trust definitions retain existing safe disable/refusal behavior and name re-enrollment needs.
- [ ] Sync shipped behavior in `docs/design_workflows.md`, `docs/design_session_execution.md`,
  `docs/design_sessions.md`, `docs/design_telemetry.md`, `docs/design_installation.md`, `docs/design_runtime.md`,
  `docs/end-user/policy.md`, `docs/end-user/hook.md`, relevant session/installation guidance, and
  `docs/cli_reference.md`. Clarify the opt-in Codex Stop latency exception separately from ordinary fast Stop handling
  and Claude verification. Do not edit normative docs ahead of implementation.

## 6. Acceptance evidence

Paths marked **new** are planned test owners, not existing coverage. Keep the product tests independent of historical
B2/B3 private round paths. Bug reproductions belong in `tests/regression/` with the `regression` marker.

| ID  | Fixture                                                                                                                                                     | Assertion                                                                                                                                       | Test owner                                                                                                                                                              |
| --- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| E1  | Default/Stop set and overrides; suspend/reload/resume; `start --runtime codex --resume-from`; unsupported child runtime                                     | Fresh Codex child policy preserved; explicit Stop persists; incompatible inherited Stop refuses before child creation/inference; no spend reset | `tests/src/cli/test_policy_supervisor.py`, `tests/src/cli/test_codex_start.py`, `tests/src/core/ops/test_codex_session.py`, `tests/src/cli/test_session_derivation.py`  |
| E2  | Multi-edit, multi-file turn; deterministic deny; advisory shell write; default per-edit control                                                             | One Stop dispatch; zero per-edit semantic/checker/shadow calls in Stop mode; existing guards still act                                          | **new** `tests/src/cli/hooks/test_codex_stop.py`; existing `test_codex_policy_check.py`, `test_authority_check.py`                                                      |
| E3  | Captured explicit prompts, duplicate/parallel Stop, hook-generated user messages, nested runtime, fresh/resumed launch                                      | Stable turn ownership; no new allowance from a continuation, stale environment, or malformed identity                                           | **new** `tests/src/policy/semantic/test_stop_review.py`; `tests/src/core/runtime/test_codex_feedback.py`                                                                |
| E4  | Dirty index/tree/untracked baseline; additions/deletions/renames; shell writes and edit-revert                                                              | Delta excludes pre-existing work; relevant action outcomes retained; no-change requires complete coverage                                       | **new** `tests/src/policy/semantic/test_turn_evidence.py`                                                                                                               |
| E5  | Missing baseline, binary/large/ignored/external paths, symlinks, submodules, non-Git, concurrent/HEAD change; clean/process filters and LFS-like attributes | Bounded capture; explicit coverage gaps; filters/helpers cannot write outside storage or use the network; no fabricated whole-turn approval     | **new** `tests/src/policy/semantic/test_turn_evidence.py`                                                                                                               |
| E6  | Reservation/attempt/dispatch/result/output crash points; concurrent journal writers; restart, checkpoint/compaction, telemetry reset                        | Atomic single owner; at most one dispatch/correction; bounded replay; uncertain outcomes stay spent/incomplete; other journal domains unchanged | **new** `tests/regression/test_bug_b4_stop_idempotency.py`; `tests/src/session/test_session_events.py`; `test_bug_b1_attempt_retention.py`                              |
| E7  | Completed deny, automatic correction edit, later explicit turn with no new changes, plan/config/file change during review                                   | No automatic review loop; old verdict not applied to new snapshot; pending work reviewed next turn or visibly unavailable                       | **new** `tests/regression/test_bug_b4_stop_stale_review.py`; **new** Stop-review unit owner                                                                             |
| E8  | Admitted sleeping stub plus descendant; native hook expiry; SIGKILL; lock/capture slowdown                                                                  | Deadline covers whole invocation; product cleanup bounded; durable incomplete status survives lost stdout                                       | **new** Stop-review unit owner; `tests/src/core/reactive/test_watchdog.py`; new live B4 controls                                                                        |
| E9  | Valid/invalid plan quotes, raw error nonce, normal/source-only/summary-off, huge Unicode finding                                                            | Correct Stop shape; bounded output; no reviewer prose leaks in source-only; unavailable is not aligned                                          | **new** Stop-hook owner; `tests/src/cli/hooks/test_codex_policy_feedback.py`; native rollout/TUI controls                                                               |
| E10 | Actual child cwd; planner cwd differs; key/helper/dotenv/proxy contamination; invalid login                                                                 | Read-only reviewer inspects executor checkout; subscription-only refuses ambiguity without API fallback                                         | `tests/integration/docker/test_supervisor_auth_isolation.py`, `test_supervisor_e2e.py`; one new live aggregate review                                                   |
| E11 | New event registration, absent trust, changed timeout/CODEX_HOME, user hooks, each runtime filter                                                           | Exact ownership and event receipts; sync/disable preserve unrelated state; untrusted delivery is not success                                    | `tests/src/install/test_codex_hooks.py`, `test_hook_dispatcher.py`; `tests/src/core/ops/test_codex_enrollment.py`; `tests/integration/docker/test_installer.py`         |
| E12 | Fresh, completed, skipped, stale, incomplete and unavailable turn records with usage                                                                        | Stable human/JSON status and activity; accurate scope, route, call count; no duplicate cost events                                              | `tests/src/cli/test_policy_supervisor.py`, `test_output_streams.py`; new Stop-review unit owner                                                                         |
| E13 | Existing Claude verification/artifact/deferred Stop and default Codex policy fixtures                                                                       | B4 changes neither default supervision nor Claude Stop semantics                                                                                | `tests/src/cli/test_stop_verification.py`, `tests/integration/cli/test_stop_verification_integration.py`, `tests/regression/test_bug_d007_stop_artifact_idempotency.py` |
| E14 | Trusted current Codex, fresh fixture, editable checkout then same candidate wheel outside repo                                                              | Product Stop review/correction/counts observed; all required events enrolled; correct launcher and checkout                                     | **new** `tests/integration/core/test_codex_stop_review.py`; committed B4 experiment helpers under `scripts/experiments/codex-hooks/`                                    |
| E15 | v1/v2/v3 reads; default/Stop in intent and override; default override masking Stop; switch back; old strict reader                                          | Read-only legacy defaulting; unchanged compatible v2/v3 shape; v4 only for stored non-default trigger state; old reader refuses by version      | `tests/src/session/test_store.py`, `test_models.py`, `test_effective.py`; **new** `tests/regression/test_bug_b4_manifest_compatibility.py`                              |

- [ ] Run focused unit/real-command regressions for E1–E13 and E15, then `make test-unit`, `make test-regression`, and
  `make pre-commit` on the candidate. Mock binaries in hermetic launch tests; do not hash or invoke a developer's real
  Codex accidentally. Use coherent indexed-session fixtures from `tests.fixtures.session_state`.
- [ ] Run targeted Docker/integration owners through `./scripts/test-integration.sh`, with `-m 'not slow'` for the
  no-inference suites. Inspect selected tests before execution; no real API test is authorized by its file being named.
  Verify the exported image can execute Claude and uses the current Forge revision before interpreting test failures.
- [ ] Build one candidate wheel; install it cleanly outside the source tree, with FORGE_DEV absent and independently
  enrolled exact hooks. Exercise extension lifecycle, Stop review and correction, auth refusal, status/activity, and
  smoke-test the installed assets. Record the wheel hash and actual hook module paths. Re-enrollment consumes the
  budget.
- [ ] Complete E14 with trusted hooks, actual stdout/stderr/exit capture, native rollout receipts, working-tree hashes,
  reviewer dispatch counts, TUI evidence where claimed, and one subscription-only aggregate-review result. Include
  multi-turn/resume boundaries and a no-change control. Observe usage from completion events; quota exhaustion stays
  unverified unless it happens naturally, with synthetic failure coverage labelled separately.
- [ ] Commit the harness, exporter/redactor, stub-admission checker, and teardown helper used for publication. Retain
  failing attempts as well as successes. Hash helper sources per run; if a source changes afterward, identify the drift
  and rerun affected controls on the candidate. Offline replay validates saved evidence, not a historical process exit.

## 7. PR and closeout

- [ ] Reconcile the card and epic with final guarantees, supported versions, failure/coverage limits, and downstream B5
  handoff. Link a compact evidence index and validation record. Recheck links and `git diff --check`; open B4's own PR
  with validation counts, skips, and unverified claims. Leave the card in `doing/` until merged and verified.
- [ ] Stop and verify all fixture-owned processes, preserving pre-sweep leak evidence. Remove only the round's own login
  material at teardown; retain sanitized captures, runtime identities, exact helper sources, and package provenance.
  Compare recorded host config/auth metadata without claiming unchanged bytes prove token validity or remote revocation.
- [ ] After merge, pull `main`, verify the merge/tree and CI against the tested candidate, record closeout in this
  checklist and `docs/board/change_log.md`, and move B4 to `done/`. Repair all inbound links and any source comments
  pointing into `doing/`; promote durable lessons only after review. Keep the epic active and B5 parked.

## Planning validation

2026-10-11: `make pre-commit-md` passes, including file-size and link checks. The standalone Markdown link audit passes
for 652 sources; staged and working-tree `git diff --check` pass. Existing test owners were checked against the tree;
new owners are labelled in the table. No product tests or live model probes have run for B4.

Review revision, 2026-10-11: moved runtime go/no-go ahead of product work, corrected Codex child/setup paths, specified
conditional v4 serialization and unsupported-child refusal, and added journal/filter cases. A disposable Git experiment
confirmed that private index/object paths preserve the original index/object files but do not contain clean-filter side
effects; its temporary files were removed. Product capture still needs E5. Revised `make pre-commit-md` passes,
including size and link checks; the standalone link audit passes for 652 sources and both diff checks pass. No live
inference ran.
