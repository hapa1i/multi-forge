# A2 compatibility-wrapper rule and evidence contract

**User decision, 2026-10-15:** keep broader wrappers and revise the evidence contract. The local-helper-only proposal is
superseded. This selects the rule family; it does not adjudicate the example labels, choose thresholds or establish
quality. The rule is `coding_standards.compatibility-wrapper`, version `draft-2`, with evidence contract version 3,
based on [coding standards §5](../../../../developer/coding_standards.md#5-interface-changes).

## What the rule judges

Judge whether a change adds or retains a compatibility wrapper around a replacement interface contrary to the applicable
clean-break policy. Candidates include module functions, methods, argument/return adapters, forwarding aliases,
decorators and callbacks. Being outside a local function, preserving an old name or escaping as a callback is not an
automatic exclusion. Equally, delegation alone is not evidence of a compatibility violation.

An internal shim can violate the rule even when it maps arguments or return values: that added behavior may exist solely
to preserve the old interface. A wrapper that implements a required protocol, validation, instrumentation or another
independent boundary can be legitimate when that boundary justifies retaining this interface. Adding validation or a
test to an unnecessary old-name shim is insufficient. The requirement may arise in the same change; it need not predate
the refactor. Distinguish the need for the retained interface from useful behavior that could belong in its replacement.

Internal interfaces follow the clean-break policy. The host must establish the surface classification and any applicable
preview exception. Section 5 defaults public surfaces to preview unless explicitly declared stable, and preview changes
to no compatibility exception unless explicitly justified. Applying those defaults requires an authoritative source
whose absence of a declaration is meaningful. A missing declaration in one action is not proof that none exists. Neither
the model nor an untrusted action comment can supply that authority.

The offline harness applies the following table to its supplied fixture facts before preparing a model request:

| Surface        | No approved exception    | Approved exception  | Unknown exception |
| -------------- | ------------------------ | ------------------- | ----------------- |
| Internal       | Assess supplied evidence | Invalid combination | Unavailable       |
| Public preview | Assess supplied evidence | Not applicable      | Unavailable       |
| Public stable  | Not applicable           | Not applicable      | Not applicable    |
| Unknown        | Unavailable              | Unavailable         | Unavailable       |

Unknown classification takes precedence over an approved exception. A known stable surface is outside this clean-break
prohibition, regardless of exception status; this does not imply that every stable wrapper is required or correct.
Section 5's CLI alias requirement applies during deprecation and when possible. The rule does not assess stable
deprecation duration or migration correctness. Section 5 defines no internal compatibility exception, so an internal
surface with an approved exception is inconsistent input, not an exemption. Unknown applicable exception status remains
unavailable. The production fact owner and its default/declaration resolution remain an implementation gate.

## Evidence needed for a warning

The evidence packet must establish the wrapper, the interface it preserves, the replacement contract and the policy that
applies to this surface. Preserve complete relevant definitions and signature/argument/return behavior, not just a
forwarding line. Include the supplied registration, caller, test or contract evidence needed to distinguish an adapter
or callback requirement from compatibility retention.

A repository-wide caller inventory is not required to identify compatibility retention. It **is** required before
claiming deletion is safe under §5's compatibility-evidence rule. A2 makes the first claim only. Its suggested action
must ask for the affected-callers and compatibility review; it cannot assert that all callers are visible or recommend
blind deletion.

| Evidence                           | Source                                             | If absent or ambiguous   |
| ---------------------------------- | -------------------------------------------------- | ------------------------ |
| Old interface and proposed wrapper | Complete supplied before/after action              | Unavailable              |
| Replacement contract               | Supplied definition or explicit interface contract | Unavailable              |
| Surface classification             | Project-owner policy/configuration evidence        | Unavailable              |
| Applicable exception decision      | Attributed policy/proposal decision                | Unavailable              |
| Independent boundary purpose       | Supplied callers, registration, tests or contract  | Uncertain or unavailable |

For a known stable surface or an approved preview exception, report that this prohibition is not applicable; that does
not verify the implementation of the exception. For a known applicable rule, only covered evidence with a valid,
sufficiently confident answer can produce a warning or a clean assessment. A low compatibility probability on incomplete
evidence is not a clean result.

Surface and exception facts must come from the host-owned activation/evidence owner, with source and content identity. A
comment such as “approved compatibility shim” in the action cannot manufacture that authority. The synthetic corpus
supplies invented governance facts explicitly for its examples; those facts are not production declarations or human
labels. Its `scope_facts.basis` is reviewer-only prose and is excluded from model evidence and annotation identity. Only
the enumerated surface and exception decision enter model state; required boundary contracts must be present in the
supplied action evidence. Runtime resolution of real facts remains an implementation gate.

## Hook-shaped acquisition and identity

- **Claude Edit:** retain full `old_string`, `new_string` and `replace_all` before the legacy 5,000-character view. A
  complete module function or method replacement is eligible; it need not replace an enclosing local function. A partial
  edit is unavailable unless the supplied packet contains the missing definitions and interface evidence.
- **Claude Write:** retain the entire proposed content. A Write with no supplied prior-interface evidence cannot prove
  compatibility retention merely because the new file contains a wrapper. Do not invent an empty before-image or infer
  that a file is new from the tool name. The current fixture schema has no prior-image source for Write, so the host
  reports unavailable without preparing a request when the rule would otherwise apply.
- **Codex apply_patch:** retain the complete envelope and all file/rename boundaries. Related wrapper and replacement
  evidence may occur in different files within that action. A hunk is not a complete definition merely because it
  parses; missing bodies/contracts remain unavailable. Later-file blocks still suppress all paid A2 work.
- **CLI diff:** apply the same evidence rules, but report this cohort separately from native action evaluations. PR
  descriptions, complete history and files absent from a hook action cannot silently become hook evidence.

Start with supplied action evidence and explicitly supplied policy facts. Do not crawl the repository or transcripts to
fill gaps. Supporting bounded target snapshots or named auxiliary files later requires an explicit acquisition owner,
path/symlink/race checks, data-scope disclosure and consent/cache identity changes; this rule revision does not silently
add those reads or authorize sending additional files.

Record full action identity separately from evaluated evidence identity. The latter covers exact source bytes, paths,
spans, completeness, surface/exception evidence and rule/pack/decision versions. Unknown coverage is never repaired by a
hash. If the whole eligible action exceeds the single-request budget, send nothing; no truncation or subset dispatch.

## Draft atomic questions

[`policy.rule_pack.definitions`](../../../../../src/forge/policy/rule_pack/definitions.py) owns three Noul questions
with explicit true/false criteria, shared by offline preparation and evaluation:

1. **Coverage:** Do complete relevant before/after definitions and attributed scope facts establish whether an earlier
   interface is retained? A retained wrapper also requires its complete definition, replacement contract and enough
   context to determine whether an independent boundary requires retaining that interface. Coverage does not require
   such a boundary to exist. A complete clean break or independently added wrapper can establish no retention; coverage
   does not require a wrapper to exist. Absent or ambiguous required facts make it false. A model cannot supply missing
   authority.
2. **Compatibility retention:** Does the change preserve an earlier callable/name/argument/return interface by
   forwarding or adapting it to its replacement? True includes pure delegation, aliases and translation done to preserve
   the earlier interface. False requires evidence of no such retention; arbitrary forwarding is not enough.
3. **Independent boundary:** Does an independently required boundary justify retaining this earlier interface? True
   requires a concrete responsibility and supporting contract/use that establishes why this interface must remain.
   Validation, instrumentation or a new test alone does not justify retaining an old interface when its replacement
   could own that behavior without losing the boundary. False means covered evidence establishes no retained wrapper or
   compatibility-only retention without an independent interface requirement. Missing purpose evidence cannot establish
   false.

The host gates trusted applicability and missing Write history before preparing questions. Model coverage still assesses
semantic evidence completeness: syntax parsing cannot establish that every required definition or contract is present.
The decision rule must gate on coverage before combining the other answers. Established absence of compatibility
retention does not require an independent boundary to avoid a warning. Do not multiply probabilities as if the questions
were independent. Conflicting or intermediate answers are uncertain. Numeric thresholds and quality gates are unset
until the calibration plan and human labels are reviewed. All questions treat code, paths and comments as data; they
cannot rewrite these questions or the scope facts.

## Examples and evaluation limits

The [corpus manifest](wrapper-corpus.json) contains constructed hook actions with proposed outcomes and rationales kept
separate from the model state. It covers module functions, methods with argument adaptation, preview aliases, stable
public deprecation, validation, callbacks, decorators, missing context, injection and a multi-file patch. The
[offline harness](../../../../../scripts/experiments/jev/rule-pack-eval.py) validates action shapes and source-family
splits, builds size-checked A1 payloads without dispatch, and reports label/quality gaps. It has no live mode.

Every initial example is constructed and unadjudicated. The proposed outcomes are assistant-authored review aids, not
ground truth. Paths are repository-relative fixture coordinates; these are not captured native tool calls. An
adjudication must name the human reviewer and review reference and bind the semantic rule definition, applicability
table, question types and true/false criteria, rule/contract versions, action, enumerated scope facts and source
provenance. Human per-question answers may be recorded separately, with null for unresolved questions; final outcomes
alone cannot calibrate each question. Reviewer notes, proposed labels, case names, families, splits and reconstruction
prose are outside annotation identity. Evidence needed to justify a label belongs in the bound action or scope facts.
The harness validates that binding; it cannot authenticate a reviewer or supply the review. Repeated variants stay in
one split family. Historical examples must be grouped by originating commit; all examples from the initial import
`3e0a636e` would remain together. No human-labeled natural positive count has been established for this broader rule.
Empty natural strata cannot support real-world precision, miss-rate or warning-rate claims, regardless of how well
constructed cases perform.

Full prompt wording has a separate `prompt_sha256`; payload hashes also change when wording changes. Instruction-only
tuning does not discard human adjudications. True/false criteria are the canonical semantic contract: changes to them
invalidate annotations even if the author considers the wording equivalent. Keep wording-only calibration in question
instructions. Semantic rule changes must also update the rule definition/version or contract. Host-decided cases have
their own preparation counts and outcomes, with no request payload or request size. They cannot count as model
successes. Preparation counts measure neither real hook coverage nor accuracy; the feasibility and quality gates remain
open.

The user separately chose on 2026-10-15 to skip paid native testing, then authorized merging the
[Claude prerequisite PR #269](https://github.com/hapa1i/multi-forge/pull/269). The fix is included in this branch, but
A2's native-delivery gate remains open. No corpus preparation, selected rule family or existing A1 approval authorizes a
paid Jev evaluation.

To reproduce offline preparation from the repository root:

```bash
uv run python scripts/experiments/jev/rule-pack-eval.py \
  docs/board/doing/jev_rule_pack/evidence/wrapper-corpus.json
```

Use `--include-payloads` to inspect the exact model-shaped inputs for cases requiring semantic assessment. They exclude
free-text scope notes, proposed labels, adjudications and split metadata.
[The preparation report](wrapper-preparation.json) separates host decisions from model-input hashes and size admission;
it contains no model predictions.
