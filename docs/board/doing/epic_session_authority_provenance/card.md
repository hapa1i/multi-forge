# Epic: Session Authority and Provenance

**Epic** -- coordinating card for the independently shippable members below. Lane: `doing/` (activated 2026-08-21);
shared contracts C1-C5 are accepted and frozen for execution. M1
[Artifact Authority Mode](../../done/artifact_authority_mode/card.md) shipped via PR #234 and is the epic's first done
member; M2 remains proposed. Coordination is tracked in [checklist.md](checklist.md), with M2 reassessment as the next
decision and no epic batch authorized.

**Purpose**: keep artifact authority and session route provenance semantically separate while preventing their journal,
run-correlation, and presentation infrastructure from drifting.

## Problem

[Artifact Authority Mode](../../done/artifact_authority_mode/card.md) and
[Session Route Provenance and Marking](../../proposed/session_route_provenance/card.md) answer different questions:

- authority: which managed session is permitted to mutate project artifacts, and what enforcement posture supported a
  run;
- route provenance: which route Forge committed for a managed launch, and what provider-declared text-marking metadata
  applied to the recorded model map.

Neither answer proves authorship, content admission, or complete runtime observation. They nevertheless share launch
entry points, JSONL mechanics, origin/outcome vocabulary, local-evidence caveats, and user-facing provenance language.
Implementing those seams independently would create two subtly incompatible evidence systems.

Generic model selection is not part of this epic.
[Model-First Interactive Session Routing](../../proposed/model_first_session_routing/card.md) is an adjacent
behavior-changing proposal; it may emit richer routing facts when present but is not required by either member.

## Members

| Id  | Card                                                                        | Delivers                                                        | Depends on |
| --- | --------------------------------------------------------------------------- | --------------------------------------------------------------- | ---------- |
| M1  | [artifact_authority_mode](../../done/artifact_authority_mode/card.md)       | Session roles, managed-tool enforcement, authority journal/read | Epic C1-C5 |
| M2  | [session_route_provenance](../../proposed/session_route_provenance/card.md) | Launch route journal/read and declared text-marking display     | Epic C1-C5 |

The members remain independently shippable. M1 does not require model selection, marking metadata, or M2's read
surfaces. M2 does not require authority roles or enforcement.

## Shared contract decisions

### C1 -- Common event envelope, separate domain payloads

Both journals use one code-owned envelope:

```yaml
schema_version: 1
event_id: sevt_...
timestamp: 2026-08-20T12:00:00Z
session: planner
runtime: claude_code
event_type: launch_preflight
run_id: run_... # nullable when no valid managed-run correlation is available
origin_surface: launcher
operation: resume
outcome: success
reason_code: null
```

`event_id` uses the `sevt_` prefix in both session journals so it remains visually distinct from usage-ledger event ids.
The envelope's `run_id` reuses Forge's existing `RunIdentity`; this epic does not introduce a parallel launch-id
namespace.

`origin_surface` is one of `external_cli`, `session_derivation`, `launcher`, `claude_authority_hook`, or
`codex_policy_hook`. `operation` is a domain-neutral lifecycle leaf when applicable: `start`, `resume`, `fork`,
`incognito`, `set`, `clear`, `tool_request`, or `runtime_event`; otherwise `null`. Event types and domain payloads
remain owned by their member card.

Outcome is one of `success`, `denied`, `refused`, `cancelled`, or `error`. A reason code is a stable machine-readable
token or `null`; human diagnostics are not the journal contract. Timestamps are UTC RFC 3339 strings. Unknown schema
versions and malformed required fields are read errors, not best-effort skips.

### C2 -- Shared run identity

The managed launcher mints the interactive child's existing root `RunIdentity` before member-specific launch preflight.
Its `run_id` is reused by:

- authority `launch_preflight`, `run_started`, and `run_ended` events when authority mode applies;
- route `launch_routing_committed` events;
- `confirmed.route_commit.event_id` and `.run_id` as the runtime-neutral latest-state pointer when M2 applies;
- the launch-owned authority marker, so delivered tool-request events can correlate to the exact managed run;
- launch diagnostics that need to identify a partially completed prelaunch sequence.

For an interactive launch, `run_id == root_run_id`, matching the current Claude, Codex, and sidecar run-tree contract.
The id identifies one Forge-managed process invocation attempt, not a conversation, lineage, model request, or
authenticated human. Preflight may consume an id even when the child is never invoked; `launch_aborted` records that
outcome, and the absence of a usage event or `run_started` event is never inferred to mean success.

### C3 -- Locked append and partial-preflight behavior

A shared helper owns path containment, dedicated lock acquisition, one-record JSONL writes, schema validation, and
secret-free serialization. Each domain retains its own file:

```text
.forge/artifacts/<session>/authority/events.jsonl
.forge/artifacts/<session>/routing/events.jsonl
```

Both journals are Forge artifact state and follow the lifetime of the containing `.forge/artifacts/<session>` tree.
`forge session delete` and `forge session clean` do not selectively remove either journal, regardless of
`--keep-transcripts`; that flag controls native runtime transcript cleanup only. Any future artifact-purge operation
must treat both journal directories identically and document a separate retention contract.

Required authority-preflight and routing-commit appends occur before child invocation, in that order when both apply.
Either append failing aborts the launch. Because two files cannot be committed atomically, a successfully appended event
may remain when the later append fails. The launcher best-effort appends a same-`run_id` `launch_aborted` event to every
journal it already touched. Readers present that attempt as aborted; they never infer that the child ran.

When M2 applies, the launcher writes `confirmed.route_commit` as the latest-state projection after every required append
succeeds. A projection failure also aborts the launch and triggers compensating events in every journal already touched.
Existing Claude-only `confirmed.launch` retains its Anthropic API-key and cost-baseline meaning; it is not widened to
Codex.

Required journal and projection writes are durable session-state commits, not best-effort telemetry. In particular, M2's
one-routing-event-per-invoked-launch contract cannot be met by launching and degrading later to `unproven`, so M2
intentionally strengthens the current best-effort `confirmed.launch` posture. Once a member is activated, its required
prelaunch writes apply to every launch in that member's stated scope even when the user has not requested a history read
or status-line segment.

Denial logging remains subordinate to enforcement: failure to journal a denied tool request never converts deny to
allow. Configuration-history writes retain the stricter authority-card failure posture.

### C4 -- Evidence language and absence states

Both members use the same evidence vocabulary:

- `supported`: the relevant local journal is readable and continuous for the claim being shown;
- `unproven`: current confirmed/configured state implies history should exist but the local journal does not support
  continuity;
- `null`: the state makes no history claim and no journal is present;
- `unavailable`: the fact requires a runtime source the current command does not possess.

Local journals are append-only by convention, not tamper-proof. No member upgrades missing evidence into a negative
claim. Every human and JSON read distinguishes intent, committed route facts, live runtime facts, and unavailable
observations.

### C5 -- Presentation stays separated

V1 does not merge authority and marking into a single provenance badge:

- authority role/tier remains on `forge session authority show`; M1 adds no status-line segment in v1;
- M2 may add its distinct default-off `marking` segment because only the status-line stdin can identify the current
  Claude request model;
- marking never changes the authority color, label, role, or enforcement posture;
- shared limitation text may be reused, but domain labels remain explicit.

This prevents `producer + mark:no` from reading as an authorship or admission attestation and avoids presenting an
advisory model's marking declaration as an enforcement property.

## Sequencing

1. Freeze C1-C5 in the epic before either member moves to `todo/`.
2. Implement the shared envelope/lock helper in the first active member, reuse the existing root-run identity, and keep
   neutral tests on that member's branch.
3. The second member consumes the existing helper and may not fork its enums or absence-state semantics.
4. If both members are accepted together, they may use an epic-authorized batch only after the epic records fixed
   membership, order, branch base, shared-file ownership, and integrator. Otherwise use ordinary per-card execution.
5. Design and end-user documentation is reconciled after each member ships; neither member documents the other as a
   prerequisite.

M1 may execute first because its enforcement value does not depend on M2. M2 may also execute first if the shared helper
is kept authority-neutral. The second member must run the first member's journal and run-correlation regression tests.

## Drift watch

- envelope field names, enums, timestamp format, and schema-version handling;
- `run_id` minting and propagation across start/resume/fork/incognito/Codex entry points and authority markers;
- journal path containment, lock naming, append failure, and malformed-read behavior;
- `supported | unproven | null | unavailable` meanings;
- no-attestation and local-tamper caveats;
- status-line terminology and the prohibition on a combined authority/marking badge;
- session deletion, transcript-retention flags, and any future artifact-purge behavior for both journal directories.

## Epic acceptance boundary

1. Both member cards link this epic and use C1-C5 without local vocabulary variants.
2. One shared implementation seam owns envelope validation, ids, locks, and complete-record appends.
3. A managed launch attempt has one existing root `run_id` across every member journal it touches; when M2 applies,
   `confirmed.route_commit` points to its exact routing event with both event and run ids.
4. Cross-journal partial preflight is visible as aborted and never presented as a started run.
5. Authority enforcement never depends on routing/marking availability, and routing reads never authorize mutation.
6. The JSON reads distinguish local-history support from live-runtime availability.
7. Status-line presentation remains domain-separated and default-off where added.
8. Aggregate regression tests cover one launch with both members active, either member active alone, one required append
   failure, one malformed journal, and one forced-child authority inheritance case.
9. Session deletion and cleanup preserve both journals with Forge artifacts regardless of `--keep-transcripts`; any
   future artifact-purge path applies the same decision to both journal directories.

## Out of scope

- Generic model-to-route selection or changes to legacy `--model`.
- Per-request interactive session correlation.
- Watermark detection, content analysis, or signed-file provenance.
- Git-range, per-hunk, authorship, admission, or tamper-proof attestations.
- Combining the two journals into one file or the two read surfaces into one verdict.

## Closeout

(pending)
