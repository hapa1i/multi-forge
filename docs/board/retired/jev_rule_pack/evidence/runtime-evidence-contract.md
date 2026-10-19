# A2 runtime evidence proposal

Status: proposed contract for offline implementation review. No declaration loader, action envelope, activation command
or dispatch described here is implemented. This document authorizes no repository collection, provider request or native
trial. All 17 constructed cases have human labels, but the
[evaluation plan's feasibility stage](evaluation-plan.md#before-real-evaluation-or-runtime-admission) must establish
representative action coverage, governance/exception mapping and practical warning usefulness before implementing this
proposal. The [selected rule contract](initial-rule-review.md) retains its broader wrapper scope.

## Project policy and action evidence

Use a declaration explicitly selected by the project owner when activating one session. Copy its exact bytes into a
session artifact and bind the snapshot to the acknowledgment. The declaration supplies an explicit project-scoped
clean-break default and scoped exceptions; the action supplies code evidence. Neither source substitutes for the other.
The owner does not enumerate every file or claim that every interface in a file has the same surface classification.

Keep surface classification separate from effective rule applicability. Internal interfaces and public-preview
interfaces without an approved exception have the same clean-break requirement and can share an applicable batch.
Applying an owner-approved project default establishes that requirement without asserting that an interface is internal
because of its path or public because it is importable. Known stable surfaces and approved public-preview exceptions
remain outside this rule; an unknown or conflicting governance decision remains unavailable.

The proposed resolver must attribute exceptions to the affected interfaces before batching. Matching only a filename
cannot exempt unrelated helpers. Methods, aliases, callbacks, decorators and module functions remain within the selected
wrapper family when their supplied evidence and applicability are covered. A demonstrated protocol requirement is
semantic boundary evidence, not an approved governance exception.

## Existing seams and proposed owners

The current [shared activation builder](../../../../../src/forge/core/ops/policy.py) validates the supported bundle
vocabulary before its callers write policy intent. `PolicyIntent.bundle_config` is already a per-bundle mapping. The
[consent helper](https://github.com/hapa1i/multi-forge/blob/39ba8cbb49d2ca3906f196edae2b139705a51bf1/src/forge/policy/rule_pack/consent.py)
binds validated settings to the session name, creation time, Forge root and worktree. Its raw-override guards reject Jev
configuration writes, and derived sessions discard Jev selection and configuration. These are foundations; the builder
does not yet admit `jev_rule_pack`.

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

Accept one bounded UTF-8 JSON document, schema version 1, with no includes, executable expressions, glob precedence or
inherited declarations. Proposed local limits are 64 KiB and 256 exception entries; the exception bound does not limit
the number of project files governed by the default. These are implementation bounds, not paid request allowances.
Reject duplicate JSON keys, unknown fields, invalid Unicode, excessive nesting and any unsupported version atomically.

The document records a declaration ID/revision, the selected rule/contract versions, an attributed owner and a review
reference. Its proposed fields are:

- `project_scope`: the selected session worktree root, represented as `.` in the document and bound to its canonical
  identity at activation. Outside-worktree actions are not covered. There is one project scope, not a directory rule
  hierarchy.
- `default_applicability`: explicitly `clean_break_required` or `unknown`. The first requires the owner's affirmative
  statement that the declaration accounts for every stable designation and approved compatibility exception in this
  project scope. Missing or incomplete authority resolves to unknown; there is no automatic default from silence.
- `exceptions`: entries with a unique ID, selector, public surface classification, compatibility decision and attributed
  decision reference. `public_stable` is outside the rule regardless of exception status. `public_preview` requires an
  explicitly approved exception. `internal/approved` remains invalid; do not manufacture an exception to encode a
  callback or protocol requirement.
- Bounded local basis and policy/review references. These explain the owner's decision but are not additional model
  evidence. The loader does not open referenced documents or discover declarations elsewhere in the repository.

Exception selectors use an exact normalized path, or `path::qualified_symbol`, with no wildcards. Duplicate selectors,
overlapping ancestor/descendant symbol scopes, path-only and symbol entries for the same file, conflicting declarations
and unsupported selector forms reject the declaration atomically; do not select a winner by entry order or an implicit
specificity rule. A path-only entry records a known exception somewhere in that file, not a claim that every interface
there is exempt. Its conservative runtime treatment is described below.

The project default must be an owner decision under the governing policy, not a guess from a version number or an
assistant's interpretation of contradictory documentation. The declaration's completeness statement makes absence of an
exception meaningful within its scope; absence of an entry alone does not. This is governance authority for the session,
not proof of every interface's public/private status.

At activation, display the project scope, explicit default, exceptions, source digest, declaration revision and review
reference. Disclose that supplied action content and enumerated policy facts are sent to the provider, then require the
session's paid-data acknowledgment. The owner is selecting governing policy, not labeling example outcomes. No model or
agent action can create authority by placing an approval comment in a file. Accepting the declaration does not prove its
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

Only resolved enumerated applicability facts and supported surface facts enter model state. Declaration prose, owner
names, review references, local source paths and absolute worktree paths remain local. The evaluated evidence identity
binds the declaration hash and selected entries locally. Adding declaration prose or auxiliary files to provider
payloads would require a revised data scope, disclosure and acknowledgment; this proposal does not authorize it.

## Deterministic applicability mapping

Resolve a path under the pinned project default unless an exception might affect it. Preserve the resolution's basis:
default, identified exception, unknown or conflict. A default-derived applicable result does not populate a fabricated
`surface=internal` or `surface=public_preview`. Record actual surface classification only when the declaration supports
it. Known applicability and known surface are distinct facts.

For the initial Python symbol mapping, a `file::qualified_symbol` exception can apply only to a uniquely identified
complete declaration in the supplied before/after text. Qualified names use lexical class/function ancestry, not
underscore conventions or guessed exports. Require exact name matching and enough supplied enclosing syntax to establish
that ancestry. Partial method hunks, dynamically constructed interfaces, duplicate declarations, unsupported syntax and
an alias whose declaration cannot be uniquely attributed remain ambiguous. Do not read a file body to resolve them.
Non-Python actions touching a symbol exception remain unavailable until their mapping is implemented.

A symbol exception covers the named interface, not every nested helper or adjacent declaration. The mapper must account
for each changed interface and preserve before/after names when one is renamed or replaced. An affected exceptional
interface cannot lose its exception merely because its name changes in the proposed action. If its identity cannot be
carried across the change from supplied evidence, refuse dispatch. Source and destination governance are both checked
for moves. Supporting definitions can remain evidence without automatically becoming exception targets.

An action touching a path-only exception is unavailable with zero dispatch in this initial proposal. That narrow
conservative refusal permits an owner to record a known exception before precise symbol mapping exists, without
declaring all helpers exempt or silently assessing the exception under the project default. A symbol-scoped exception in
a touched file likewise requires enough evidence to prove whether the action intersects it; an unmatched partial hunk
cannot default to applicable merely because its selector text is absent.

Batch by effective applicability, not equal surface labels. All applicable changed interfaces may share one bounded
request, including internal and non-exempt preview interfaces. An action whose changed interfaces are all explicitly
outside this rule is host-decided not applicable. Mixed applicable/not-applicable interfaces, or any unknown or
conflicting mapping, produce unavailable with zero dispatch in the first runtime version. Do not exempt unrelated
helpers, ignore an exceptional interface or send only the convenient subset. Later per-interface questions may lift this
restriction only with explicit attribution and a reviewed evidence contract.

This requires a new runtime scope representation carrying project authority, per-interface resolution and exception
mapping. The current offline corpus still has one explicit `scope_facts` pair and treats `surface=unknown` as
unavailable. Do not reinterpret that pair or relabel unknown surfaces to implement the project default. Version and
validate the runtime representation and adapt the question/evidence boundary explicitly before wiring it; retain
existing offline semantics until a separately reviewed contract migration changes them.

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

A move requires compatible effective applicability at both the source and destination; its old interface and proposed
location must not silently acquire different policy. Deletions stay in the full identity and attribution record. A
deletion-only action is not applicable, not a model success. For a mixed action, a deleted source may supply relevant
interface history only when that text is actually present in the supplied envelope. A bodyless delete cannot invent it.

Resolve applicability for every non-delete operation and every move endpoint using the mapping above. If any applicable
operation is locally unsupported, send none of the action. The preparation layer must account for every operation and
never call a partly covered action clean. Relevant wrapper, replacement and boundary evidence comes from the supplied
action; the governance declaration cannot substitute a prose claim for that evidence.

The [offline retention/admission proposal](offline-retention-admission.md) distinguishes a structural forwarding
candidate from admitted `compatibility_retention`. Missing history, replacement evidence or attribution must prevent a
warning even when a consumer question is independently answerable. Complete removal of the old interface has a separate
evidence path; an empty AST lookup is not proof of that removal. This clarification does not implement an admission
resolver or change the active rule and reviewed diagnostic contract.

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

After a recorded feasibility go-ahead, implementation fixtures must exercise snapshot selection, immutable source bytes,
replacement/revocation, malformed declarations, copied grants, default-derived applicability, mixed surface classes with
the same applicability, exact exceptions, unrelated helpers, incomplete selector attribution, unknown/conflicting
applicability, move endpoints, path rejection, unchanged source-file edits, complete long inputs, `replace_all`,
unsupported operations and all-or-nothing preparation without credentials or a client. They must also prove that action
comments cannot alter scope and declaration prose never enters a model payload. These are planned implementation checks,
not completed tests or model-quality evidence.

The project-default proposal supersedes exact-file enumeration and uniform surface declarations. Its declaration loader,
deterministic exception mapping and runtime scope representation remain unimplemented and need verification before
runtime admission. Pinned authority still changes only by replacement/revocation. No production declaration or quality
threshold is selected here. The evaluation plan owns the completed constructed labels and pending numerical quality
choices. First measure this proposal's real-action evidence and symbol-mapping limits through a bounded offline
prototype or manual review under an approved acquisition scope; record unknown, ambiguous and refused cases. That
feasibility work may proceed before runtime implementation, but this proposal supplies no data-collection authority.
Production implementation waits for the explicit proceed/revise/stop decision. Live payload approval and native delivery
remain separate gates.
