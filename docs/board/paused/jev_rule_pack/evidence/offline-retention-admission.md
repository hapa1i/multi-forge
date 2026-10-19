# Bounded offline retention and admission review

2026-10-18. This pass uses only the existing 12 diagnostic actions and 17 constructed corpus cases. It clarifies a
prospective contract and compares current host capabilities; it does not change the active rule, diagnostic draft 3,
human labels, thresholds or the [completed capture](bounded-diagnostic-2026-10-18/README.md). Both captured arms still
fail their frozen screen. No judgment requests, native acquisition or runtime implementation are part of this pass. The
validation exception below records an unintended document token-count request.

## Retention and the evidence needed to judge it

Keep `compatibility_retention` as the policy claim that an earlier interface remains through its replacement. A
**structural retention candidate** is the weaker observation that an earlier interface remains as a forwarder, alias or
adapter to a named target in the supplied change. The candidate does not establish that the target actually replaces the
earlier implementation, that its behavior is compatible, or that keeping the interface is unnecessary.

The proposed separation is:

| Layer                  | Evidence or decision                                                      | Consequence                 |
| ---------------------- | ------------------------------------------------------------------------- | --------------------------- |
| Structural observation | Attributed earlier/proposed interface and visible relation                | Candidate only              |
| Evidence admission     | Applicable authority, complete relevant history, definitions and bindings | Permit or refuse assessment |
| Semantic judgment      | Replacement relationship and supplied consumer requirements               | Covered rule assessment     |

For the structural observation alone, the named target's body need not be present. A call or target hint cannot supply
the earlier interface's missing definition or history. Absence of a recognized shape means only that the detector found
no candidate; it does not establish a clean break. An alias's binding counts as its definition, without requiring a
function body for the alias itself.

For a retained-interface assessment, admission still requires the complete relevant earlier and proposed interface
definitions, a replacement definition or adequate explicit interface contract, enough binding evidence to identify the
relationship, and applicable host-owned governance. Source attribution and supported action boundaries must be known.
Missing evidence remains unavailable even if a model confidently identifies forwarding or says no consumer constraint is
shown. A model answer cannot supply a missing definition or governance authority.

The complete-clean-break branch is separate: complete attributed before/after evidence can establish that the old
interface is removed within the supplied change. It does not require a proposed definition of the removed interface. An
empty definition lookup, an unrecognized AST shape or a missing before-image does not establish that branch.

This preserves the active rule's [coverage requirement](../../../../../src/forge/policy/rule_pack/definitions.py) and
its broader wrapper scope. It proposes separating observations from admission, not narrowing the rule to local helpers
or permitting warnings on partial snippets. A future diagnostic revision must name the exact prerequisites of each
question and receive review before its answers are used; draft-3 answers are not migrated or rescored here.

## Why the captured failures differ

Jev twice selected `partial` for the complete proposed `parse_document` definition. The frozen criterion requires
visibly missing portions, and the action contains the guard, return and replacement definition. That supports the
declared sentinel stop. Its first answer also placed a blank-input guard in `decode_json`, which has none. There is no
captured rationale that establishes why either mistake occurred.

Opus consistently recognized that `normalize_text` has no supplied definition, while answering that `normalize` is
retained. The
[frozen retention question](diagnostic-review/module-forwarding-without-replacement.md#normalizerretention) requires
complete history and "required" definitions without enumerating the replacement prerequisite. The human review intended
that prerequisite; a structural reading instead identifies the visible forwarding relationship. The disagreement is a
failure against the reviewed contract, but does not isolate a reasoning failure from that implicit dependency. Reviewer
notes explaining the dependency were not provider input.

Under the proposed separation, this action has a structural candidate and insufficient replacement evidence, so it
cannot reach a warning. That is a prospective interpretation, not a replacement human label or a successful replay of
the paid study. Opus's agreement on the other 94 question identities supports further examination of decomposition; it
does not establish automatic target selection, warning usefulness or a working outcome combiner.

## Admission decision table

These are proposed precedence rules, not a runtime implementation or new human adjudications. Apply them to every
affected operation under the runtime proposal's whole-action coverage rule; one covered target cannot excuse an
unsupported operation or an unaccounted target.

The runtime proposal also refuses mixed applicable/exempt operations with zero dispatch. Do not remove exempt operations
and judge the remainder; retain its
[mixed-applicability rule](runtime-evidence-contract.md#deterministic-applicability-mapping).

| Supplied state                                            | Required disposition        | Example                                         |
| --------------------------------------------------------- | --------------------------- | ----------------------------------------------- |
| Known exemption                                           | `not_applicable`            | Stable surface or approved preview exception    |
| Unknown authority, attribution or supported shape         | `unavailable`               | Unknown surface; unsupported patch              |
| Missing earlier-interface evidence                        | `unavailable`               | History-less Write or missing-history control   |
| Unattributed or incomplete relevant definition            | `unavailable`               | Bare return fragment                            |
| Retained candidate; missing replacement evidence          | `unavailable`               | Missing-replacement control                     |
| Complete evidence establishes removal                     | Covered no-retention branch | Direct update                                   |
| Complete history establishes independently added wrapper  | Covered no-retention branch | No replaced earlier interface                   |
| Admitted retention; missing relevant consumer evidence    | `unavailable`               | Cannot distinguish ordinary use from constraint |
| Admitted retention; conflicting boundary evidence         | `uncertain`                 | Contradictory requirement evidence              |
| Admitted retention; no independent justification shown    | Warning candidate           | Ordinary caller left on the old name            |
| Admitted retention; independent justification established | `no_warning`                | Required name or protocol boundary              |

The unavailable rows take precedence over every possible model answer. The warning row additionally requires an
established replacement relationship and an accepted semantic decision contract; the structural detector alone cannot
select it. "No justification shown" requires sufficient supplied interface/consumer evidence to examine the claim, not a
repository-wide proof that no unseen consumer exists.

Use the existing applicability table, including rejection of unsupported internal approval claims. Keep every
definition, binding and consumer requirement attached to the same target: one complete target cannot admit another's
missing replacement, and one justified boundary cannot excuse a different wrapper. Complete syntax with an unresolved
replacement relationship remains unassessed: missing required evidence is unavailable, while a genuinely inconclusive
semantic comparison of admitted evidence is uncertain. Distinct, coherent consumer contracts may justify an adapter;
they are not contradictory evidence merely because a single replacement cannot satisfy them directly. This table does
not adopt a new action-level outcome combiner.

`consumer_constraint=established` plus `replacement_satisfies=does_not_satisfy` is not by itself a complete boundary
decision. Direct substitution might fail while moving behavior into the replacement preserves all supplied contracts.
The existing validation and callback transformations examine that distinction. Their fixed, reviewed transformations are
diagnostic aids, not a demonstrated automatic transformation generator. Conversely, `not_applicable` on the
replacement-comparison question means there is no comparison to perform; it cannot override missing structural evidence.

## Existing AST capability

The [offline report](offline-retention-admission.json) records both cohorts separately, with exact input/source
identities, current host decisions, raw baseline results and target-specific syntax spans. The cohorts overlap and must
not be added together as 29 independent observations. Human-selected target hints are lookup keys; a definition is
reported only when it is found in the supplied syntax.

| Capability                             | Current baseline                       | Limit                                             |
| -------------------------------------- | -------------------------------------- | ------------------------------------------------- |
| Python definition/binding inventory    | Supplied parseable Edit images         | Syntax presence is not semantic completeness      |
| Forwarding, aliases, selected adapters | Bounded recognized shapes              | Candidate, not compatibility or necessity         |
| Missing replacement refusal            | Implemented for recognized shapes      | Not a complete coverage checker                   |
| Clean-break recognition                | No candidate on supplied direct update | Pattern absence is not a negative verdict         |
| Consumer boundary judgment             | None                                   | Legitimate and gratuitous adapters both flagged   |
| Complete action/exception mapping      | None                                   | Human targets and fixture authority remain inputs |
| Patch and partial-snippet support      | Unsupported                            | No supplemental file reads                        |

The current detector already couples candidate enumeration to replacement availability. It returns
`replacement_definition_missing` for the missing-replacement control, rather than exposing the weaker forwarding
observation as a candidate. This pass records that behavior unchanged; the proposed layer separation is not implemented
by relabeling its output. Successful `ast.parse` also does not prove arbitrary evidence complete: a syntactically valid
stub, selected fragment, unresolved binding or prose contract requires separate treatment.

The diagnostic comparison finds eight actions with candidates, one with no recognized candidate and three unavailable.
The unavailable controls are missing history, missing replacement and the unattributed fragment. The constructed
comparison preserves four host decisions; among its 13 model candidates, eight have AST candidates, three have no
recognized shape and two are unsupported. The existing marker patterns flag none of those 13 candidates.

Both required and gratuitous validation boundaries are AST candidates. Callback cases also enumerate `process_line`,
outside the diagnostic's human-selected `on_record` target. That is an additional structural candidate, not a measured
false positive. Target-selection completeness and precision have no human labels in this study.

## Feasibility disposition and hard stop

**Revise the proposed responsibility split; keep runtime work and further capture stopped.** Host checks can establish
some explicit facts and reject these missing-evidence controls. This does not repair Jev's earlier boundary judgments or
prove a general host evidence-admission algorithm. The proposed admission table still needs implementation proof after
feasibility review; this report is not that proof.

Opus exceeded five seconds on 21 of 36 requests, before accounting for a production hook's full preparation path. Its
configuration therefore supplies no basis to replace Jev inside A2's proposed five-second stage. An asynchronous review
surface would be a separate product decision, not an implicit fallback.

The next evidence must address the
[unmeasured native coverage and usefulness](feasibility-progress.md#approved-local-inventory): an availability-checked,
bounded acquisition scope, explicit acceptance gates and human usefulness review. No source collection is authorized
here. Before another model capture, record whether the candidate selector covers enough real actions, whether their
supplied evidence can satisfy admission, and what semantic value remains beyond deterministic checks. If those gates
fail, narrow or stop the rule through an explicit scope decision. This offline pass does not open another prompt-tuning
cycle or authorize use of the completed study's unused slots.

## Reproduction

From the repository root, using already-installed development dependencies:

```bash
uv run python scripts/experiments/jev/rule-pack-offline.py \
  --review docs/board/paused/jev_rule_pack/evidence/diagnostic-review-2026-10-18-batch-6.json \
  --corpus docs/board/paused/jev_rule_pack/evidence/wrapper-corpus.json
```

The command emits JSON only and has no provider, credential, native collection or runtime mode. Compare stdout with the
retained report; rerunning it does not write to the reviewed inputs or historical capture.

## Verification

The focused judgment, rule-pack, experiment and regression selection passed 802 tests; the new offline comparison suite
passed another 17. The report reproduces byte-for-byte, and the active rule, draft-3 diagnostic, completed human ledger,
corpus, approved manifest and captured results are unchanged from `641773e7`. The 720-source link audit, file-size
checks and repository-wide pre-commit passed; EOF ran separately on changed files because the broad hook opens
sandbox-protected skill paths in write mode. Mypy initially found a missing union annotation in the new script; the
corrected full check passed.

The prior PR's CI failures also exposed replay guards that mishandled the published capture's manifest reference. Both
guards now verify bounded, local, hash-matching references. The 26 new regressions cover unrelated calibration scans,
consumed diagnostic proposals after local-claim loss and malformed references; they are included in the 802 tests.
Historical execution artifacts remain frozen rather than being regenerated to match the corrected runner's source hash.

### Validation exception

The repository size checker sent the edited A2 checklist to Anthropic's free token-count endpoint after it crossed the
12,000-token local screen, before failing for missing cached evidence. This was outside the intended offline scope; no
paid inference ran. The old foundation execution notes were then moved intact into a linked archive, bringing the
checklist below its local screen. Subsequent checks redirect Anthropic fallback to loopback with dummy credentials and
use local counts or existing authoritative cache entries. No cache refresh is authorized by this pass.
