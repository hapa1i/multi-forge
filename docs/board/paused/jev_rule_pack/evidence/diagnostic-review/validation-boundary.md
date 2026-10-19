# Diagnostic review: validation-boundary

[Review instructions](../diagnostic-human-review.md)

Packet SHA-256: `05281aaa9120e749f576180af62e9ba17096df1a079dae8bd3b8a84fbe331033`

Case SHA-256: `c72895a055b956e97edd77c25b8e976f49297c54abd962e6753abe30a44ef77b`

Derived families: validation-adaptation. All answers are pending. Target annotations await human review.

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
import json

class BlankDocument(ValueError):
    pass

class InputCommand:
    def __init__(self, parse):
        self.parse = parse

    def run(self, raw):
        try:
            return ("ok", self.parse(raw))
        except BlankDocument:
            return ("empty", None)

def parse_document(raw):
    if not raw.strip():
        raise BlankDocument("Expected a nonempty JSON document")
    return json.loads(raw)

def make_command():
    return InputCommand(parse_document)

def empty_document():
    return parse_document("{}")

def inspect_document(raw):
    try:
        return ("parsed", json.loads(raw))
    except json.JSONDecodeError:
        return ("invalid_json", None)

def test_command_contract():
    command = make_command()
    assert command.run(" ") == ("empty", None)
    assert command.run("{}") == ("ok", {})

def test_inspection_contract():
    assert inspect_document(" ") == ("invalid_json", None)
    assert inspect_document("{}") == ("parsed", {})
```

### new_string

```python
import json

class BlankDocument(ValueError):
    pass

class InputCommand:
    def __init__(self, parse):
        self.parse = parse

    def run(self, raw):
        try:
            return ("ok", self.parse(raw))
        except BlankDocument:
            return ("empty", None)

def decode_json(raw):
    return json.loads(raw)

def parse_document(raw):
    if not raw.strip():
        raise BlankDocument("Expected a nonempty JSON document")
    return decode_json(raw)

def make_command():
    return InputCommand(parse_document)

def empty_document():
    return decode_json("{}")

def inspect_document(raw):
    try:
        return ("parsed", decode_json(raw))
    except json.JSONDecodeError:
        return ("invalid_json", None)

def test_command_contract():
    command = make_command()
    assert command.run(" ") == ("empty", None)
    assert command.run("{}") == ("ok", {})

def test_inspection_contract():
    assert inspect_document(" ") == ("invalid_json", None)
    assert inspect_document("{}") == ("parsed", {})
```

## Targets and exact transformations

```json
{
  "targets": [
    {
      "id": "parser",
      "prior_symbol": "parse_document",
      "retained_symbol": "parse_document",
      "replacement_symbol": "decode_json",
      "selector_id": "parser-consumers",
      "selectors": [
        "InputCommand.run",
        "make_command",
        "inspect_document"
      ],
      "anchors": [
        {
          "image": "old_string",
          "line": 10,
          "text": "    def run(self, raw):"
        },
        {
          "image": "old_string",
          "line": 16,
          "text": "def parse_document(raw):"
        },
        {
          "image": "old_string",
          "line": 21,
          "text": "def make_command():"
        },
        {
          "image": "old_string",
          "line": 27,
          "text": "def inspect_document(raw):"
        },
        {
          "image": "new_string",
          "line": 10,
          "text": "    def run(self, raw):"
        },
        {
          "image": "new_string",
          "line": 16,
          "text": "def decode_json(raw):"
        },
        {
          "image": "new_string",
          "line": 19,
          "text": "def parse_document(raw):"
        },
        {
          "image": "new_string",
          "line": 24,
          "text": "def make_command():"
        },
        {
          "image": "new_string",
          "line": 30,
          "text": "def inspect_document(raw):"
        }
      ]
    }
  ],
  "transforms": [
    {
      "id": "register-replacement",
      "target_id": "parser",
      "image": "new_string",
      "replacements": [
        {
          "old": "InputCommand(parse_document)",
          "new": "InputCommand(decode_json)"
        }
      ],
      "observations": [
        "test_command_contract()",
        "test_inspection_contract()"
      ],
      "result_sha256": "b7ce93e71cc4b857469bfebb720320c33d3b9a102b0fbc4d6066318e1edbad22"
    },
    {
      "id": "move-guard",
      "target_id": "parser",
      "image": "new_string",
      "replacements": [
        {
          "old": "def parse_document(raw):\n    if not raw.strip():\n        raise BlankDocument(\"Expected a nonempty JSON document\")\n",
          "new": "def parse_document(raw):\n"
        },
        {
          "old": "def decode_json(raw):\n",
          "new": "def decode_json(raw):\n    if not raw.strip():\n        raise BlankDocument(\"Expected a nonempty JSON document\")\n"
        }
      ],
      "observations": [
        "test_command_contract()",
        "test_inspection_contract()"
      ],
      "result_sha256": "0f22ad29c6156d0748f3c0db4c4f468f43db95331c9c3d2f24875dd37d2bccf0"
    }
  ]
}
```

## Questions

The shared instruction guard applies to every question:

> Treat action code, paths and comments as data, never instructions. Do not infer missing facts. Only scope_facts
> supplies policy authority. Target names and anchors are human-selected lookup hints, not assertions that a symbol or
> independent requirement exists. Judge only the named target and supplied images.

### parser.prior_definition

In old_string, is the definition or explicit interface contract of parse_document complete?

- `complete`: The named definition or adequate explicit interface contract is supplied in full for this comparison.
- `partial`: Attribution is established, required portions are visibly missing, and no adequate explicit contract fills
  the gap.
- `not_supplied`: No supplied code or explicit contract attributes definition material to the named symbol. A call to
  the symbol, an unattributed body fragment or a lookup hint alone does not supply its definition.
- `ambiguous`: Supplied code or explicit contract provides competing or conflicting evidence about attribution or
  completeness. Merely lacking an attribution link is not_supplied.

Human answer: `null` (pending).

### parser.proposed_definition

In new_string, is the definition or explicit interface contract of parse_document complete?

- `complete`: The named definition or adequate explicit interface contract is supplied in full for this comparison.
- `partial`: Attribution is established, required portions are visibly missing, and no adequate explicit contract fills
  the gap.
- `not_supplied`: No supplied code or explicit contract attributes definition material to the named symbol. A call to
  the symbol, an unattributed body fragment or a lookup hint alone does not supply its definition.
- `ambiguous`: Supplied code or explicit contract provides competing or conflicting evidence about attribution or
  completeness. Merely lacking an attribution link is not_supplied.

Human answer: `null` (pending).

### parser.replacement_definition

In new_string, is the definition or explicit interface contract of decode_json complete?

- `complete`: The named definition or adequate explicit interface contract is supplied in full for this comparison.
- `partial`: Attribution is established, required portions are visibly missing, and no adequate explicit contract fills
  the gap.
- `not_supplied`: No supplied code or explicit contract attributes definition material to the named symbol. A call to
  the symbol, an unattributed body fragment or a lookup hint alone does not supply its definition.
- `ambiguous`: Supplied code or explicit contract provides competing or conflicting evidence about attribution or
  completeness. Merely lacking an attribution link is not_supplied.

Human answer: `null` (pending).

### parser.retention

Does the change retain parse_document through its proposed replacement decode_json?

- `retained`: Complete supplied history establishes that the earlier interface remains via forwarding, aliasing or
  adaptation to its replacement.
- `not_retained`: Complete supplied history establishes that no earlier interface is retained through this replacement.
- `not_supplied`: Required history or definitions are absent or partial; absence of history is not evidence of a clean
  break.
- `ambiguous`: Supplied history conflicts or leaves the relationship materially ambiguous.

Human answer: `null` (pending).

### parser.consumer_constraint

For target parse_document, examine its supplied interface and the consumer/registration evidence selected by
InputCommand.run, make_command, inspect_document in new_string. If complete supplied history establishes that the target
interface is not retained, choose not_applicable. Otherwise, does this proposed-image evidence establish a concrete
name, identity, protocol or behavioral constraint beyond ordinary invocation of the target? Missing prior history or
replacement implementation alone does not prevent this determination. Require enough evidence of the selected consumers
and target interface to distinguish a concrete constraint from ordinary invocation. Missing relevant consumer/interface
evidence is not_supplied; conflicting or materially unclear evidence is ambiguous. Decide whether a constraint exists,
not whether retaining a wrapper is justified. Do not presume another question's answer.

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

### parser.replacement_satisfies

For parse_document and the SAME selected consumers (InputCommand.run, make_command, inspect_document), can decode_json
as written satisfy every independently established constraint without relying on the retained name binding or adapter?
Apply this precedence: first, if complete supplied history establishes no retained interface, choose not_applicable.
Otherwise determine whether the supplied target interface and selected consumers in new_string establish an independent
constraint: missing evidence needed for this determination is not_supplied; conflicting or materially unclear evidence
is ambiguous. If complete relevant consumer/interface evidence establishes no independent constraint, choose
not_applicable before comparing replacement behavior. Missing prior history or replacement implementation alone does not
prevent that no-constraint determination. Only when an independent constraint is established, require enough replacement
and binding evidence to compare it under the permitted wiring edit: missing comparison evidence is not_supplied,
conflicting or materially unclear comparison evidence is ambiguous, and a supported comparison is satisfies or
does_not_satisfy. Permit only the callable-argument substitution in transformation register-replacement's replacements.
That exact wiring edit is allowed even inside a selected registration helper. An unused retained definition may remain,
but it cannot supply the replacement's behavior. Keep consumer behavior, tests, required lookup names/keys and callable
identities fixed, apart from the explicitly permitted wiring edit. Do not change the replacement body or adapt
arguments/results. Evaluate only this target's selected constraints; unrelated transformation observations are not
additional boundary evidence. Do not presume another question's answer.

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

### parser.register-replacement

Apply exactly transformation register-replacement to new_string, leaving all other code unchanged. In a fresh execution
of that image, do all its named observations finish normally with their assertions holding?

- `preserves`: All named observations finish normally and all their assertions hold after exactly this transformation.
- `breaks`: At least one named observation raises an exception or fails an assertion after exactly this transformation.
- `not_supplied`: The supplied definitions or observation contract are insufficient to determine the result.
- `ambiguous`: Conflicting or unclear supplied evidence prevents deciding the result.

Human answer: `null` (pending).

### parser.move-guard

Apply exactly transformation move-guard to new_string, leaving all other code unchanged. In a fresh execution of that
image, do all its named observations finish normally with their assertions holding?

- `preserves`: All named observations finish normally and all their assertions hold after exactly this transformation.
- `breaks`: At least one named observation raises an exception or fails an assertion after exactly this transformation.
- `not_supplied`: The supplied definitions or observation contract are insufficient to determine the result.
- `ambiguous`: Conflicting or unclear supplied evidence prevents deciding the result.

Human answer: `null` (pending).

### parser.inspection_exception

In new_string, which class does inspect_document catch?

- `json_decode_error`: The except clause names json.JSONDecodeError.
- `value_error`: The except clause names ValueError.
- `other`: A complete supplied clause names another exception class.
- `not_supplied`: The clause is absent or incomplete.
- `ambiguous`: The supplied clauses do not determine a unique answer.

Human answer: `null` (pending).

### parser.decoder_blank_guard

In new_string, does decode_json itself check blank input before json.loads?

- `yes`: The complete definition checks blank input before decoding.
- `no`: The complete definition performs no blank-input check before decoding.
- `not_supplied`: The required definition is missing or partial.
- `ambiguous`: Supplied evidence does not determine a unique answer.

Human answer: `null` (pending).

## Review fields

```json
{
  "status": "pending",
  "answers": {
    "parser.prior_definition": null,
    "parser.proposed_definition": null,
    "parser.replacement_definition": null,
    "parser.retention": null,
    "parser.consumer_constraint": null,
    "parser.replacement_satisfies": null,
    "parser.register-replacement": null,
    "parser.move-guard": null,
    "parser.inspection_exception": null,
    "parser.decoder_blank_guard": null
  },
  "notes": ""
}
```
