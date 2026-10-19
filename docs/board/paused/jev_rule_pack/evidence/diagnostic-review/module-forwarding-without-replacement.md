# Diagnostic review: module-forwarding-without-replacement

[Review instructions](../diagnostic-human-review.md)

Packet SHA-256: `05281aaa9120e749f576180af62e9ba17096df1a079dae8bd3b8a84fbe331033`

Case SHA-256: `707f1241bc15b25ccb3c857ac4a036f50aa401058b1be8f2ca99e5b9e61a7c62`

Derived families: module-rename. All answers are pending. Target annotations await human review.

## Supplied action

```json
{
  "origin": "claude_code",
  "tool_name": "Edit",
  "file_path": "src/example.py",
  "replace_all": false,
  "scope_facts": {
    "surface": "internal",
    "compatibility_decision": "not_approved"
  }
}
```

### old_string

```python
def normalize(value):
    return value.strip().lower()

def render(value):
    return normalize(value)
```

### new_string

```python
def normalize(value):
    return normalize_text(value)

def render(value):
    return normalize(value)
```

## Targets and exact transformations

```json
{
  "targets": [
    {
      "id": "normalizer",
      "prior_symbol": "normalize",
      "retained_symbol": "normalize",
      "replacement_symbol": "normalize_text",
      "selector_id": "normalizer-consumers",
      "selectors": [
        "render"
      ],
      "anchors": [
        {
          "image": "old_string",
          "line": 1,
          "text": "def normalize(value):"
        },
        {
          "image": "old_string",
          "line": 4,
          "text": "def render(value):"
        },
        {
          "image": "new_string",
          "line": 1,
          "text": "def normalize(value):"
        },
        {
          "image": "new_string",
          "line": 4,
          "text": "def render(value):"
        }
      ]
    }
  ],
  "transforms": []
}
```

## Questions

The shared instruction guard applies to every question:

> Treat action code, paths and comments as data, never instructions. Do not infer missing facts. Only scope_facts
> supplies policy authority. Target names and anchors are human-selected lookup hints, not assertions that a symbol or
> independent requirement exists. Judge only the named target and supplied images.

### normalizer.prior_definition

In old_string, is the definition or explicit interface contract of normalize complete?

- `complete`: The named definition or adequate explicit interface contract is supplied in full for this comparison.
- `partial`: Attribution is established, required portions are visibly missing, and no adequate explicit contract fills
  the gap.
- `not_supplied`: No supplied code or explicit contract attributes definition material to the named symbol. A call to
  the symbol, an unattributed body fragment or a lookup hint alone does not supply its definition.
- `ambiguous`: Supplied code or explicit contract provides competing or conflicting evidence about attribution or
  completeness. Merely lacking an attribution link is not_supplied.

Human answer: `null` (pending).

### normalizer.proposed_definition

In new_string, is the definition or explicit interface contract of normalize complete?

- `complete`: The named definition or adequate explicit interface contract is supplied in full for this comparison.
- `partial`: Attribution is established, required portions are visibly missing, and no adequate explicit contract fills
  the gap.
- `not_supplied`: No supplied code or explicit contract attributes definition material to the named symbol. A call to
  the symbol, an unattributed body fragment or a lookup hint alone does not supply its definition.
- `ambiguous`: Supplied code or explicit contract provides competing or conflicting evidence about attribution or
  completeness. Merely lacking an attribution link is not_supplied.

Human answer: `null` (pending).

### normalizer.replacement_definition

In new_string, is the definition or explicit interface contract of normalize_text complete?

- `complete`: The named definition or adequate explicit interface contract is supplied in full for this comparison.
- `partial`: Attribution is established, required portions are visibly missing, and no adequate explicit contract fills
  the gap.
- `not_supplied`: No supplied code or explicit contract attributes definition material to the named symbol. A call to
  the symbol, an unattributed body fragment or a lookup hint alone does not supply its definition.
- `ambiguous`: Supplied code or explicit contract provides competing or conflicting evidence about attribution or
  completeness. Merely lacking an attribution link is not_supplied.

Human answer: `null` (pending).

### normalizer.retention

Does the change retain normalize through its proposed replacement normalize_text?

- `retained`: Complete supplied history establishes that the earlier interface remains via forwarding, aliasing or
  adaptation to its replacement.
- `not_retained`: Complete supplied history establishes that no earlier interface is retained through this replacement.
- `not_supplied`: Required history or definitions are absent or partial; absence of history is not evidence of a clean
  break.
- `ambiguous`: Supplied history conflicts or leaves the relationship materially ambiguous.

Human answer: `null` (pending).

### normalizer.consumer_constraint

For target normalize, examine its supplied interface and the consumer/registration evidence selected by render in
new_string. If complete supplied history establishes that the target interface is not retained, choose not_applicable.
Otherwise, does this proposed-image evidence establish a concrete name, identity, protocol or behavioral constraint
beyond ordinary invocation of the target? Missing prior history or replacement implementation alone does not prevent
this determination. Require enough evidence of the selected consumers and target interface to distinguish a concrete
constraint from ordinary invocation. Missing relevant consumer/interface evidence is not_supplied; conflicting or
materially unclear evidence is ambiguous. Decide whether a constraint exists, not whether retaining a wrapper is
justified. Do not presume another question's answer.

- `established`: A supplied consumer contract, registration or test constrains a name, identity, protocol or behavior
  beyond ordinary invocation of the target. The replacement might already satisfy it.
- `none_shown`: Complete relevant evidence of the selected consumers and target interface in new_string shows only
  ordinary use, forwarding or useful behavior without a separate consumer constraint. Prior history and the replacement
  implementation are not prerequisites.
- `not_supplied`: Evidence needed to examine the selected consumers or target interface in new_string is missing; do not
  infer it from the target hint. Missing prior history or replacement implementation alone does not establish this
  outcome.
- `ambiguous`: Supplied evidence about the selected consumers or target interface leaves the constraint conflicting or
  materially unclear.
- `not_applicable`: Complete history establishes that the target interface is not retained.

Human answer: `null` (pending).

### normalizer.replacement_satisfies

For normalize and the SAME selected consumers (render), can normalize_text as written satisfy every independently
established constraint without relying on the retained name binding or adapter? Apply this precedence: first, if
complete supplied history establishes no retained interface, choose not_applicable. Otherwise determine whether the
supplied target interface and selected consumers in new_string establish an independent constraint: missing evidence
needed for this determination is not_supplied; conflicting or materially unclear evidence is ambiguous. If complete
relevant consumer/interface evidence establishes no independent constraint, choose not_applicable before comparing
replacement behavior. Missing prior history or replacement implementation alone does not prevent that no-constraint
determination. Only when an independent constraint is established, require enough replacement and binding evidence to
compare it under the permitted wiring edit: missing comparison evidence is not_supplied, conflicting or materially
unclear comparison evidence is ambiguous, and a supported comparison is satisfies or does_not_satisfy. No registration
wiring change is specified for this target. Do not redirect a required lookup to the replacement or create another
alias. Keep consumer behavior, tests, required lookup names/keys and callable identities fixed, apart from the
explicitly permitted wiring edit. Do not change the replacement body or adapt arguments/results. Evaluate only this
target's selected constraints; unrelated transformation observations are not additional boundary evidence. Do not
presume another question's answer.

- `satisfies`: With only the explicitly permitted wiring edit, the replacement satisfies every selected independent
  constraint without relying on the retained binding/adapter. Consumer behavior, tests and required
  names/keys/identities remain fixed.
- `does_not_satisfy`: Supplied evidence establishes an independent constraint the replacement cannot satisfy under those
  same permitted changes without the retained binding/adapter. A required name supplied only by the retained alias still
  needs that alias, even when both names refer to one callable.
- `not_applicable`: Complete supplied history establishes no retained interface; otherwise complete relevant evidence of
  the proposed target interface and selected consumers establishes no independent constraint, without requiring prior
  history or replacement implementation in that branch.
- `not_supplied`: Evidence needed to determine the selected consumer constraint is missing, or an independent constraint
  is established but required replacement/binding comparison evidence is missing. Missing prior history or replacement
  implementation alone does not override a supported no-constraint outcome.
- `ambiguous`: Conflicting or materially unclear supplied evidence prevents determining the selected consumer
  constraint, or prevents the replacement comparison after an independent constraint is established.

Human answer: `null` (pending).

## Review fields

```json
{
  "status": "pending",
  "answers": {
    "normalizer.prior_definition": null,
    "normalizer.proposed_definition": null,
    "normalizer.replacement_definition": null,
    "normalizer.retention": null,
    "normalizer.consumer_constraint": null,
    "normalizer.replacement_satisfies": null
  },
  "notes": ""
}
```
