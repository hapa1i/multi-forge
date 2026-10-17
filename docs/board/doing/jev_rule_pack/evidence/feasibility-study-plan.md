# A2 feasibility study proposal

Status: the user approved the first local acquisition scope on 2026-10-16. Numerical gates remain draft. No local
session metadata, native transcript, historical diff or caller inventory was collected to write this proposal. It
defines a bounded local inventory before the [runtime proposal](runtime-evidence-contract.md) is implemented. The 17
constructed judgments remain unchanged. The
[evaluation plan](evaluation-plan.md#before-real-evaluation-or-runtime-admission) owns evaluation order and the separate
approvals for provider captures.

The acquisition approval permits only that local inventory and its private review packet. It does not approve the
proposed numerical gates, establish repository governance, authorize publication of extracted code, or permit provider
calls. Record those decisions separately.

The [first acquisition result](feasibility-progress.md#approved-local-inventory) records missing selected sources and
zero native content reads. The implementation currently stops at metadata and source-path admission.

## First acquisition: native action sufficiency

The first question is whether the evidence a hook receives can support the rule often enough to justify runtime work.
Sample recorded Claude `Edit`/`Write` and Codex `apply_patch` proposals without enlarging their evidence. These records
preserve native action shape; they do not prove that Forge received a hook, that permissions allowed the proposal or
that the tool succeeded. Do not infer those facts from their presence in a transcript.

Use the following fixed scope. Shortfalls remain visible; no cap, date window or runtime allocation expands implicitly.

| Boundary             | Proposed limit                                                              |
| -------------------- | --------------------------------------------------------------------------- |
| Repository           | `/Users/habib/workspace/multi-forge` and its verified managed Git worktrees |
| Action timestamps    | `2026-10-01T00:00:00Z` through, but excluding, `2026-10-17T00:00:00Z`       |
| Candidate metadata   | One session index, one active index; at most 24 matching manifests          |
| Selected sessions    | Up to three Claude and three Codex sessions, at most six total              |
| Native files         | One confirmed transcript/rollout per selected session                       |
| Native read limits   | 20 MiB per file, 120 MiB total, 1 MiB per JSONL record                      |
| Sampled actions      | Latest 20 named-tool proposals per selected session; at most 120 total      |
| Retained action size | At most 64 KiB and 64 file operations per complete action                   |
| Private packet       | At most 120 actions and 8 MiB, plus a bounded metadata ledger               |

The end date includes only records already present when the snapshot is taken. Sort sessions by `last_accessed_at`
descending, breaking ties by canonical session identity. Within each runtime take the first three eligible metadata
rows, then select the latest 20 named-tool proposals in each admitted native file, ordered by timestamp and native
record ordinal. Select before checking wrapper content or predicted outcomes. A missing, oversized or unprovable source
consumes its selected slot; report the shortfall rather than replacing it with a more convenient example.

Inspect only default local stores: `~/.forge/sessions/index.json`, `~/.forge/sessions/active.json`, confirmed project
manifests, and their selected native sources under `~/.claude/projects/`, `~/.codex/sessions/` or the owning project's
`.forge/artifacts/<session>/transcripts/`. Bound each index to 8 MiB and each manifest to 256 KiB. Custom native homes,
remote hosts and sidecar sessions need a revised selection. Do not discover other native conversations by scanning their
contents or recursively following transcript ancestry.

### Metadata before content

1. Read the indexes without invoking repair, migration, reconciliation, launch or adoption. Keep only rows whose
   `project_root` identifies this repository. Verify worktree membership from Git metadata before following a manifest
   path; retain only repository identity, session identity, runtime, timestamps, worktree, active status and confirmed
   native ID/path. Discard other index and manifest fields immediately. No credentials, environment values, user task,
   policy notes or general Forge configuration enter the acquisition output.
2. Exclude active sessions, uncertain liveness, sidecars, ambiguous identities, unsupported schemas and paths outside
   those stores. `last_accessed_at` selects candidates; it is not proof that a session completed. The durable
   [session models](../../../../../src/forge/session/models.py) have no generic completed flag. The
   [active store](../../../../../src/forge/session/active.py) also has repairing read paths, which this study must
   avoid.
3. Inspect the bounded native identity/header and completion metadata only after selection. Require the recorded native
   ID and CWD to match the managed session, an understood completed-turn boundary, and stable file identity/size around
   the read. Freeze at the last such boundary. Unknown formats or completion states are exclusions, not guesses. Do not
   borrow the Codex supervisor's version-specific admission rules as proof that another native format is parsed.
4. Refuse symlink components, non-regular files, ambiguous copies and changed reads. Use the confirmed source;
   [Claude path ownership](../../../../../src/forge/session/claude/paths.py) and
   [Codex rollout ownership](../../../../../src/forge/core/runtime/codex_rollouts.py) describe where it belongs, not
   permission to search for replacements. A missing confirmed path remains missing.

The extractor must read JSONL bytes locally to identify record types. It may transiently parse records containing
messages, but it must expose and retain only the allowlisted metadata and named tool arguments. Exclude user/assistant
prose, reasoning, instructions, tool results, images, subagent logs and usage/auth records. For Claude, take only
`tool_use` blocks named `Edit` or `Write`. For Codex, take only an understood tool-call representation named
`apply_patch`; do not interpret arbitrary shell commands as patches. Count other tool names without retaining their
arguments. This sample measures the named mutation tools, not all ways an agent can modify a repository.

### Local sanitization and retention

Validate the selected action's complete envelope before retaining code. Keep paths relative to the verified worktree;
reject traversal, out-of-worktree targets and symlink ambiguity. Exclude any action touching `.env*`, credentials,
private keys, auth/config stores, `.forge/`, `.git/`, native stores, or known secret-bearing files. Run a local secret
screen on the remaining payloads. A match excludes the whole action; retain only its exclusion reason, never the matched
secret. An oversized, malformed or unsupported action is counted but never truncated into an apparently covered case.

Do not rewrite code literals or remove comments to make evidence admissible. A path normalization that changes an
argument must retain separate source-action and normalized-action digests and a transformation version. Suspected
sensitive code that cannot be screened confidently stays excluded. Screening reduces exposure; it is not proof that a
private action is safe to publish or send to a provider.

Store the inventory in a new private directory such as `/private/tmp/jev-a2-feasibility-<id>/`, mode 0700 with files
0600\. Keep pseudonymous session/family IDs, native ordinal and timestamp, action hashes, shape/size counters and bounded
reason codes. Keep the raw identity/path lookup in a separate private ledger. Retain only the sampled action payloads
that pass sanitization; do not copy complete transcripts. Do not print raw payloads into shell output or this chat. The
user selects any examples for a subsequent human-review corpus. Aggregate counts may be proposed for this card after
review; private payloads and source identifiers do not enter Git, the PR, a cloud artifact or a model request by
default. Retain the private packet through the scope review, then record its explicit retention or deletion decision.

## What the inventory measures

For every selected action, report runtime/tool shape, all supplied operations, prior/replacement definition
completeness, `replace_all`, supported syntax, input/request size, path attribution and each refusal reason. Compute
structural completeness against the original bounded action, without reading a current file, neighboring transcript turn
or Git before-image to repair missing evidence. Keep Write/Add File's absent history visible. An action containing
several file operations remains one action; a complete function in one file cannot compensate for an unsupported
operation elsewhere.

Report three denominators: all selected named-tool proposals, selected proposals with known applicable governance, and
those admitted to semantic assessment. Show exclusions before each denominator, including source-level shortfalls.
Unknown governance stays unknown. The repository's policy prose or importability does not substitute for the
owner-approved default and exceptions in the runtime proposal. An optional count assuming a clean-break default is a
conditional upper bound, not observed coverage or permission to dispatch.

After the owner selects a declaration for review, measure mapping against supplied actions only: uniquely resolved
symbols, partial method/alias/rename ambiguity, mixed applicability and path-only exceptions. Do not declare the mapper
feasible from a cohort with no touched exceptions. Keep completeness and mapping judgments separate from semantic human
labels. A narrow offline mapper or manual review can supply these measurements without implementing runtime activation.

Assign related actions from the same originating change, session lineage or shared template to one source family.
Deduplicate copied native IDs and repeated action hashes without hiding repeated proposals from the workload counts.
Freeze family assignments before quality scoring and keep each family in one split. Treat unknown relationships
conservatively as one family. The recency sample is a small local convenience cohort, not an estimate for all Forge
users.

## Separate semantic and usefulness evidence

Keep the native-action inventory distinct from reconstructed Git changes and CLI whole diffs. If it has too few positive
examples, propose a separate bounded Git acquisition naming exact revisions and paths before collection. A reconstructed
full-definition Edit can help test semantic discrimination, but cannot establish how often native tools supply those
definitions. Constructed mutations remain constructed, even when derived from real code. Do not add them to real-action
coverage, warning burden or historical-positive counts.

The existing 17 judgments remain one constructed cohort. New case labels require the same hash-bound human-review
workflow, with model outputs withheld. Keep per-question unknowns, host decisions, disagreements and exclusions. The
already exposed held-out scenarios support only a limited output check; new generalization claims require new scenarios
that were not used to develop the rule or thresholds.

Usefulness needs a second, separate human review of affected callers and contracts. First identify candidate warnings
from packet labels or a frozen detector, then propose exact frozen repository revisions/files for that wider review. The
native acquisition above does not authorize that expansion. A later bounded review can record `useful`, `unhelpful` or
`unresolved`, references and reviewer minutes. Useful means it identifies unnecessary retention worth changing; a
legitimate unseen consumer requirement is unhelpful, not a retroactive change to the packet-bound label. Unresolved or
unreviewed warnings stay in the usefulness denominator and receive no useful credit. Never add the wider context to the
original model input silently.

## Proposed exploratory decision criteria

These are reviewable starting points, not accepted settings, calibrated question bands or a production release claim.
Ratify or revise them after the metadata inventory establishes available strata and before looking at new model outputs.
Preserve the rejected proposal and rationale if a limit changes. Do not lower a gate after seeing a failing model
result.

| Concern              | Proposed minimum or limit                                                                       |
| -------------------- | ----------------------------------------------------------------------------------------------- |
| Native sampling      | 60 actions; at least 30 and two sessions per claimed runtime                                    |
| Supplied evidence    | At least 25% of all selected actions and 50% of known-applicable actions fully admissible       |
| Governance           | At least 90% of selected in-worktree actions have owner-attributed applicability                |
| Exception mapping    | At least 10 real touched-exception actions in three families; at least 80% uniquely mapped      |
| Mapping mistakes     | Zero false exemptions or falsely admitted ambiguous actions in human review                     |
| Semantic strata      | At least 10 positive and 20 negative cases across five families per class                       |
| False positives      | At most 10% point rate; nominal Wilson 95% upper bound at most 25%                              |
| Effective misses     | At most 20% point rate; nominal upper bound at most 45%, including pipeline misses              |
| Practical usefulness | At least 10 warnings in five families; at least 80% useful and nominal lower bound at least 50% |
| Warning burden       | At most 15% of the unfiltered native action sample; report useful warnings per 100 actions      |

The coverage floors reject a design that cannot assess most applicable actions while hiding its refusals. Governance and
mapping floors require evidence that the declaration can be applied rather than merely parsed. The error/usefulness
limits are loose feasibility screens intended to justify further development, not promises to users. They do not make
five families independent. Report counts by family and session and the interval assumptions alongside every point rate;
the nominal Wilson intervals are descriptive under this clustered sampling. A concentrated or overlapping family set
requires an explicit limitation or additional evidence even when the numerical screen passes.

For semantic gates, positives/negatives refer to human packet-bound labels. Count unavailable/uncertain or missing
assessments on positives as effective misses, including host refusals in the pipeline measure. Report assessed-only
false positives alongside coverage so abstention cannot manufacture a good verdict. Apply the minimums and limits to the
claimed evaluation split and real-evidence cohort, not pooled constructed cases or repeated requests. A missing stratum
is inconclusive. The current constructed held-out positive cannot satisfy these minimums.

Warning burden uses the native workload cohort, not an enriched positive sample. Usefulness may be reviewed in an
explicitly selected warning cohort, but then report that selection and do not extrapolate its prevalence. Count pending
usefulness reviews against the floor. Keep median/p95 review minutes and unresolved reasons visible; numerical quality
cannot justify a warning stream the owner judges too costly to act on.

Compare today's marker checks, a bounded AST baseline and Jev on identical supplied bytes, scope facts and admission
limits. Freeze baseline syntax/candidate rules before held-out outputs. Compare paired disagreements and review at least
three independently sourced cases where a paid semantic assessment is useful beyond the strongest deterministic baseline
before choosing the paid path. If no such value appears, prefer revising or stopping that path over shipping equivalent
paid warnings. Repetitions measure response variation; they add no cases or families.

## Decisions before runtime work

1. Approve, narrow or decline the first local acquisition scope. Run only the approved scope and review its counts and
   private candidate packet. No provider authorization is requested at this step.
2. Review the owner declaration, available independent families and these proposed criteria. Either ratify a bounded
   evidence claim and predeclare its gates, or record that the available data cannot support it. Additional native,
   historical or caller/contract reads need their own concrete scope.
3. Prepare and separately authorize calibration captures under the evaluation plan. Use calibration responses only to
   choose question bands, then freeze contract/settings/baselines before separately approved held-out capture. Local
   collection approval never carries repository content into either provider manifest.
4. Record `proceed`, `revise/narrow` or `stop` from the full evidence. A proceed decision permits the agreed runtime
   implementation scope; it does not activate paid sessions. Sparse strata or wide intervals mean inconclusive and
   further bounded evidence, not an automatic pass. If action completeness or mapping fails, revise the proposal before
   building it. Constructed-only success remains a smoke test.
