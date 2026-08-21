# M1 execution checklist: Artifact Authority Mode

**Card**: [card.md](card.md) -- the normative contract. **Epic**:
[Session Authority and Provenance](../epic_session_authority_provenance/card.md). **Branch**:
`feat/artifact-authority-mode` (rebased onto `main` at `9ea043a4`).

## Current focus

Implementation and local verification completed on 2026-08-21; the branch is being prepared for review. M1 remains in
`doing/` until merge and post-merge lane/link closeout. M2 remains proposed; this branch adds no route history, marking
metadata, model selection, or status-line segment.

## Verified pre-implementation baseline

- `SessionIntent` has no authority field (`src/forge/session/models.py`); its strict dacite schema is additive at
  version 1, and `session/overrides.py` derives accepted override paths from that dataclass.
- `_inherit_intent_fields` currently deep-copies every listed field without role-specific logic. Authority needs a
  dedicated branch because advisory inherits while producer does not.
- Claude host launches mint their root `RunIdentity` inside `session/claude/invoke.py::_build_environment`, and sidecar
  launches mint independently inside `sidecar/container.py::run_sidecar_session`; both are too late for required launch
  preflight. Codex interactive launchers already mint before spawn, but the identity is not yet shared with authority
  preflight or journals.
- Claude registers ordinary `policy-check` only for `Write` and `Edit`. Codex already has the required no-matcher
  `codex-policy-check` command, whose registered bytes are trust-sensitive and must not change.
- The rendered host dispatcher calls `_should_dispatch()` before it parses the handler name. A managed producer or
  unmarked `authority-check` row would therefore resolve and execute Forge unless the marker gate moves ahead of that
  work.
- `core.telemetry.jsonl_io.append_jsonl_record` is intentionally best-effort and swallows failures. The epic requires a
  separate required-write helper with strict reads, containment, and durable complete-record appends.
- `ActiveSessionStore.peek_session()` is the existing non-repairing read seam suitable for `authority show`; mutating
  control-plane checks can use the live/self-healing seam.
- Session delete/clean do not selectively purge `.forge/artifacts/`, but artifact lifetime follows the session's
  recorded `forge_root`. Root-level `session start --worktree` keeps that root in the parent checkout; nested-project
  starts and worktree forks can place it inside the owned checkout, where worktree deletion removes the whole containing
  tree.

## Phase 0 -- Acceptance and design ratification

- [x] Branch created from current `main`; epic and M1 moved `proposed/ -> doing/` with `git mv`.
- [x] Lane-dependent links repointed in the active epic/member, proposed M2, and the adjacent model-first proposal.
- [x] Current intent, inheritance, launch/run-identity, hook registration/dispatch, active-state, artifact-retention,
  and JSONL seams verified against code before sequencing work.
- [x] Detailed checklist and fixture-grounded acceptance matrix written; implementation remains paused.
- [x] User ratified D1-D5 on 2026-08-21 with the D1 adopt exclusion, D3 per-attempt probe cost, and D4 spawn-boundary
  distinction recorded below.
- [x] Ratification review confirmed the checklist deliberately follows the repository precedents: structural dispatcher
  assertions plus the benchmark script as performance authority, additive optional manifest fields without a schema bump
  only when strict round trips prove compatibility, registration keys over `(event, matcher, command, timeout)`, and
  unchanged Codex command bytes so existing trust is not invalidated.

Activation and ratification verification (2026-08-21): all affected local Markdown links resolve, `git diff --check`
passes, `make pre-commit-md` passes, and the amended checklist size check reports about 7.5k tokens / 352 lines.

Ratified decisions:

- [x] **D1 -- Authority-bearing creation surfaces.** Put `--authority` and `--authority-tier` on every launch-capable
  governed-session creation surface: `session start` for Claude/Codex (including `--no-launch` and `--incognito`), the
  `session incognito` shortcut, `session fork`, and `session resume --fresh`. Reject those flags on an in-place resume;
  an external human can use `session authority set` before resuming. Explicit child authority wins before first launch;
  absent authority follows the card's advisory-only inheritance rule. This closes the card's otherwise implicit
  “explicit child role” surface without turning ordinary resume into a hidden mutation command. `session adopt` also
  creates a managed session but is intentionally excluded from the creation flags: Claude and Codex adoption remain
  unmarked, attach no authority seam to an already-running native client, and require the human to stop any native
  client and run `session authority set` on the inactive managed session before resuming it as advisory or producer.
- [x] **D2 -- Launch marker wire shape.** Use one internal, versioned, compact-JSON environment marker only for advisory
  runs. It carries the session/runtime, root run id, effective authority-config digest, and expected hook-registration
  digest; it carries no prompt, payload, path, or source content. The standalone dispatcher treats an absent marker as
  the producer/unmarked fast no-op, but forwards any present marker -- including malformed data -- to the handler for a
  fail-closed decision. Full schema, manifest, digest, and run-id validation stays in Forge code.
- [x] **D3 -- Runtime preflight posture.** For host Claude, require the exact catch-all registration and a current,
  executable dispatcher. For advisory Codex, require exactly one user-scope no-matcher `codex-policy-check` row with the
  installed command bytes and timeout, then call the existing empirical SessionStart enrollment verifier for each launch
  attempt; do not convert either static `hook_seam="enrollment_gated"` or a stale cache into `verified`. Treat advisory
  Claude sidecar as `unsupported` in v1 unless implementation can establish an equivalent pre-spawn hook/handler proof
  for the selected image; producer and unmarked sidecars retain current behavior and record a null
  installed-registration digest when no seam is required or observed. This is the narrow honest reading of “unverified
  refuses” and avoids claiming that staged settings prove the image can execute the handler. The chosen strictness
  spends one real, cheap `codex exec` probe whenever Codex is ready and registered: a 20-turn headless advisory workflow
  can therefore pay about 20 additional turns of latency and quota. The existing readiness cache observes the binary,
  auth/credential mtimes, and a TTL, not a proven trust-revocation source; any future enrollment cache needs separate
  probe evidence locating Codex trust state and demonstrating sound invalidation.
- [x] **D4 -- Configuration/lifecycle transaction boundary.** Serialize authority mutation against launch preflight for
  the same session. A successful set/clear/derivation must leave intent and its journal event consistent; on required
  append failure, roll back a newly created session or the prior authority subtree before returning an error. Register
  the marked launch as active and write `run_started` before invoking the child. A failed `run_started` append aborts;
  `run_ended` is attempted in `finally`, and a failure is surfaced without rewriting the child's actual exit outcome.
  This prevents the active-target check from being a race-prone advisory hint. Here `run_started` means Forge committed
  to invoke, not that a child was observed alive: a spawn exception produces
  `run_ended(outcome=error, reason_code=child_never_spawned)`, while a spawned child that returns nonzero uses
  `run_ended(outcome=error, reason_code=child_exited_nonzero)`. Reads must not present the former as an observed child
  run. The review refinement applies the same lock to an unmarked launch decision and retains it for the legacy child's
  lifetime. Its active registration stays best-effort, so ordinary start gains no new global-registry dependency;
  concurrent set/clear fails quickly with a journaled launching-or-active diagnostic instead of creating a marked
  manifest behind an unmarked child.
- [x] **D5 -- `launch_support` derivation.** Report `unsupported` for a statically incapable seam, `unverified` when a
  capable seam lacks required empirical/current-run evidence, `verified` only for a matching successful preflight of a
  live run, and `not_running` when the seam is capable but no run is active. `configuration_history` remains an
  independent journal-continuity field. Use `ActiveSessionStore.peek_session()` so the read does not repair state.

## Phase 1 -- Shared session-event journal foundation (epic C1-C4)

- [x] Add one authority-neutral `forge.session` event-journal module rather than an authority-local writer.
  - Assertion: it owns the schema-v1 envelope, `sevt_` id minting, UTC RFC 3339 timestamps, frozen
    `origin_surface`/`operation`/`outcome` enums, required/nullability validation, and domain-payload validation hooks.
  - Assertion: authority and the later M2 consumer can select separate domain paths without duplicating enums, ids,
    locks, serialization, or absence vocabulary.
- [x] Add contained artifact-path construction for `.forge/artifacts/<validated-session>/<domain>/events.jsonl` with an
  explicit domain allowlist.
  - Assertion: absolute names, separators, `.`/`..`, symlink escapes, unknown domains, and roots outside the owning
    `forge_root` are rejected before directory creation or append.
  - Assertion: authority events resolve only to `authority/events.jsonl`; no routing path is created by M1.
- [x] Implement required append under one dedicated per-journal lock using strict JSON-compatible values, compact UTF-8
  JSON plus one newline, secure directory/file modes, flush, and durability sync before success returns.
  - Assertion: concurrent processes produce complete, individually parseable records with unique ids and no interleaved
    bytes; append/open/lock/fsync failures propagate as typed errors.
  - Assertion: arbitrary `default=str` serialization is not used, so unsupported objects cannot silently stringify
    secrets or source-bearing values.
- [x] Implement a strict ordered reader.
  - Assertion: missing file is represented to the domain reader as absence, while unreadable files, truncated/non-object
    lines, unknown fields, invalid enums/nullability/timestamps/ids, and newer schema versions raise a record/line
    diagnostic; non-UTF-8 bytes are a typed read error and no bad line is skipped.
- [x] Pin the authority payload schema: role, nullable tier, effective-config SHA-256, nullable hook-registration
  SHA-256, and nullable covered tool; reject prompt/tool payload/patch/source fields and unknown payload keys.
- [x] Validate event-specific authority envelope semantics in addition to the shared fields and payload: run-id
  nullability, origin, operation, outcome/reason pairing, runtime-hook correspondence, and required advisory hook
  evidence must match the event type before append or report derivation.
- [x] Add neutral tests in `tests/src/session/test_session_events.py`; name the helper contract in the epic checklist so
  M2 must consume rather than fork it.
- [x] Sync the shared event ownership, paths, lock/failure behavior, local-tamper caveat, and C4 absence vocabulary into
  `docs/design.md`/`docs/design_appendix.md` with M1 described as the sole shipped consumer.

## Phase 2 -- Authority intent, coverage inventory, and human control plane

- [x] Add typed `AuthorityIntent(role, tier)` under `SessionIntent.authority`, defaulting to `None` (unmarked), without
  a manifest schema bump if old and new strict round trips remain compatible.
  - Assertion: only `advisory | producer` are accepted; advisory defaults to `shell_closed`; producer plus a tier is an
    error; direct malformed/newer manifest values fail strict reads.
  - Assertion: `session_state_to_dict` and strict store reads preserve exact role/tier values, while legacy manifests
    remain unmarked and behavior-compatible.
- [x] Add one versioned, runtime-specific coverage inventory and pure classifier used by launch markers, hooks, and
  `authority show`.
  - Assertion: `named_tools` covers raw `Write`, `Edit`, `NotebookEdit`, and `apply_patch` only; Bash, delegation, MCP,
    skill, unknown, and external-process surfaces are printed as uncovered.
  - Assertion: Claude `shell_closed` declines only the card's exact inspection and conversation/control allowlists and
    denies every other tool; Codex denies `Bash`, `apply_patch`, and every unknown/new tool because it has no
    shell-backed inspection allowlist.
  - Assertion: “decline” never emits an authority allow/grant and ordinary permission/policy hooks still run.
- [x] Add UI-free authority operations and a typed `forge session authority show|set|clear` CLI subgroup with stable
  `--json` on `show` and stdout/stderr behavior following the CLI style contract.
  - Assertion: `set` defaults advisory tier, rejects producer tier, and `clear` removes the complete subtree; both use
    workspace-scoped target resolution and target-project compatibility checks.
  - Assertion: `show` may resolve the current `FORGE_SESSION`, but `set`/`clear` require the explicit target shown in
    the card and never expose a mutating direct `%authority` command.
- [x] Enforce the human control plane before mutation and again at the serialized write boundary.
  - Assertion: authority-bearing creation, set, and clear refuse when `FORGE_SESSION` is present; set/clear refuse a
    live target; every well-formed target-resolved refusal appends `mutation_refused` with the applicable run
    id/origin/reason.
  - Assertion: malformed or unresolved commands emit diagnostics without creating an attacker-chosen journal path.
- [x] Statically reject `authority`, `authority.*`, and concrete authority leaves in both generic `session set` and
  keyed `session reset`; a target-resolved attempt appends `mutation_refused`. `reset --all` remains an override-only
  operation and cannot clear session intent.
- [x] Implement role-specific derivation across fresh resume, same/worktree/`--into` fork, relaunch helpers, and Codex
  child creation.
  - Assertion: advisory and its tier inherit; producer yields an unmarked child; frozen/confirmed runtime state is not
    copied as authority intent.
  - Assertion: an explicit child role replaces inherited authority before first launch and writes `authority_configured`
    from `external_cli`; implicit advisory writes `authority_inherited` from `session_derivation`; both use
    `run_id: null`.
- [x] Journal successful configured/cleared/inherited transitions with a canonical config digest and no source-bearing
  data; required append failure follows D4 and never reports success.
- [x] Sync session ownership/inheritance/control-plane semantics into `docs/design.md` and generic override restrictions
  into `docs/end-user/session.md` as the code lands.

## Phase 3 -- One launch identity, preflight, marker, and lifecycle

- [x] Introduce one runtime-neutral launch-attempt value carrying operation, runtime, root `RunIdentity`, effective
  authority config, and preflight evidence.
  - Assertion: root identity is minted once before member preflight for Claude host, supported sidecar paths, Codex
    headless start/resume, Codex TUI start/reattach, fresh resume, fork, and incognito; it is passed into the existing
    invoker/container instead of being reminted there.
  - Assertion: every interactive attempt has `run_id == root_run_id` and no inherited parent id; preflight failure may
    consume the id without producing a usage event or `run_started`.
- [x] Implement role-aware preflight without imposing authority work on unmarked sessions.
  - Assertion: advisory launch validates role/tier, exact runtime hook seam, dispatcher/registration digest, and D3
    empirical requirements before invocation; absent, malformed, stale, unregistered, unverified, or unsupported seams
    refuse with actionable recovery.
  - Assertion: producer records its configuration/run posture but does not require an enforcement seam; unmarked
    sessions keep current launch behavior and create no authority claim.
- [x] Canonicalize the effective config and registration tuples and compute lowercase SHA-256 digests from secret-free
  bytes; pin digest stability and drift behavior in tests.
- [x] Stamp the D2 advisory-only marker into Claude/Codex child environments, including the existing sidecar env-file
  transport only if sidecar advisory support is ratified.
  - Assertion: the marker is built from the validated preflight result, remains byte-fixed for the run, and cannot be
    supplied by session overrides or a user-facing option.
- [x] Append `launch_preflight`, `run_started`, `run_ended`, and `launch_aborted` with the same run id and correct
  start/resume/fork/incognito operation.
  - Assertion: preflight and start records commit before child invocation; normal exit, spawned-child nonzero exit,
    cancellation, and launcher exception each produce the exact terminal outcome and reason.
  - Assertion: a spawn exception after `run_started` yields `child_never_spawned`, a nonzero child exit yields
    `child_exited_nonzero`, and reads distinguish both from a preflight/commit abort, which has no `run_started` event.
  - Assertion: the launch orchestration exposes M2's future “authority then routing projection” insertion point and can
    append same-run compensating aborts, but M1 adds no routing event or projection.
- [x] Serialize every managed launch decision with authority mutation per D4. Marked launch activation remains required
  and releases the lock before child execution; unmarked execution keeps the lock for the child lifetime while retaining
  best-effort legacy active registration. Marker/config mismatch during a live marked run can only tighten to denial.
- [x] Pin journal tree lifetime through normal delete, clean with either transcript flag, failed launch, and incognito
  cleanup.
  - Assertion: delete/clean never selectively removes `authority/`; `--keep-transcripts` has no effect, and the journal
    survives whenever the recorded `forge_root` remains, including root-level `session start --worktree`, `--into`, and
    `--keep-worktree` cases.
  - Assertion: when deletion removes an owning checkout that contains the recorded `forge_root`, as for a nested-project
    worktree or worktree fork, the journal disappears with the complete `.forge/artifacts/<session>` tree. Tests pin
    both sides of this containing-tree boundary rather than promising retention outside it.
- [x] Sync the one-root-id/preflight/lifecycle/retention architecture into `docs/design.md` and the runtime-specific
  seam details into `docs/design_appendix.md`.

## Phase 4 -- Runtime authority guards and ordinary-policy preservation

- [x] Add Claude's dedicated `forge hook authority-check` command with raw PreToolUse evaluation and the existing valid
  Claude block response/exit contract.
  - Assertion: marker and manifest resolution, digest/run-id consistency, and tier classification happen before any
    per-file/path normalization or ordinary policy check; malformed mutation envelopes, delete/rename operations, and
    outside/`.forge`/unnormalizable targets remain denied by tool name.
  - Assertion: valid advisory guard exceptions, unreadable state, and marker mismatch deny; request-journal failure
    emits a diagnostic but never changes the deny.
- [x] Add one host Claude PreToolUse registration with omitted matcher for `authority-check`; keep both existing
  `policy-check` Write/Edit rows intact. Omit the row from sidecar staging while advisory sidecar is unsupported, and
  pin both host and sidecar event/matcher/command/timeout contracts.
- [x] Move the rendered dispatcher's handler parse and advisory-marker presence gate ahead of `_should_dispatch`, dev
  override resolution, runtime metadata reads, Forge launcher resolution, import, and exec.
  - Assertion: absent marker for producer/unmarked `authority-check` exits 0 structurally without resolving/importing/
    executing Forge; a present or malformed marker dispatches for full validation; every other hook keeps current
    resolution and error behavior.
  - Assertion: the 50-run/40-registry/depth-5 benchmark remains at p95 \<= 30 ms on the reference host; unit tests
    assert structural no-resolve/no-import/no-exec behavior rather than a flaky time bound.
- [x] Put the Codex authority guard at the top of the existing `codex-policy-check` command, before the raw tool-name
  `apply_patch` filter, `policy.enabled`, bundle/supervisor gates, and `CodexHookAdapter`.
  - Assertion: advisory raw `apply_patch`, `Bash`, malformed mutation envelopes, and unknown tools receive Codex's
    strict deny JSON even with policy disabled/open or no bundles; guard errors deny whenever valid output can be
    emitted.
  - Assertion: `get_builtin_codex_entries()` and rendered managed-block bytes are unchanged, so existing trust
    enrollment is not invalidated and no second Codex hook is registered.
- [x] Prove producer/unmarked compatibility for both runtimes.
  - Assertion: Claude's authority-only row declines and existing Write/Edit policy rows still decide; Codex without an
    advisory marker follows its current apply_patch policy path byte-for-byte; allowlist declines never override runtime
    prompts or other hooks.
- [x] Append `request_denied` with valid marker run id, runtime hook origin, `tool_request`, stable reason, config/hook
  digests, and covered tool only -- never the raw envelope, command, patch, prompt, or path.
- [x] Extend Docker hook and installer coverage for real registered rows, both runtime wire responses, disabled/open
  ordinary policy, malformed inputs, journal failure, and the host dispatcher fast path.
- [x] Sync the authority-before-policy boundary and fail-closed-vs-runtime-non-delivery limitation into
  `docs/design_workflows.md`, `docs/design_appendix.md`, and `docs/end-user/hook.md`.

## Phase 5 -- Honest authority posture read

- [x] Build a pure report operation that combines current manifest intent, strict journal history, runtime coverage,
  non-repairing active state, and launch-preflight evidence without persisting derived state.
- [x] Emit the same stable fields for advisory, producer, and unmarked sessions: `session`, `role`, `tier`, `runtime`,
  `active`, `launch_support`, `configuration_history`, `configured_epoch`, `covered_tools`, `read_only_tools`,
  `control_tools`, `observed_denials`, and `limitations`.
  - Assertion: not-applicable values are `null`/empty collections, not omitted; human output labels the same facts and
    never compresses them into an overall badge.
- [x] Derive configuration epochs and denials from ordered events.
  - Assertion: continuous matching configured/inherited/cleared history is `supported`; a currently marked manifest with
    absent or inconsistent history is `unproven`; unmarked plus no journal is `null`; malformed/unreadable/newer history
    is a command error rather than `unproven` or a skipped line.
- [x] Implement D5 launch-support precedence and keep it independent from configuration history.
  - Assertion: a valid unavailable seam is a successful `unsupported` read; only launch attempts refuse. Verified does
    not claim later hook delivery, response handling, authorship, admission, or tamper resistance.
- [x] Use `ActiveSessionStore.peek_session()` and strict reads; compare hashes/mtimes before and after human and JSON
  `show` to prove no manifest, journal, index, active registry, or report file changed.
- [x] Keep authority absent from status-line sources/registration/tests and keep all marking terminology out of the
  authority report.

## Phase 6 -- User flow and documentation

- [x] Add CLI reference entries for the subgroup, JSON contract, creation flags, validation matrix, generic override
  rejection, and external-human-only mutation rules.
- [x] Update `docs/end-user/session.md` with Day 1 setup/recovery: enable and sync user hooks, verify Codex enrollment,
  stop an active session before set/clear, and understand unmarked vs positive producer intent.
- [x] Update `docs/end-user/policy.md` and `docs/end-user/hook.md` to distinguish authority fail-closed decisions from
  ordinary policy fail mode and to disclose command timeout/non-delivery/dispatcher/malformed-output gaps.
- [x] Document the supported producer flow exactly: a fresh producer session in a distinct worktree, no `--resume-from`,
  transfer snapshot, transcript forwarding, generated patch, or model-curated handoff; the human carries
  requirements/findings and decides admission.
- [x] Preserve the card's claim boundaries in every surface: managed tool requests only; no OS immutability, authorship,
  Git-range, provider compliance, semantic independence, watermark detection, merge, or admission attestation.
- [x] Verify no authority status-line segment, combined marking badge, delegation command, producer lane, or generic
  model-routing change entered the diff.

## Acceptance tests (fixture-grounded)

| Test                               | Fixture                                                                                                      | Assertion                                                                                                   | Test File                                                                                            |
| ---------------------------------- | ------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------- |
| Additive intent round trip         | legacy manifest; advisory; producer                                                                          | legacy loads unmarked; valid roles round-trip strictly; schema stays compatible                             | `tests/src/session/test_models.py`, `test_store.py`                                                  |
| Role/tier validation               | advisory with omitted/named tier; producer with tier; unknown values                                         | default is `shell_closed`; invalid combinations fail before write                                           | `tests/src/session/test_authority.py`                                                                |
| Shared envelope validation         | valid authority event plus bad id/time/enum/nullability/UTF-8/semantic/newer-version variants                | valid record round-trips; every malformed shared or event-specific variant names record/field               | `tests/src/session/test_session_events.py`, `tests/src/session/test_authority.py`                    |
| Containment and domain isolation   | traversal/absolute/symlinked session targets; authority domain                                               | every escape rejects with no file; only authority path is created                                           | `tests/src/session/test_session_events.py`                                                           |
| Concurrent complete appends        | multiple processes append distinct events to one journal                                                     | exact record count, unique ids, parseable newline-complete JSON, no lost/interleaved records                | `tests/src/session/test_session_events.py`                                                           |
| Required append failure            | lock/open/write/fsync faults                                                                                 | typed error propagates; command/launch reports failure and D4 rollback invariant holds                      | `tests/src/session/test_session_events.py`, `tests/src/core/ops/test_session_authority.py`           |
| Control-plane mutations            | inactive target outside agent; active target; `FORGE_SESSION` set; unresolved target                         | only external inactive mutation succeeds; scoped refusals journal; unresolved input creates no journal      | `tests/src/cli/test_session_authority.py`                                                            |
| Adoption exclusion                 | adopted Claude and Codex sessions; set before managed resume                                                 | adoption has no authority flags and creates unmarked state; only later external inactive set designates it  | `tests/src/cli/test_session_adopt.py`, `tests/src/core/ops/test_codex_adopt.py`                      |
| Generic override rejection         | `set authority...`, `reset authority...`, and `reset --all`                                                  | keyed authority attempts reject+journal; clear-all cannot mutate intent                                     | `tests/src/cli/test_session_overrides.py`                                                            |
| Derivation matrix                  | advisory/producer parents across fresh resume, fork, relaunch, and Codex child creation                      | advisory+tier inherit; producer becomes unmarked; explicit child role wins and event origin/type is exact   | `tests/src/session/test_authority_inheritance.py`                                                    |
| One root id per attempt            | Claude host, supported sidecar or refusal, Codex headless/TUI, aborted preflight                             | preflight/start/end/marker use one root id; no remint; abort has no run-start/usage claim                   | `tests/src/core/ops/test_session_authority_launch.py`                                                |
| Unmarked launch serialization      | unmarked child plus concurrent set/second launch; unavailable active registry                                | child keeps legacy path; mutation cannot race behind it; contention is actionable without registry reliance | `tests/src/core/ops/test_session_authority_launch.py`                                                |
| Spawn-boundary lifecycle           | launcher spawn exception; spawned child exits nonzero                                                        | both terminate as error, with `child_never_spawned` distinct from `child_exited_nonzero`                    | `tests/src/core/ops/test_session_authority_launch.py`                                                |
| Claude seam preflight              | exact catch-all/current dispatcher; absent/wrong matcher/stale/missing dispatcher                            | only exact current seam launches advisory; failures name recovery                                           | `tests/src/core/ops/test_session_authority_launch.py`                                                |
| Codex seam preflight               | exact/missing/drifted/duplicate policy row; ready+enrolled and negative enrollment; consecutive resumes      | exact static policy row and positive empirical probe are both required; every attempt probes                | `tests/src/install/test_codex_hooks.py`, `tests/src/core/ops/test_session_authority_launch.py`       |
| Marker immutability/mismatch       | validated advisory marker, later manifest drift, malformed marker, wrong run/digest                          | marker is fixed; every inconsistency denies rather than consulting ordinary fail mode                       | `tests/src/cli/hooks/test_authority_check.py`                                                        |
| Named-tools raw denial             | Write/Edit/NotebookEdit/apply_patch add/update/delete/rename; malformed/path variants                        | every covered raw request denies without path carve-outs; Bash/unknown reported uncovered                   | `tests/src/cli/hooks/test_authority_check.py`                                                        |
| Shell-closed classification        | exact Claude allowlists, Bash, unknown/delegation/skill/MCP; Codex Bash/apply_patch/unknown                  | allowlisted tools receive no authority grant; every other delivered tool denies                             | `tests/src/cli/hooks/test_authority_check.py`                                                        |
| Authority-before-policy            | advisory request with policy absent/disabled/open, no bundles, malformed adapter input                       | authority denial occurs before each existing early exit/adapter                                             | `tests/src/cli/hooks/test_authority_check.py`                                                        |
| Guard error and denial-log failure | manifest read/digest/classifier error; journal append error                                                  | valid runtime deny remains; diagnostic is secret/source-free                                                | `tests/src/cli/hooks/test_authority_check.py`                                                        |
| Producer/unmarked compatibility    | existing TDD/supervisor allow+deny fixtures under no advisory marker                                         | ordinary Claude Write/Edit and Codex apply_patch results remain unchanged                                   | `tests/src/cli/hooks/test_authority_check.py`                                                        |
| Registration byte contracts        | host Claude, authority-excluding sidecar rows, and existing Codex managed block                              | host adds one no-matcher authority row; sidecar omits it; Codex bytes/row count stay exact                  | `tests/src/install/test_registered_commands_contract.py`, `tests/src/install/test_codex_hooks.py`    |
| Dispatcher early no-op             | authority handler, absent marker, managed env, populated registry, broken resolver/dev target                | exits 0 without gate/resolver/import/exec; marker-present path still forwards                               | `tests/src/install/test_hook_dispatcher.py`                                                          |
| Journal content hygiene            | config, preflight, abort, lifecycle, denial, and refusal fixtures seeded with secret/source strings          | envelope/payload exact; no prompt, raw payload, patch, command, source bytes, or candidate path appears     | `tests/src/session/test_authority.py`                                                                |
| Posture absence matrix             | unmarked/no journal; marked/missing or inconsistent; malformed; inactive capable; unsupported; live verified | exact history/support states; malformed is error; JSON fields never disappear                               | `tests/src/core/ops/test_session_authority.py`, `tests/src/cli/test_session_authority.py`            |
| Read-only show                     | valid report with stale active entry and journal                                                             | stdout/JSON correct; manifest/journal/index/active files and mtimes remain unchanged                        | `tests/src/cli/test_session_authority.py`                                                            |
| Artifact tree lifetime             | delete/clean; both transcript settings; retained/external vs containing owning worktree; incognito; failure  | no selective purge; journal survives with its Forge root and disappears only with its containing checkout   | `tests/src/session/test_authority_retention.py`, `tests/integration/docker/test_project_identity.py` |
| Human-courier producer flow        | planner advisory plus independent producer `--worktree`, no parent flags                                     | distinct checkout/conversation; no derivation/transfer artifact or automatic context                        | `tests/integration/cli/test_session_commands_integration.py`                                         |

## Phase 7 -- Verification and closeout

- [x] Run focused unit suites for the new session-event/authority modules, session models/store/inheritance, launch ops,
  CLI subgroup/flags/output streams, both hook handlers, preset/Codex registrations, dispatcher, cleanup, and
  status-line non-regression; record exact results here. The broad focused pass completed 357 tests, and the final
  journal/history/creation-lock review pass completed 108 tests after its edge-case fixes.
- [x] Run `make test-unit` and `make test-regression`; fix failures rather than skipping them. Final repaired-head
  results are recorded in Phase 8.
- [x] Run the risk-required targeted integration set through `./scripts/test-integration.sh`: authority additions in
  `tests/integration/docker/test_policy_hooks.py`, `test_installer.py`, `test_session_lifecycle.py`,
  `tests/integration/cli/test_session_commands_integration.py`, the relevant Codex session smoke, and sidecar hook tests
  if D3 support is added. The repaired targeted run passed eight cases, including both runtime deny wires, producer
  policy preservation, installed registrations, the complete advisory Claude launch lifecycle, the independent producer
  worktree flow, and omission of the unsupported sidecar authority row. Advisory sidecar remains unsupported by D3, so
  no sidecar-launch success case applies.
- [x] Run the live runtime checks appropriate to configured credentials: `forge extension doctor --json`,
  `forge extension sync`, `forge runtime preflight codex --verify-enrollment`, one advisory Claude deny, one advisory
  Codex deny, producer ordinary-policy behavior, and `authority show --json` before/during/after a run. Record any
  unavailable external prerequisite rather than substituting a mock claim. Isolated user-scope enable/sync and
  dispatcher diagnosis passed; Docker exercised Claude/Codex advisory denial, producer ordinary policy, read-only show,
  and the advisory Claude lifecycle. The host Codex enrollment check refused before a turn because the configured
  `$CODEX_HOME` lacks the `codex-session-start` registration (`attempted=false`); no empirical Codex launch claim is
  substituted for that unavailable prerequisite.
- [x] Re-run `scripts/experiments/hook-dispatcher/benchmark.py` with 50 runs, 40 registry entries, and depth 5; record
  p50/p95 and require p95 \<= 30 ms. Final shim results: p50 24.8923 ms, p95 26.7895 ms, maximum 27.14 ms; the full
  Forge import measured 617.5 ms p95 and is not on the absent-marker path.
- [x] Build wheel/sdist with `uv build`, install the wheel in a clean path, enable/sync user hooks, and verify the
  packaged dispatcher, Claude catch-all row, unchanged Codex command, and authority CLI/hook entry points. The final
  0.9.4 wheel/sdist built; an isolated wheel install completed idempotent user-scope enable/sync, exposed both authority
  command groups, installed an executable dispatcher, and produced exactly one catch-all `PreToolUse` row at 60 s.
- [x] Run `make pre-commit`, `git diff --check`, a relative Markdown-link sweep, and
  `./scripts/count-tokens.py docs/board/doing/artifact_authority_mode/checklist.md`; record results. Final repaired-head
  results are recorded in Phase 8.
- [x] Review the final diff against every card acceptance item 01-12 and epic C1-C5; explicitly confirm M2/non-goal
  exclusions and no unrelated user changes. The review found and fixed strict UTC/JSON coercion, record-context,
  inconsistent-history, pre-active marker, typed preflight-error, and creation/publication-lock edge cases. M2, route
  projection, model marking, status-line additions, delegation, attestations, and admission remain absent.
- [x] Add a proportionate completed-work entry to `docs/board/change_log.md`; propose only stable, human-approved
  lessons for `docs/board/impl_notes.md`.
- [x] Update the epic checklist with M1 evidence and shared-helper ownership; leave M2 proposed until separately
  accepted.
- [ ] After merge, move M1 `doing/ -> done/` and repoint every inbound board link.

## Phase 8 -- Multi-model review repairs

- [x] Rebase onto current `main` and preserve the merged WorkflowPolicy removal instead of resurrecting its deleted
  design text while resolving conflicts.
- [x] Require an exact static Codex `codex-policy-check` row before the existing per-attempt empirical SessionStart
  probe; keep the trust-sensitive managed-block bytes unchanged.
- [x] Close the unmarked launch/set race with the refined D4 lock boundary, without making an ordinary launch depend on
  successful global active registration; add short actionable contention errors and deterministic concurrency tests.
- [x] Remove the unenforceable sidecar authority catch-all and pin the intentional host/sidecar inventory difference.
- [x] Centralize launch-marker scrubbing and cover bare proxy Codex, wrap non-UTF-8 journal reads, enforce
  event-specific envelope semantics, include event construction in mutation rollback, replace prose-derived preflight
  reasons with typed codes, distinguish post-child launcher exceptions, and remove unused legacy active-helper
  parameters.
- [x] Re-run focused, full unit, regression, integration, pre-commit, diff, link, and token checks on the repaired
  rebased head; update the PR review interface. The consolidated authority contract pass ran 212 tests; the full unit
  and regression suites passed 9,447 tests with 117 deselected and 1,053 tests, respectively; eight targeted Docker/CLI
  integration cases passed; and `make pre-commit`, `git diff --check`, and the relative-link sweep passed. The checklist
  measured 8,572 tokens. The intentionally bypassed design-size gate measured 31,415 tokens for `design.md` and 31,273
  for `design_appendix.md`; compaction remains a separate follow-up as directed.

## Deferred and out of scope

- M2 routing journal/projection, provider-declared marking, and any marking status-line segment remain proposed.
- `os_readonly`, OS/filesystem immutability, raw-runtime/editor/human enforcement, and protection against runtime hook
  timeout/non-delivery are not implemented; the residual fail-open seam is reported.
- Delegation, automated handoff/return, a producer consumer lane, cross-runtime transfer, and prompt/model routing are
  not part of M1.
- Git-range, hunk/model authorship, textual overlap, watermark detection, signed/tamper-proof evidence, commit/merge,
  and admission/provider-compliance judgments require separate proposals.
