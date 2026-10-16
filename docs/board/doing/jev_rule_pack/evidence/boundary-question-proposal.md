# Boundary-question diagnosis and adopted wording

Adopted, 2026-10-17. The [first calibration capture](calibration-2026-10-16/README.md) cannot recover the two
human-labeled boundary exceptions under the current decision bands. The user approved the boundary instruction change
below, keeping coverage unchanged. Semantic criteria and human labels remain unchanged; settings remain unset. The
[next capture plan](calibration-boundary-run-plan.md) requires separate approval before dispatch.

## What the capture establishes

An offline audit reproduced the approved manifest, implementation identities, payload hashes and saved predictions. All
nine requests contained their complete corpus actions and then-current questions. Both affected requests included the
before/after definitions, consumers, registrations and tests. Responses were HTTP 200 from the expected snapshot, and
raw probabilities were preserved by question ID. No local truncation, swapped criteria or probability inversion explains
the result.

| Calibration case        | Human boundary | Boundary score | Coverage score |
| ----------------------- | -------------- | -------------- | -------------- |
| validation-boundary     | True           | 0.14           | 0.59           |
| callback-protocol       | True           | 0.16           | 0.45           |
| validation-gratuitous   | False          | 0.29           | 0.61           |
| method-argument-adapter | False          | 0.15           | 0.72           |

The human distinctions have executable support. An in-memory check of the already captured synthetic code passed the
original supplied tests and checked these substitutions:

- **Validation boundary:** substituting `decode_json` for `parse_document` makes the command test raise
  `JSONDecodeError`, which `InputCommand` does not catch. Moving the blank-input check into `decode_json` instead makes
  the inspection test raise `BlankDocument`, which `inspect_document` does not catch. The wrapper mediates two supplied
  exception contracts.
- **Callback protocol:** registering `consume_payload` directly makes the subscription test raise `AttributeError`:
  `Record` has no `strip`. `on_record` adapts the bus's `Record` contract to the replacement's string interface, also
  used directly by `process_line`.
- **Gratuitous validation:** substituting `decode_json` for `parse_document` passes both supplied tests. The replacement
  already performs the blank-input check, and inspection catches either exception through `ValueError`.

These checks verify the supplied examples, not safety of deleting a real interface. Ordinary adapters remain a necessary
negative control: a changed signature can prevent direct substitution without establishing an independent requirement to
preserve the earlier interface. In `method-argument-adapter`, the only supplied caller already uses the replacement.

## Likely ambiguity, with limits

The boundary question used in the first capture asks for a requirement for “retaining this interface” and whether its
replacement “could own” the behavior. It does not make the scope of that comparison concrete. An unrestricted
hypothetical refactor could rename an adapter, inline it or redesign its consumers; that would make almost any
particular function dispensable. The intended distinction concerns the retained interface's role under supplied consumer
contracts, not proof that its exact spelling is the only possible implementation.

The question also combines identifying the old/replacement relationship, tracing consumers, comparing signatures or
exception behavior, and assessing whether behavior can move without breaking another contract. Jev may have missed that
reasoning even if it interpreted the wording correctly. The validation scores order the negative above the positive;
this is not merely a threshold offset. Responses contain no rationale, and there is only one observation per case, so
the capture cannot distinguish wording ambiguity, code-reasoning limitations or response variability.

Callback coverage is a separate blocker: 0.45 cannot meet any allowed true cutoff. Improving its boundary score alone
would not yield `no_warning` if coverage stayed unchanged. The presence of complete inputs does not establish that the
model recognizes their completeness.

## Adopted boundary instruction

The shared data/instruction guard and the true/false criteria stay unchanged. Only the appended
[`independent_boundary.instructions`](../../../../../src/forge/policy/rule_pack/definitions.py) text changes to:

> Does the supplied evidence justify a boundary role for the retained interface, distinct from its replacement? Identify
> the retained interface, its replacement, and any supplied consumer, registration, contract or test evidence requiring
> a particular name, signature, callable identity or behavior. Compare that requirement with what the replacement
> provides. An ordinary caller still using the old name or signature does not alone establish an independent
> requirement, and direct-substitution failure alone is insufficient. Assess evidenced boundary contracts as written; do
> not redesign them to erase the requirement. A justified adapter role need not have an irreplaceable function name,
> though an explicitly required name or identity can itself establish a boundary. If the wrapper's behavior could move
> into the replacement, check whether that move preserves all supplied required consumer contracts and the replacement's
> other supplied uses. Behavior already provided by the replacement does not justify duplicating it. Apply the stated
> criteria to absent, ambiguous or conflicting justification; do not infer unseen requirements.

This makes the comparison explicit without naming fixtures or supplying their answers. It preserves the advisory
standard: absence of justification can support a warning on covered evidence, while conflicting justification remains
uncertain. It does not exempt all callbacks, validation or signature adapters.

Coverage stays unchanged so the only prompt intervention is the boundary instruction. Record coverage alongside boundary
results; a boundary-only improvement is insufficient for the combined rule. This does not by itself establish a causal
effect: the next capture compares against a historical run without a contemporaneous control.

## Unadopted coverage candidate

The following coverage clarification remains a possible later experiment and is not part of the active questions or next
manifest:

> Assess structural evidence completeness separately from whether retention is justified. For an Edit, read old_string
> as the before-image and new_string as the after-image. For apply_patch, read the supplied before/after hunks. Check
> the relevant prior interface, proposed interface, replacement definition or explicit contract, and supplied scope
> facts. A newly extracted replacement needs no before-definition. Do not require a whole-file or repository-wide caller
> inventory when the relevant evidence is supplied. Difficulty deciding the independent-boundary question is not itself
> missing interface evidence.

## Experiment and identity boundaries

An instructions-only clarification preserves human case hashes under the
[existing identity contract](initial-rule-review.md#examples-and-evaluation-limits), while changing prompt and payload
hashes. Active rule/contract/decision versions and labels can remain unchanged only while their semantics and criteria
remain unchanged. Any criteria rewrite, extra semantic question or changed boundary standard requires corresponding
versioning and human review; do not migrate labels automatically. Retain the original capture unchanged.

The [next capture plan](calibration-boundary-run-plan.md) keeps the existing nine-case runner and takes one new
observation per case, including duplicated validation and ordinary adapters. Its fresh manifest binds the exact
payloads, limits and expected snapshot. It compares with the retained first capture; it adds no contemporaneous
original-prompt control or repetitions. This narrow comparison cannot distinguish an instruction effect from run-to-run
changes or establish stability. Do not choose threshold bands merely to turn the difficult cases into abstentions.

The next observation should test whether the two positive boundary scores separate from negative controls while
preserving coverage and retention. If the clarification still fails, consider decomposing contract identification and
replacement compatibility into separately reviewed questions, or revisit model/rule fit. That would be a semantic
redesign, not another silent wording adjustment. No held-out model outputs or extra action context are needed for this
proposal. Representative evidence and practical usefulness remain separate, unresolved feasibility gates.
