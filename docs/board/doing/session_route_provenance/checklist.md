# M2 execution checklist: Session Route Provenance and Marking

**Card**: [card.md](card.md) -- the normative contract. **Epic**:
[Session Authority and Provenance](../epic_session_authority_provenance/card.md). **Branch**:
`feat/session-route-provenance`, created from `main` at `3e17f4a4` on 2026-08-22.

## Current state and stop boundary

The card moved from `proposed/` to `doing/` after M1 shipped and the user accepted M2 for detailed planning. The
document-review recommendations have been incorporated into the card, but implementation is intentionally paused.

- [x] Create a separate M2 branch from current `main`; do not reuse M1's branch or an epic batch.
- [x] Move the complete card directory with `git mv` and repoint inbound board links.
- [x] Add this member checklist and preserve the epic's frozen C1-C5 vocabulary.
- [x] Resolve the prior review's transaction, schema, continuity, identity, marking, and release-proof gaps in the card.
- [x] Validate the planning-only move and documents with `git diff --check` and `make pre-commit-md`.
- [ ] **Human review gate**: approve or amend D1-D8 and this checklist.
- [ ] **Implementation authorization**: begin source/test changes only after the review gate is checked.

No source implementation, dependency change, commit, push, PR, or external provider-declaration research belongs before
those two unchecked gates.

## Decision ratification

Review these as one coherent contract; changing one may require reopening downstream phases.

- [ ] **D1 -- launch transaction and compensation.**
  - Ratify the epic C3 clarification that abort presentation requires a durably landed compensation event; compensation
    failure remains a disclosed evidence limitation and never permits child invocation.
  - Every attempt crossing the route-commit boundary writes one route commit before child invocation.
  - Existing M1 order remains authority `launch_preflight` -> `run_started` -> routing commit -> route projection.
  - Routing append failure compensates each authority journal already touched.
  - Projection failure compensates the routing journal and every authority journal already touched.
  - Compensation runs routing first, then authority, attempts every applicable journal, and aggregates secondary errors.
  - A pre-invocation M2 abort clears active state and suppresses M1 `run_ended`.
  - A landed authority abort supersedes same-run start evidence and reports advisory `launch_support=aborted`, including
    when active-state clear fails.
  - If both authority abort and active clear fail, diagnostics and limitations disclose the residual evidence ambiguity.
  - Spawn/child failures after projection retain the effective route commit.
- [ ] **D2 -- exact journal and pointer.**
  - The routing payload, route-kind invariants, fingerprint, snapshot slots, reason codes, and event semantics are
    closed.
  - `confirmed.route_commit` contains only `event_id` and `run_id`; the journal owns details.
- [ ] **D3 -- continuity state machine.**
  - Commit-plus-abort is an aborted attempt.
  - The newest effective commit and projection table own `supported | unproven | null`.
  - Cross-event structural violations are command errors, not skipped records.
- [ ] **D4 -- stable reads.**
  - `session model` is the intentional user-facing noun; `routing` remains the internal domain and no `session route`
    alias is added.
  - `model show --json` keeps one field set across all route/evidence variants.
  - A supported `route_commit` exposes journal-owned `billing_mode` and `route_scope_tags`.
  - Journal-derived `marking.launch_entries` and authoritative `marking.live_proxy_entries` remain separate.
  - `model history --json` returns validated full events in append order.
  - Runtime/config failure uses labelled fallback; manifest/journal/active-registry corruption is strict.
- [ ] **D5 -- model-practice declarations.**
  - The package-owned schema, conjunctive route tags, canonicalization, dates, URLs, overlap rules, snapshots, and
    `changed_since_launch` comparison are normative.
- [ ] **D6 -- proxy/statusline source boundary.**
  - `GET /` adds secret-free effective backend id and model alternatives.
  - `marking` declares proxy plus session sources, uses stdin request precedence, and remains exit-zero/default-off.
- [ ] **D7 -- initial all-unknown data.**
  - Production `model_practices.yaml` contains no non-unknown declarations in M2.
  - Tests use fixtures for `mark:yes` / `mark:no`; later real declarations require separate source review.
- [ ] **D8 -- completion proof.**
  - Design/end-user docs, targeted session/proxy integration, regression, package build, and clean-wheel resource
    loading are required before closeout.

## Verified pre-implementation baseline

- [x] `forge.session.events` already owns schema-v1 envelopes, `sevt_` ids, strict values, contained domain paths,
  serialized fsync-backed JSONL appends, and strict full-journal reads.
- [x] The shared domain allowlist already reserves `routing`; no routing producer or reader exists.
- [x] Every managed Claude/Codex launch path already mints one root `RunIdentity`.
- [x] M1's marked transaction appends `launch_preflight` and `run_started` before yielding to runtime launch code and
  already owns `launch_aborted` vocabulary. The yielded body is the structural M2 insertion region, not a named routing
  hook, and the current marked exit path always appends `run_ended`.
- [x] Unmarked launches retain the authority lock for the existing child lifetime; the M2 commit must not create a new
  independent concurrency seam.
- [x] Claude `confirmed.launch` is best-effort and Codex leaves it unset; M2 must not widen or repurpose it.
- [x] `session_context.py` can resolve intent/current config but has no durable route history.
- [x] Proxy `GET /` exposes effective tier mappings/defaults but not canonical `backend_id` or `model_alternatives`.
- [x] Statusline source acquisition is plan-lazy and fail-open; existing drift precedence is explicit request tier
  before proxy default.
- [x] No `route_commit`, routing validator/projector, model-practices resource, model command group, marking segment, or
  M2 test currently exists.
- [x] `[1m]` vocabulary and direct-pin lookup exist in `forge.core.models.direct_model`, but no runtime-neutral
  canonical route-model helper owns suffix removal, provider-prefix handling, aliases, and unknown output together. Five
  additional literal suffix-removal sites exist outside that module, with different lookup/routing semantics; they are
  not all interchangeable.

## Phase 1 -- Data contracts and package resource

- [ ] Add a runtime-neutral `RouteCommitConfirmed` projection with exactly `event_id` and `run_id`; add the optional
  field to `SessionConfirmed` without changing legacy `confirmed.launch`.
- [ ] Pin strict manifest round trips for absent, valid, malformed, and unknown-field projections; projection-only
  updates preserve an existing `confirmed_by` value exactly.
- [ ] Add `src/forge/core/data/model_practices.yaml` with schema version 1 and an empty `models` map.
- [ ] Define dependency-light marking types for normalized declarations, route scopes, and model slots.
- [ ] Validate exact top-level/model/declaration fields, canonical model keys, status/basis, HTTPS URLs, ISO dates,
  sorted-unique tags, tag-family cardinality, duplicate/overlapping matches, and unknown schema versions.
- [ ] Normalize missing declarations to the full unknown output object; do not store explicit unknown declarations.
- [ ] Factor runtime-neutral model-reference normalization under `forge.core.models`: reuse the existing `[1m]`
  vocabulary and catalog resolver, handle one provider prefix, aliases, unknown ids, and removed ids, and do not route
  proxy/unknown models through `resolve_direct_model_pin`.
- [ ] Inventory every literal `[1m]` remover, then repoint only equivalent catalog-lookup operations to the neutral
  helper while preserving each caller's direct-pin validation, context-limit, proxy-routing, ZDR, and fail-open/error
  behavior.
- [ ] Resolve conjunctive route scopes from proven runtime/route/backend/billing facts; never infer a missing backend or
  payer.
- [ ] Keep direct Claude and Codex backend/billing unknown in M2; do not upgrade API-key availability into payer
  evidence.
- [ ] Compare complete normalized declarations for `changed_since_launch`; return null when no launch snapshot exists.
- [ ] Test marked, unmarked, unknown, future-effective, invalid, ambiguous-match, and catalog-load failures with fixture
  data only.

## Phase 2 -- Routing journal and history projection

- [ ] Add a routing-domain module that reuses `forge.session.events`; do not fork envelope ids, enums, path containment,
  locking, fsync, or strict-read mechanics.
- [ ] Define exact route/payload/snapshot data types and serialize every required key, including explicit null/empty
  values.
- [ ] Enforce event-specific envelope rules:
  - commit: launcher + launch operation + success + null reason + root run id;
  - abort: launcher + same operation/run/payload + error + `route_projection_failed`.
- [ ] Enforce direct/proxy/custom/runtime-native payload invariants, route-kind/runtime compatibility, manifest-runtime
  continuity, and existing `BillingMode` vocabulary.
- [ ] Canonicalize and SHA-256 fingerprint only the custom route's HTTP(S) origin after userinfo, password, path, query,
  and fragment are excluded; pin same-origin collisions and reject an uncanonicalizable origin before journal mutation.
- [ ] Generate direct, tier-default, and model-alternative marking slots without collapsing route-distinct duplicates.
- [ ] Validate journal-level continuity: unique event ids, at most one commit/abort per run, commit before abort, exact
  abort payload, and no orphan abort.
- [ ] Derive effective commits and the exact D3 history-status table from validated append order, not timestamps.
- [ ] Keep structurally valid but projection-inconsistent state readable as `unproven`; fail malformed state as a
  contextual command error.
- [ ] Pin prior supported projection plus a newer aborted attempt as `supported`.
- [ ] Distinguish an absent journal (`null`) from an existing empty journal (`unproven`).
- [ ] Pin the governing rule: absent path makes no history claim; a present empty path claims initiated history but has
  no complete event capable of proving continuity.
- [ ] Pin a projection that identifies an aborted commit as `unproven`, including when an older effective commit exists.
- [ ] Pin missing compensation as an effective newer commit and therefore stale/missing-projection `unproven`.
- [ ] Preserve routing artifacts across normal delete/clean/incognito cleanup exactly like authority artifacts and
  regardless of `--keep-transcripts`.

## Phase 3 -- Required launch transaction

- [ ] Inventory every root managed-launch entry point before editing:
  - Claude host start/resume/fork/incognito;
  - Claude sidecar supported paths;
  - Codex headless start/resume;
  - Codex interactive start/resume.
- [ ] Move or complete route/context/runtime preparation so the event snapshot and child argv/env are fixed before the
  routing commit.
- [ ] Reuse the transaction's existing root `RunIdentity`; no launch path or invoker remints it.
- [ ] Use the yielded body of each caller's `with authority_launch_transaction(...)` as the structural M1 insertion
  region: marked attempts have committed `run_started`, unmarked attempts still hold the authority lock, and, after the
  preceding preparation task has fixed child argv/env, routing commit plus projection must finish before child
  invocation.
- [ ] Atomically update the two-field route projection only after every required journal append succeeds.
- [ ] Retain the exact immutable payload object used by `launch_routing_committed` and pass it unchanged to a projection
  failure's routing abort; do not reread or rebuild catalog, proxy, registry, or runtime facts during compensation.
- [ ] Expose one M1-owned compensation operation instead of importing or duplicating a private authority helper.
- [ ] On routing append failure, abort the launch and best-effort append `routing_commit_failed` only to authority
  journals already touched.
- [ ] On projection failure, abort the launch and best-effort append `route_projection_failed` to routing plus every
  authority journal already touched.
- [ ] Aggregate compensation diagnostics without hiding the primary error or allowing child invocation.
- [ ] Update `AuthorityLaunchAttempt` and the context manager's exit semantics so a compensated pre-invocation abort
  clears active state without calling `_append_run_ended`; ordinary spawn, child, cancellation, and post-child failures
  retain their existing `run_ended` behavior. Do not classify every exception from the `with` body as pre-invocation.
- [ ] Extend M1's `AuthorityLaunchSupport` and advisory reader with `aborted` precedence before `verified`, keyed to the
  live active run/config/hook digests and a matching authority abort; producer/unmarked output remains null.
- [ ] Preserve `aborted` when authority compensation lands but active clear fails, and add an M1 regression for a
  `run_started` append that becomes visible before reporting failure.
- [ ] When authority compensation and active clear both fail, report both secondary failures, keep the child suppressed,
  and add the residual authority-evidence caveat to M1's static `AUTHORITY_LIMITATIONS` without consulting the routing
  journal.
- [ ] Preserve route commitment on spawn exception, nonzero child exit, cancellation, or post-child launcher failure.
- [ ] Keep preparation failure free of routing history and preserve existing authority-preflight evidence.
- [ ] Keep `confirmed.launch` best-effort, Claude-only, and semantically unchanged.
- [ ] Verify unmarked routing does not depend on global active registration and does not weaken M1's launch/mutation
  serialization.

## Phase 4 -- Model read surfaces

- [ ] Add `forge session model show [session] [--json]` as a read leaf using command-core result types and output
  helpers.
- [ ] Add `forge session model history [session] [--json]` with the stable object wrapper and full validated events.
- [ ] Register the intentional user-facing `model` subgroup without adding a `route` alias or changing existing session
  command spellings/output streams.
- [ ] Add read-only `%session model show [session]`; reject/omit history and every mutation form.
- [ ] Update `%h`/`%help`, `%session` docstrings, and both invalid/empty usage strings to include
  `%session model show [session]`; pin their hook JSON payloads.
- [ ] Resolve omitted session names using the existing session resolver; explicit missing/ambiguous targets fail
  contextually.
- [ ] Read active state through the non-mutating strict registry path used by authority show.
- [ ] Render intent only from manifest state; do not let registry/runtime state rewrite it.
- [ ] Dereference a supported route projection through the exact journal event.
- [ ] Expose journal-owned `billing_mode` and `route_scope_tags` in supported route commitments; use null/empty values
  for inconsistent or unavailable evidence and never reconstruct them from current config.
- [ ] For an unproven projection, preserve its ids with `evidence_source=unproven_projection` and suppress unsupported
  route details.
- [ ] Preserve legacy `confirmed.launch` fallback with null event/run ids, null launch snapshots, and no synthesized
  history.
- [ ] Read live proxy state in order: authoritative runtime -> proxy config -> supported route commit -> unavailable,
  labelling each source.
- [ ] Derive `marking.launch_entries` only from journal snapshots and `marking.live_proxy_entries` only from
  authoritative runtime mappings; never relabel config or route-commit fallback as live marking evidence.
- [ ] Keep proxy default separate from `current_request_tier=null` on terminal/direct-command reads.
- [ ] Return successful fallback for unreachable/unreadable auxiliary proxy state; keep manifest, active-registry, and
  journal corruption strict.
- [ ] Pin exact direct, proxy, custom, runtime-native, legacy, no-evidence, fallback, and inconsistent JSON objects.
- [ ] Extend `tests/src/cli/test_output_streams.py` for both new read leaves.

## Phase 5 -- Live proxy truth and marking statusline

- [ ] Extend proxy `GET /` with `runtime.backend_id` and `runtime.model_alternatives` from effective loaded config,
  without credentials or session state.
- [ ] Apply the same runtime ZDR substitutions to exposed/committed tier defaults and model-alternative values that
  proxy dispatch applies.
- [ ] Extend neutral `ProxyRuntimeTruth` parsing defensively for new and older response shapes.
- [ ] Add `marking` to the exact segment-name/producer equality contract but not `DEFAULT_ORDER`.
- [ ] Declare both proxy and session sources so an opt-in marking-only layout acquires exactly what it needs.
- [ ] Resolve proxy request routing in server order: explicit request tier, proxy default; matching model alternative,
  then tier default.
- [ ] Require authoritative live proxy truth for proxy `mark:yes/no`; config/registry fallback renders `mark:?`.
- [ ] Read direct scope facts only from a supported route commit and render `mark:?` in M2 because direct backend
  identity remains unproven; keep missing/unproven/legacy evidence unknown as well.
- [ ] Omit only the segment when stdin has no model id.
- [ ] Resolve expected catalog/source/mapping failures to `mark:?`; preserve the registry's unexpected-producer
  fail-open behavior.
- [ ] Document and test that `mark:no` is provider-declared, not detected or admitted.
- [ ] Keep default statusline output byte-identical and pin source-lazy plans with marking enabled/disabled.

## Phase 6 -- Documentation and migration behavior

- [ ] Update `docs/design.md` for routing journal ownership and `confirmed.route_commit`.
- [ ] Update `docs/design_sessions.md` for the D1 transaction, root-run reuse, and compensation ordering.
- [ ] Update `docs/design_runtime.md` for `GET /` backend/alternative truth and marking-practice separation.
- [ ] Update `docs/design_telemetry.md` for marking source acquisition, fallback, and default-off ordering.
- [ ] Update `docs/cli_reference.md` §§1, 2.1, and 2.2: add both terminal leaves to the session-management table and add
  `%session model show` to the direct-command scope policy and shipped-command list.
- [ ] Update `docs/end-user/session.md`, `proxy.md`, `config.md`, `hook.md`, and `model_selection.md` for the exact
  read, statusline, fallback, provider-declaration, and direct-command contracts.
- [ ] Preserve the transfer-free producer warning and every no-attestation limitation.
- [ ] Document legacy no-backfill behavior and the fact that `supported` begins at the first M2 journal event.
- [ ] Document the intentional all-unknown production catalog and the separate source-review requirement for later
  declarations.
- [ ] Verify old manifests, missing routing journals, older proxy responses, and mixed-version statusline polls retain
  their documented fallback behavior.

## Phase 7 -- Acceptance and verification

### Fixture-grounded acceptance tests

| Test                                     | Fixture                                                         | Assertion                                                                                      | Test File                                                                                                       |
| ---------------------------------------- | --------------------------------------------------------------- | ---------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------- |
| Shared envelope reuse                    | Valid/bad M1 and M2 envelope records                            | One C1 validator owns ids, enums, paths, locks, and strict reads                               | `tests/src/session/test_session_events.py`                                                                      |
| Route payload matrix                     | Direct, proxy, custom, runtime-native payloads                  | Exact fields/nulls/maps and kind/runtime invariants                                            | `tests/src/session/test_routing.py`                                                                             |
| Exact routing abort payload              | Projection failure plus catalog/config mutation                 | Commit and abort payloads are equal; journal remains valid                                     | `tests/src/session/test_routing.py`                                                                             |
| Custom fingerprint                       | Credentials, paths, default ports, IPv6, invalid URLs           | Only canonical secret-free origin is hashed; same-origin collision is pinned                   | `tests/src/session/test_routing.py`                                                                             |
| D1 preparation failure                   | Route/context/runtime preparation exception                     | No routing event or child; authority follows existing preflight semantics                      | `tests/src/core/ops/test_session_authority_launch.py`                                                           |
| D1 authority failure                     | Required authority append or activation exception               | No routing event or child; M1 compensation remains authoritative                               | `tests/src/core/ops/test_session_authority_launch.py`                                                           |
| D1 routing append failure                | Routing append exception after authority start                  | Authority-only abort; active state cleared; no child or `run_ended`                            | `tests/src/core/ops/test_session_authority_launch.py`                                                           |
| D1 projection failure                    | Atomic projection exception after route commit                  | Routing then authority abort; exact payload; no child or `run_ended`                           | `tests/src/core/ops/test_session_authority_launch.py`                                                           |
| D1 compensation failure                  | One or both compensating appends fail                           | Primary error retained; all compensation named; no child or `run_ended`                        | `tests/src/core/ops/test_session_authority_launch.py`                                                           |
| D1 abort-aware authority read            | Visible start, landed abort, active clear failure               | Advisory support is `aborted`, never `verified`; no `run_ended`                                | `tests/src/core/ops/test_session_authority.py`                                                                  |
| D1 late M1 append failure                | Complete `run_started` visible before append reports error      | Later abort supersedes start in the shipped M1 reader                                          | `tests/src/core/ops/test_session_authority.py`                                                                  |
| D1 dual authority-state failure          | Authority abort and active clear both fail                      | Both failures disclosed; no child; residual limitation remains explicit                        | `tests/src/core/ops/test_session_authority_launch.py`                                                           |
| D1 child spawn failure                   | Successful projection, child raises before spawn                | Effective route retained; M1 records `child_never_spawned`                                     | `tests/src/core/ops/test_session_authority_launch.py`                                                           |
| D1 child exit/cancel                     | Spawned child nonzero, cancellation, post-child exception       | Effective route retained; M1 terminal outcome stays exact                                      | `tests/src/core/ops/test_session_authority_launch.py`                                                           |
| D3 absent history                        | No projection and no journal path                               | `history_status=null`                                                                          | `tests/src/session/test_routing.py`                                                                             |
| D3 empty history                         | No projection and empty journal file                            | `history_status=unproven`; file presence is not collapsed to absence                           | `tests/src/session/test_routing.py`                                                                             |
| D3 aborted-only history                  | No projection and one or more complete aborted attempts         | `history_status=supported`; no effective route                                                 | `tests/src/session/test_routing.py`                                                                             |
| D3 unprojected effective commit          | No projection and one effective commit                          | `history_status=unproven`                                                                      | `tests/src/session/test_routing.py`                                                                             |
| D3 newest projected commit               | Projection identifies newest effective commit                   | `history_status=supported`                                                                     | `tests/src/session/test_routing.py`                                                                             |
| D3 prior projection plus aborted attempt | Older effective projection, newer aborted attempt               | `history_status=supported`; prior route remains current                                        | `tests/src/session/test_routing.py`                                                                             |
| D3 missing projection target             | Nonexistent event id or mismatched run id                       | `history_status=unproven`; route details suppressed                                            | `tests/src/session/test_routing.py`                                                                             |
| D3 projection targets aborted commit     | Projection points to a later-aborted commit                     | `history_status=unproven`, even with an older effective commit                                 | `tests/src/session/test_routing.py`                                                                             |
| D3 stale effective projection            | Older projected commit plus newer effective commit              | `history_status=unproven`                                                                      | `tests/src/session/test_routing.py`                                                                             |
| D3 projection without effective commit   | Projection exists; all commits aborted                          | `history_status=unproven`                                                                      | `tests/src/session/test_routing.py`                                                                             |
| D3 malformed history                     | Duplicate/orphan/mismatched/runtime/newer/unreadable cases      | Contextual command error; no best-effort record skipping                                       | `tests/src/session/test_routing.py`                                                                             |
| Route projection isolation               | Manifest with sentinel `confirmed_by` and other confirmed state | `route_commit` changes atomically; `confirmed_by` and every other confirmed field remain exact | `tests/src/session/test_models.py`, `tests/src/core/ops/test_session_model.py`                                  |
| Projection and legacy reads              | Atomic failure, old pointer, legacy launch, absent state        | Exact dereference/fallback; no synthetic history or snapshot                                   | `tests/src/core/ops/test_session_model.py`                                                                      |
| Marking catalog and scopes               | Valid/invalid, marked/unmarked/unknown/future/overlap data      | Strict schema; conjunctive proven scope; full normalized output                                | `tests/src/core/models/test_model_practices.py`                                                                 |
| Shared model normalization               | Alias, prefix, `[1m]`, unknown, removed models                  | Neutral helper reused; caller-specific direct/context/proxy behavior preserved                 | `tests/src/core/models/test_model_reference.py`                                                                 |
| Stable model show variants               | Every route/evidence/live/legacy combination                    | Exact JSON including billing/scope and launch/live separation                                  | `tests/src/core/ops/test_session_model.py`                                                                      |
| Terminal command contract                | Both leaves, omitted/explicit/ambiguous targets                 | Intentional `model` noun, `--json`, stdout/stderr, no `route` alias                            | `tests/src/cli/test_session_model.py`                                                                           |
| Direct-command contract                  | Show, history/mutation refusal, empty/bad input, help           | Read-only mirror; exact `%h` and usage JSON                                                    | `tests/src/cli/test_user_prompt_dispatcher.py`                                                                  |
| Live proxy truth                         | Current/older/unreachable GET responses and ZDR maps            | Backend/alternatives authoritative only at runtime; fallbacks labelled                         | `tests/src/proxy/test_server_backend_identity.py`, `tests/src/core/ops/test_session_model.py`                   |
| Marking statusline                       | Explicit/default/alternative/direct/old-proxy cases             | Exact `mark:yes/no/?`; default order unchanged; source-lazy; exit zero                         | `tests/src/cli/statusline/test_statusline_registry.py`, `tests/src/cli/statusline/test_statusline_rendering.py` |
| Artifact retention parity                | Delete/clean/incognito, transcript flags, owning tree           | Authority and routing directories share one lifetime                                           | `tests/src/session/test_authority_retention.py`                                                                 |
| Managed launch composition               | Claude/Codex paths with authority absent/advisory/producer      | One root run id; required ordering; no route/authority dependency inversion                    | `tests/integration/proxy/test_session_routing_e2e.py`                                                           |
| Clean-wheel resource                     | Built wheel in isolated environment                             | Packaged empty catalog loads; read/statusline import paths work                                | `scripts/test-wheel-runtime.sh`                                                                                 |

### Managed launch integration

- [ ] Run targeted Claude host start/resume/fork/incognito cases through the real command boundary.
- [ ] Run supported Claude sidecar launch coverage with Docker.
- [ ] Run Codex headless and interactive start/resume coverage with route-native payload assertions.
- [ ] Cover authority absent, advisory, and producer launches with one shared root run id.
- [ ] Inject routing append failure and assert authority-only compensation plus no child invocation.
- [ ] Inject projection failure and assert routing+authority compensation plus no child invocation.
- [ ] Inject compensation failure and assert primary error, supplemental diagnostics, no child, and `unproven` history.
- [ ] Assert every pre-invocation M2 abort attempts marked-active cleanup and produces no authority `run_ended`; when
  the abort lands but cleanup fails, authority show reports `aborted`.
- [ ] Inject simultaneous authority-abort and active-clear failure and assert all diagnostics, no child invocation, and
  the documented temporary evidence limitation.
- [ ] Inject spawn failure after projection and assert effective route commit plus M1 `child_never_spawned`.
- [ ] Cover proxy runtime truth, config fallback, older GET response, and unreachable proxy behavior.

### Package and standard commands

- [ ] Run focused unit tests while developing, after `make` has prepared prerequisites.
- [ ] Run `make test-unit`.
- [ ] Run `make test-regression`.
- [ ] Run targeted integration through `./scripts/test-integration.sh <paths-or-pytest-args>`, not a deferred full-suite
  substitute.
- [ ] Run `uv build`.
- [ ] Install the wheel in a clean path and verify the packaged catalog plus model read/statusline import paths.
- [ ] Run `make pre-commit`.
- [ ] Run `git diff --check`, board/link validation, and token/file-size checks for the card and checklist.
- [ ] Record exact pass/fail/skip counts and disclose any unrelated failure rather than silently omitting it.

## Phase 8 -- Review and closeout

- [ ] Complete one full code/document review pass against D1-D8, acceptance 01-15, epic C1-C5, and every non-goal.
- [ ] Verify no provider marking declaration entered production without separate source review.
- [ ] Verify no route/marking read authorizes mutation or claims per-request use, authorship, detection, or admission.
- [ ] Verify authority can operate without route/marking reads and M2 does not fork M1 infrastructure.
- [ ] Update the epic checklist with aggregate M1+M2 evidence.
- [ ] Add a proportionate completed-work entry to `docs/board/change_log.md`; promote only human-approved durable
  lessons to `docs/board/impl_notes.md`.
- [ ] Re-read the commit/PR description and remove filler, inventory, and process narration.
- [ ] After merge, move M2 `doing/ -> done/`, repoint inbound links, and close the epic only when its aggregate
  acceptance and closeout are complete.
