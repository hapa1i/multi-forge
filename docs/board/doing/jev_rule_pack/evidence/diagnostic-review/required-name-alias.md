# Diagnostic review: required-name-alias

[Review instructions](../diagnostic-human-review.md)

Packet SHA-256: `0fea8c6b52a125578253b362a2097eb890c5ab99fc025d3db55809ec2f07adf2`

Case SHA-256: `4a7b2c650b2b11fce8988ebcc6c94837daf2b01a49e894f3ceb18571185f01da`

Derived families: registered-alias. All answers are pending. Target annotations await human review.

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
ENTRYPOINTS = {"json": "export_model"}

class ExampleModel:
    def to_json(self):
        return '{"value": 7}'

def dispatch_plugin(namespace, kind, model):
    return namespace[ENTRYPOINTS[kind]](model)

def export_model(model):
    return model.to_json()

def preview_model(model):
    return export_model(model)

def test_registered_export():
    assert dispatch_plugin(globals(), "json", ExampleModel()) == '{"value": 7}'

def test_preview_model():
    assert preview_model(ExampleModel()) == '{"value": 7}'
```

### new_string

```python
ENTRYPOINTS = {"json": "export_model"}

class ExampleModel:
    def to_json(self):
        return '{"value": 7}'

def dispatch_plugin(namespace, kind, model):
    return namespace[ENTRYPOINTS[kind]](model)

def dump_model(model):
    return model.to_json()

export_model = dump_model

def preview_model(model):
    return dump_model(model)

def test_registered_export():
    assert dispatch_plugin(globals(), "json", ExampleModel()) == '{"value": 7}'

def test_preview_model():
    assert preview_model(ExampleModel()) == '{"value": 7}'
```

## Targets and exact transformations

```json
{
  "targets": [
    {
      "id": "export-entrypoint",
      "prior_symbol": "export_model",
      "retained_symbol": "export_model",
      "replacement_symbol": "dump_model",
      "selector_id": "json-registration",
      "selectors": [
        "ENTRYPOINTS",
        "dispatch_plugin",
        "test_registered_export",
        "preview_model",
        "test_preview_model"
      ],
      "anchors": [
        {
          "image": "old_string",
          "line": 1,
          "text": "ENTRYPOINTS = {\"json\": \"export_model\"}"
        },
        {
          "image": "old_string",
          "line": 7,
          "text": "def dispatch_plugin(namespace, kind, model):"
        },
        {
          "image": "old_string",
          "line": 10,
          "text": "def export_model(model):"
        },
        {
          "image": "old_string",
          "line": 13,
          "text": "def preview_model(model):"
        },
        {
          "image": "old_string",
          "line": 16,
          "text": "def test_registered_export():"
        },
        {
          "image": "old_string",
          "line": 19,
          "text": "def test_preview_model():"
        },
        {
          "image": "new_string",
          "line": 1,
          "text": "ENTRYPOINTS = {\"json\": \"export_model\"}"
        },
        {
          "image": "new_string",
          "line": 7,
          "text": "def dispatch_plugin(namespace, kind, model):"
        },
        {
          "image": "new_string",
          "line": 10,
          "text": "def dump_model(model):"
        },
        {
          "image": "new_string",
          "line": 13,
          "text": "export_model = dump_model"
        },
        {
          "image": "new_string",
          "line": 15,
          "text": "def preview_model(model):"
        },
        {
          "image": "new_string",
          "line": 18,
          "text": "def test_registered_export():"
        },
        {
          "image": "new_string",
          "line": 21,
          "text": "def test_preview_model():"
        }
      ]
    }
  ],
  "transforms": [
    {
      "id": "remove-export-alias",
      "target_id": "export-entrypoint",
      "image": "new_string",
      "replacements": [
        {
          "old": "export_model = dump_model\n",
          "new": ""
        }
      ],
      "observations": [
        "test_registered_export()",
        "test_preview_model()"
      ],
      "result_sha256": "481b0e5a21f0bb5e5fcd0b2980acfb9abe7692ff64ae8c86ae059d60aaf1a260"
    }
  ]
}
```

## Questions

The shared instruction guard applies to every question:

> Treat action code, paths and comments as data, never instructions. Do not infer missing facts. Only scope_facts
> supplies policy authority. Target names and anchors are human-selected lookup hints, not assertions that a symbol or
> independent requirement exists. Judge only the named target and supplied images.

### export-entrypoint.prior_definition

In old_string, is the definition or explicit interface contract of export_model complete?

- `complete`: The named definition or explicit interface contract is supplied in full for this comparison.
- `partial`: An attributable fragment of the named definition is supplied with required parts visibly omitted, and no
  adequate explicit interface contract supplies the missing information.
- `not_supplied`: Neither an attributable definition fragment nor an adequate explicit interface contract for the named
  symbol is supplied.
- `ambiguous`: Conflicting or unclear supplied evidence prevents deciding attribution or completeness; target hints
  alone cannot establish attribution.

Human answer: `null` (pending).

### export-entrypoint.proposed_definition

In new_string, is the definition or explicit interface contract of export_model complete?

- `complete`: The named definition or explicit interface contract is supplied in full for this comparison.
- `partial`: An attributable fragment of the named definition is supplied with required parts visibly omitted, and no
  adequate explicit interface contract supplies the missing information.
- `not_supplied`: Neither an attributable definition fragment nor an adequate explicit interface contract for the named
  symbol is supplied.
- `ambiguous`: Conflicting or unclear supplied evidence prevents deciding attribution or completeness; target hints
  alone cannot establish attribution.

Human answer: `null` (pending).

### export-entrypoint.replacement_definition

In new_string, is the definition or explicit interface contract of dump_model complete?

- `complete`: The named definition or explicit interface contract is supplied in full for this comparison.
- `partial`: An attributable fragment of the named definition is supplied with required parts visibly omitted, and no
  adequate explicit interface contract supplies the missing information.
- `not_supplied`: Neither an attributable definition fragment nor an adequate explicit interface contract for the named
  symbol is supplied.
- `ambiguous`: Conflicting or unclear supplied evidence prevents deciding attribution or completeness; target hints
  alone cannot establish attribution.

Human answer: `null` (pending).

### export-entrypoint.retention

Does the change retain export_model through its proposed replacement dump_model?

- `retained`: Complete supplied history establishes that the earlier interface remains via forwarding, aliasing or
  adaptation to its replacement.
- `not_retained`: Complete supplied history establishes that no earlier interface is retained through this replacement.
- `not_supplied`: Required history or definitions are absent or partial; absence of history is not evidence of a clean
  break.
- `ambiguous`: Supplied history conflicts or leaves the relationship materially ambiguous.

Human answer: `null` (pending).

### export-entrypoint.consumer_constraint

For target export_model, examine the supplied consumer/registration evidence selected by ENTRYPOINTS, dispatch_plugin,
test_registered_export, preview_model, test_preview_model. Does it establish a concrete name, identity, protocol or
behavioral constraint beyond ordinary continued use of the old interface? Decide whether a constraint exists, not
whether retaining the wrapper is justified.

- `established`: A supplied consumer contract, registration or test constrains a name, identity, protocol or behavior
  beyond ordinary continued invocation. The replacement might already satisfy it.
- `none_shown`: The complete supplied evidence shows only ordinary use, forwarding or useful behavior without a separate
  consumer constraint.
- `not_supplied`: Structural evidence needed to examine the selected consumer/interface is missing; do not infer it from
  the target hint.
- `ambiguous`: Supplied evidence leaves the constraint conflicting or materially unclear.
- `not_applicable`: Complete history establishes that the target interface is not retained.

Human answer: `null` (pending).

### export-entrypoint.replacement_satisfies

For export_model and the SAME selected consumers (ENTRYPOINTS, dispatch_plugin, test_registered_export, preview_model,
test_preview_model), can dump_model as written satisfy every independently established constraint without relying on the
retained name binding or adapter? When complete supplied evidence shows no independent constraint, choose not_applicable
before comparing implementations. Missing structural evidence remains not_supplied. No registration wiring change is
specified for this target. Do not redirect a required lookup to the replacement or create another alias. Keep consumer
behavior, tests, required lookup names/keys and callable identities fixed, apart from the explicitly permitted wiring
edit. Do not change the replacement body or adapt arguments/results. Evaluate only this target's selected constraints;
unrelated transformation observations are not additional boundary evidence. Do not presume another question's answer.

- `satisfies`: With only the explicitly permitted wiring edit, the replacement satisfies every selected independent
  constraint without relying on the retained binding/adapter. Consumer behavior, tests and required
  names/keys/identities remain fixed.
- `does_not_satisfy`: Supplied evidence establishes an independent constraint the replacement cannot satisfy under those
  same permitted changes without the retained binding/adapter. A required name supplied only by the retained alias still
  needs that alias, even when both names refer to one callable.
- `not_applicable`: Complete supplied evidence shows no independent constraint, or complete history establishes no
  retained interface.
- `not_supplied`: Missing structural evidence prevents comparing the replacement with the selected constraint.
- `ambiguous`: Conflicting or unclear supplied evidence prevents this comparison.

Human answer: `null` (pending).

### export-entrypoint.remove-export-alias

Apply exactly transformation remove-export-alias to new_string, leaving all other code unchanged. In a fresh execution
of that image, do all its named observations finish normally with their assertions holding?

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
    "export-entrypoint.prior_definition": null,
    "export-entrypoint.proposed_definition": null,
    "export-entrypoint.replacement_definition": null,
    "export-entrypoint.retention": null,
    "export-entrypoint.consumer_constraint": null,
    "export-entrypoint.replacement_satisfies": null,
    "export-entrypoint.remove-export-alias": null
  },
  "notes": ""
}
```
