# Diagnostic review: validation-boundary

[Review instructions](../diagnostic-human-review.md)

Packet SHA-256: `0fea8c6b52a125578253b362a2097eb890c5ab99fc025d3db55809ec2f07adf2`

Case SHA-256: `73d13e1b8cc184ef095d07d75cb1e4e137813af7cdb5fb385aa42608b3449f2c`

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

- `complete`: The named definition or explicit interface contract is supplied in full for this comparison.
- `partial`: An attributable fragment of the named definition is supplied with required parts visibly omitted, and no
  adequate explicit interface contract supplies the missing information.
- `not_supplied`: Neither an attributable definition fragment nor an adequate explicit interface contract for the named
  symbol is supplied.
- `ambiguous`: Conflicting or unclear supplied evidence prevents deciding attribution or completeness; target hints
  alone cannot establish attribution.

Human answer: `null` (pending).

### parser.proposed_definition

In new_string, is the definition or explicit interface contract of parse_document complete?

- `complete`: The named definition or explicit interface contract is supplied in full for this comparison.
- `partial`: An attributable fragment of the named definition is supplied with required parts visibly omitted, and no
  adequate explicit interface contract supplies the missing information.
- `not_supplied`: Neither an attributable definition fragment nor an adequate explicit interface contract for the named
  symbol is supplied.
- `ambiguous`: Conflicting or unclear supplied evidence prevents deciding attribution or completeness; target hints
  alone cannot establish attribution.

Human answer: `null` (pending).

### parser.replacement_definition

In new_string, is the definition or explicit interface contract of decode_json complete?

- `complete`: The named definition or explicit interface contract is supplied in full for this comparison.
- `partial`: An attributable fragment of the named definition is supplied with required parts visibly omitted, and no
  adequate explicit interface contract supplies the missing information.
- `not_supplied`: Neither an attributable definition fragment nor an adequate explicit interface contract for the named
  symbol is supplied.
- `ambiguous`: Conflicting or unclear supplied evidence prevents deciding attribution or completeness; target hints
  alone cannot establish attribution.

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

For target parse_document, examine the supplied consumer/registration evidence selected by InputCommand.run,
make_command, inspect_document. Does it establish a concrete name, identity, protocol or behavioral constraint beyond
ordinary continued use of the old interface? Decide whether a constraint exists, not whether retaining the wrapper is
justified.

- `established`: A supplied consumer contract, registration or test constrains a name, identity, protocol or behavior
  beyond ordinary continued invocation. The replacement might already satisfy it.
- `none_shown`: The complete supplied evidence shows only ordinary use, forwarding or useful behavior without a separate
  consumer constraint.
- `not_supplied`: Structural evidence needed to examine the selected consumer/interface is missing; do not infer it from
  the target hint.
- `ambiguous`: Supplied evidence leaves the constraint conflicting or materially unclear.
- `not_applicable`: Complete history establishes that the target interface is not retained.

Human answer: `null` (pending).

### parser.replacement_satisfies

For parse_document and the SAME selected consumers (InputCommand.run, make_command, inspect_document), can decode_json
as written satisfy every independently established constraint without relying on the retained name binding or adapter?
When complete supplied evidence shows no independent constraint, choose not_applicable before comparing implementations.
Missing structural evidence remains not_supplied. Permit only the callable-argument substitution in transformation
register-replacement's replacements. That exact wiring edit is allowed even inside a selected registration helper. An
unused retained definition may remain, but it cannot supply the replacement's behavior. Keep consumer behavior, tests,
required lookup names/keys and callable identities fixed, apart from the explicitly permitted wiring edit. Do not change
the replacement body or adapt arguments/results. Evaluate only this target's selected constraints; unrelated
transformation observations are not additional boundary evidence. Do not presume another question's answer.

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
