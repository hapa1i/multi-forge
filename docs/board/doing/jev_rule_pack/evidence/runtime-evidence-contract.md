# A2 runtime evidence proposal

Status: proposed contract for offline implementation review. No declaration loader, action envelope, activation command
or dispatch described here is implemented. This document authorizes no repository collection, provider request or native
trial. The [selected rule contract](initial-rule-review.md) and [evaluation plan](evaluation-plan.md) retain their
human-label, quality and admission gates.

## Smallest supported scope

Use a declaration explicitly selected by the project owner when activating one session. Copy its exact bytes into a
session artifact and bind the snapshot to the acknowledgment. The declaration supplies intended policy authority for
exact files; the action supplies code evidence. Neither source can substitute for the other.

For this first contract, a file declaration must apply uniformly to every interface in that file. Every relevant file in
one action must resolve to the same surface/exception pair. Mixed interfaces within a file, mixed facts across files,
missing entries and unknown applicable facts produce unavailable with zero dispatch. Do not select convenient files or
apply an internal classification inferred from a path. This limits evidence admission, not the selected wrapper family:
methods, aliases, callbacks, decorators and module functions remain candidates when their evidence is covered.

Known stable surfaces remain not applicable even when exception status is unknown, following the shared table. The
uniform-action restriction preserves the existing single `scope_facts` object and three questions. Supporting different
facts per symbol or file would require explicit scope mapping and reviewed question/evidence changes; it is not implicit
in this proposal.

## Existing seams and proposed owners

The current [shared activation builder](../../../../../src/forge/core/ops/policy.py) validates the supported bundle
vocabulary before its callers write policy intent. `PolicyIntent.bundle_config` is already a per-bundle mapping. The
[consent helper](../../../../../src/forge/policy/rule_pack/consent.py) binds validated settings to the session name,
creation time, Forge root and worktree. Its raw-override guards reject Jev configuration writes, and derived sessions
discard Jev selection and configuration. These are foundations; the builder does not yet admit `jev_rule_pack`.

Extend that shared activation owner to validate the selected declaration and build the immutable reference before
publishing any enabled intent. Put declaration validation and action preparation under `policy/rule_pack/`; do not make
the transport or supervisor responsible for governance. The existing
[session artifact root](../../../../../src/forge/session/artifacts.py) supplies project-local storage ownership. A new
rule-pack subdirectory beneath that root is proposed; no new artifact field or storage implementation exists today.

The current [Claude adapter](../../../../../src/forge/cli/hooks/policy.py) retains full tool input but truncates
`new_content`. The [Codex adapter](../../../../../src/forge/cli/hooks/codex_policy.py) builds truncated per-file views
and omits delete operations. The [explicit CLI](../../../../../src/forge/cli/policy.py) also truncates its contexts.
Their pre-truncation fingerprints identify content but cannot recover it. Capture the new envelope before these
projections while retaining the existing contexts for existing policy evaluation.

## Owner-selected declaration

Accept one bounded UTF-8 JSON document, schema version 1, with no includes, executable expressions, inferred entries,
wildcards or inheritance. Proposed local limits are 64 KiB and 256 exact file entries. These are implementation bounds,
not paid request allowances. Reject duplicate JSON keys, unknown fields, invalid Unicode, excessive nesting and any
ambiguous or unsupported version atomically.

The document records a declaration ID/revision, the selected rule/contract versions, an attributed owner and a review
reference. Each entry contains:

- An exact worktree-relative file path and `uniform_scope: true`, asserting that the policy applies to all interfaces in
  that file, including the proposed change. This is an owner assertion, not a conclusion obtained by reading code.
- One surface from the shared applicability vocabulary: internal, public preview, public stable or unknown.
- One compatibility decision: not approved, approved or unknown. An internal approved exception is invalid under the
  selected rule. An approved preview exception requires an attributed decision reference.
- A bounded local basis/reference for reviewing the assertion. This text is provenance, not additional model evidence.

Require explicit resolved values. An omitted file or field never means internal, preview or no exception. An owner may
resolve the coding-standard defaults while authoring a declaration only after affirming that the declaration is complete
for the exact scope and that absence of a stable designation/exception is meaningful there. The loader does not search
for declarations or apply defaults from silence. A file with both public and internal interfaces cannot honestly claim a
uniform surface and is unsupported by this initial format.

At activation, display the exact admitted paths, their facts, source digest, declaration revision and review reference.
Disclose that supplied action content and enumerated policy facts are sent to the provider, then require the session's
paid-data acknowledgment. The owner is selecting governing policy, not labeling example outcomes. No model or agent
action can create authority by placing an approval comment in a file. Accepting the declaration does not prove its
factual accuracy or supply a human calibration label.

The trusted boundary is the operator and trusted local configuration writers, matching the existing acknowledgment.
Neither a claimed reviewer name nor an unkeyed hash authenticates a human. A process able to rewrite the local manifest
and Forge artifacts can forge both. This contract prevents accidental scope drift and action-text substitution; it does
not create a privilege boundary against the same operating-system user.

## Snapshot, replacement and revocation

Read only the explicitly selected declaration at activation. Admit a bounded regular file, refuse symlink components or
a changing read, and hash the exact bytes that were parsed and displayed. Use one opened file identity and verify its
metadata around the bounded read. Do not enumerate its directory or resolve its prose references. Failures leave
existing session policy intact; activation never publishes a partial acknowledgment or declaration.

Proposed storage is `.forge/artifacts/<session>/rule_pack/declarations/<sha256>.json`, derived through the session's
artifact owner rather than a caller-controlled destination. Persist the bytes atomically with private permissions. Keep
only the immutable reference, content hash, declaration schema/revision and rule/contract identity in validated bundle
settings. The existing acknowledgment's settings digest then binds that reference; local source-path and reviewer
metadata remain inspectable provenance. Runtime must verify the snapshot's bounded bytes and digest before use.

The pinned snapshot is the session's policy authority. Editing, deleting or moving the original input file does not
silently replace or revoke it, and hooks do not reread that path. The activation preview must state this behavior.
Changing governance requires explicit replacement through the validating operation or disabling the bundle. Replacement
creates a new snapshot and acknowledgment; disable revokes the existing grant before another dispatch. Missing/corrupt
snapshot bytes, a mismatched grant, changed session/worktree identity or incompatible rule/contract version yield
unavailable with zero calls. A new source revision is not discovered automatically.

Resume of the same session retains a matching pinned declaration. Fork, fresh-resume and relaunch children inherit no
Jev activation or acknowledgment and need their own review and grant. A changed declaration/settings digest invalidates
cached results; it must not revive an earlier grant from overrides. Bound snapshots and references separately from
decision-log entries. Retain referenced artifacts for audit under the later A2 retention/deletion owner; disable revokes
dispatch permission without erasing evidence. That lifecycle must be implemented and tested before activation ships.

Only the resolved enumerated facts enter model state. Declaration prose, owner names, review references, local source
paths and absolute worktree paths remain local. The evaluated evidence identity binds the declaration hash and selected
entries locally. Adding declaration prose or auxiliary files to provider payloads would require a revised data scope,
disclosure and acknowledgment; this proposal does not authorize it.

## One complete action envelope

Capture an immutable envelope from one native tool call, or one explicit CLI input, before presentation truncation and
before any per-file omission. Proposed bounds are 64 KiB of supplied UTF-8 action text and 64 file operations. An input
over either bound is unavailable; never retain or evaluate only its prefix. The eventual serialized A1 request must also
fit the current 30,000-byte admission limit, including questions and facts.

Keep origin, native tool kind, session/worktree identity, supplied path spellings, exact action text, operation order
and parser/envelope versions. Store normalized worktree-relative paths separately. Preserve each operation's source and
destination path, its type, and its complete relevant supplied text; represent deletion-only operations explicitly. Do
not add repository files or transcript context while normalizing.

| Input             | Retained action                                       | Initial admission limit                                 |
| ----------------- | ----------------------------------------------------- | ------------------------------------------------------- |
| Claude Edit       | Full old/new strings and `replace_all`                | Single replacement; sufficient supplied definitions     |
| Claude Write      | Full proposed content                                 | Unavailable without attributed prior-interface evidence |
| Codex apply_patch | Complete original envelope and every parsed operation | Supported grammar and attributable paths                |
| CLI diff          | Complete supplied diff and file boundaries            | Separate cohort; supported text changes only            |
| CLI file          | Explicitly selected full file content                 | Same prior-interface limitation as Write                |

An Edit with `replace_all=true` is unavailable in this first contract: without a before-image, the number and positions
of actual replacements are not known. With `replace_all=false`, assess only the supplied proposed replacement; do not
claim that the old text exists uniquely on disk. Semantic coverage still requires complete relevant definitions and
contracts. A native tool's eventual match failure does not retroactively create evidence. Write and Add File cannot
invent an empty before-image; the existing Write applicability gate remains in force.

The [Codex parser](../../../../../src/forge/cli/hooks/codex_patch.py) already exposes move source and destination paths,
but its parsed sections normalize line endings. Preserve the original patch text for action identity and record parser
version with the evaluation representation. A parsed hunk is not proof of a complete function or replacement contract.
Binary/combined diffs, unsupported operations or unassignable sections are unavailable. Do not interpret an empty or
malformed adapter result as a covered clean action.

Normalize paths against the session's pinned worktree and the verified native action directory, not an arbitrary process
directory. Reject paths outside that worktree, traversal, NULs, duplicate/conflicting destinations, ambiguous aliases
and symlink components. For a new destination, inspect only its existing parent components. These checks use metadata
for the supplied targets, never file-body reads or repository enumeration. An unresolvable path or observed metadata
race is unavailable. The check does not lock the filesystem through the later native tool execution.

A move requires declared, matching facts at both the source and destination; its old interface and proposed location
must not silently acquire different policy. Deletions stay in the full identity and attribution record. A deletion-only
action is not applicable, not a model success. For a mixed action, a deleted source may supply relevant interface
history only when that text is actually present in the supplied envelope. A bodyless delete cannot invent it.

Resolve declarations for every non-delete operation and every move endpoint, and apply one uniform facts pair to the
whole action. Missing, mixed or ambiguous facts make the action unavailable with zero dispatch. If any applicable
operation is locally unsupported, send none of the action. Host-decided inapplicability still follows the shared table;
the proposed preparation layer must account for every operation and never call a partly covered action clean. This
preserves the current question contract without extending it to per-file governance.

## Evidence identity and orchestration boundary

Maintain three separate identities: the full canonical action envelope, the exact evaluated state, and the rendered
presentation excerpt. Evaluated state identity covers supplied bytes, normalized paths, operation attribution,
completeness, selected declaration entries/snapshot hash, rule/contract/question/decision versions and parser version.
Requested endpoint/model and decision settings remain part of cache identity; retain the resolved model with results.
The legacy per-file `action_fingerprint` remains available to existing consumers, but cannot stand in for this complete
multi-file action or reconstruct missing bytes.

Run existing policies/resolvers once per file in their existing order, then inspect the whole action's results. Any deny
or unresolved review yields `skipped_blocked`, zero A2 attempts and no assessed verdict. Only after that phase may the
proposed runner prepare one bounded shared state and at most one request. Preparation and I/O share the existing hook
deadline and A2's five-second cap from the [execution checklist](../checklist.md); this proposal creates no new deadline
or fallback. Failure to acquire facts or evidence must never add a Jev denial or review request.

## Offline proof and remaining review

Fixtures can now exercise snapshot selection, immutable source bytes, replacement/revocation, malformed declarations,
copied grants, unknown/mixed scope, move endpoints, path rejection, unchanged source-file edits, complete long inputs,
`replace_all`, unsupported operations and all-or-nothing preparation without credentials or a client. They must also
prove that action comments cannot alter scope and declaration prose never enters a model payload. These are planned
implementation checks, not completed tests or model-quality evidence.

The proposed initial limitation needs explicit contract review before runtime admission: owner-attested, exact-file
uniform scope, one facts pair per action, and pinned authority that changes only by replacement/revocation. If useful
actions require mixed scopes, revise the evidence/question contract and evaluation corpus before widening admission. No
production declaration or quality threshold is selected here. Human adjudication and numerical quality choices remain
owned by the evaluation plan; live payload approval and native delivery remain separate gates. Offline fixtures and a
reviewable implementation of this contract can proceed without deciding those later gates.
