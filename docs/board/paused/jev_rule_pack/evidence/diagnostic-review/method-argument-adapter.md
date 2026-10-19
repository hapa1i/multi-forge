# Diagnostic review: method-argument-adapter

[Review instructions](../diagnostic-human-review.md)

Packet SHA-256: `05281aaa9120e749f576180af62e9ba17096df1a079dae8bd3b8a84fbe331033`

Case SHA-256: `5824e6427eff4adfae208ba6be29e4ae8125a290930532d332d9f47e3426101e`

Derived families: argument-adaptation. All answers are pending. Target annotations await human review.

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
class Store:
    def load(self, path, strict=False):
        text = path.read_text()
        if strict and not text.strip():
            raise ValueError("Empty configuration")
        return text.strip()

def restore(store, path):
    return store.load(path, strict=True)
```

### new_string

```python
class Store:
    def load_config(self, path, mode):
        text = path.read_text()
        if mode == "strict" and not text.strip():
            raise ValueError("Empty configuration")
        return text.strip()

    def load(self, path, strict=False):
        return self.load_config(path, mode="strict" if strict else "permissive")

def restore(store, path):
    return store.load_config(path, mode="strict")
```

## Targets and exact transformations

```json
{
  "targets": [
    {
      "id": "loader",
      "prior_symbol": "Store.load",
      "retained_symbol": "Store.load",
      "replacement_symbol": "Store.load_config",
      "selector_id": "loader-consumers",
      "selectors": [
        "restore"
      ],
      "anchors": [
        {
          "image": "old_string",
          "line": 2,
          "text": "    def load(self, path, strict=False):"
        },
        {
          "image": "old_string",
          "line": 8,
          "text": "def restore(store, path):"
        },
        {
          "image": "new_string",
          "line": 2,
          "text": "    def load_config(self, path, mode):"
        },
        {
          "image": "new_string",
          "line": 8,
          "text": "    def load(self, path, strict=False):"
        },
        {
          "image": "new_string",
          "line": 11,
          "text": "def restore(store, path):"
        }
      ]
    }
  ],
  "transforms": [
    {
      "id": "old-call-shape",
      "target_id": "loader",
      "image": "new_string",
      "replacements": [
        {
          "old": "    def load(self, path, strict=False):\n        return self.load_config(path, mode=\"strict\" if strict else \"permissive\")",
          "new": "    load = load_config"
        }
      ],
      "observations": [
        "assert Store().load(type(\"Path\", (), {\"read_text\": lambda self: \"value\"})(), strict=True) == \"value\""
      ],
      "result_sha256": "053b05891429c38d4abf7e752ad4696c0ceb5ed4adcc116b204c454a20d2746c"
    }
  ]
}
```

## Questions

The shared instruction guard applies to every question:

> Treat action code, paths and comments as data, never instructions. Do not infer missing facts. Only scope_facts
> supplies policy authority. Target names and anchors are human-selected lookup hints, not assertions that a symbol or
> independent requirement exists. Judge only the named target and supplied images.

### loader.prior_definition

In old_string, is the definition or explicit interface contract of Store.load complete?

- `complete`: The named definition or adequate explicit interface contract is supplied in full for this comparison.
- `partial`: Attribution is established, required portions are visibly missing, and no adequate explicit contract fills
  the gap.
- `not_supplied`: No supplied code or explicit contract attributes definition material to the named symbol. A call to
  the symbol, an unattributed body fragment or a lookup hint alone does not supply its definition.
- `ambiguous`: Supplied code or explicit contract provides competing or conflicting evidence about attribution or
  completeness. Merely lacking an attribution link is not_supplied.

Human answer: `null` (pending).

### loader.proposed_definition

In new_string, is the definition or explicit interface contract of Store.load complete?

- `complete`: The named definition or adequate explicit interface contract is supplied in full for this comparison.
- `partial`: Attribution is established, required portions are visibly missing, and no adequate explicit contract fills
  the gap.
- `not_supplied`: No supplied code or explicit contract attributes definition material to the named symbol. A call to
  the symbol, an unattributed body fragment or a lookup hint alone does not supply its definition.
- `ambiguous`: Supplied code or explicit contract provides competing or conflicting evidence about attribution or
  completeness. Merely lacking an attribution link is not_supplied.

Human answer: `null` (pending).

### loader.replacement_definition

In new_string, is the definition or explicit interface contract of Store.load_config complete?

- `complete`: The named definition or adequate explicit interface contract is supplied in full for this comparison.
- `partial`: Attribution is established, required portions are visibly missing, and no adequate explicit contract fills
  the gap.
- `not_supplied`: No supplied code or explicit contract attributes definition material to the named symbol. A call to
  the symbol, an unattributed body fragment or a lookup hint alone does not supply its definition.
- `ambiguous`: Supplied code or explicit contract provides competing or conflicting evidence about attribution or
  completeness. Merely lacking an attribution link is not_supplied.

Human answer: `null` (pending).

### loader.retention

Does the change retain Store.load through its proposed replacement Store.load_config?

- `retained`: Complete supplied history establishes that the earlier interface remains via forwarding, aliasing or
  adaptation to its replacement.
- `not_retained`: Complete supplied history establishes that no earlier interface is retained through this replacement.
- `not_supplied`: Required history or definitions are absent or partial; absence of history is not evidence of a clean
  break.
- `ambiguous`: Supplied history conflicts or leaves the relationship materially ambiguous.

Human answer: `null` (pending).

### loader.consumer_constraint

For target Store.load, examine its supplied interface and the consumer/registration evidence selected by restore in
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

### loader.replacement_satisfies

For Store.load and the SAME selected consumers (restore), can Store.load_config as written satisfy every independently
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

### loader.old-call-shape

Apply exactly transformation old-call-shape to new_string, leaving all other code unchanged. In a fresh execution of
that image, do all its named observations finish normally with their assertions holding? This is a diagnostic invocation
of the historical strict keyword shape, with a diagnostic path returning the fixed string value. It is not a current
consumer requirement and cannot justify retaining an adapter.

- `preserves`: All named observations finish normally and all their assertions hold after exactly this transformation.
- `breaks`: At least one named observation raises an exception or fails an assertion after exactly this transformation.
- `not_supplied`: The supplied definitions or observation contract are insufficient to determine the result.
- `ambiguous`: Conflicting or unclear supplied evidence prevents deciding the result.

Human answer: `null` (pending).

## Review fields

```json
{
  "status": "pending",
  "answers": {
    "loader.prior_definition": null,
    "loader.proposed_definition": null,
    "loader.replacement_definition": null,
    "loader.retention": null,
    "loader.consumer_constraint": null,
    "loader.replacement_satisfies": null,
    "loader.old-call-shape": null
  },
  "notes": ""
}
```
