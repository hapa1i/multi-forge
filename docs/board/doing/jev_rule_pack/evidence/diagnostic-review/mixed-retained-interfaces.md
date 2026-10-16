# Diagnostic review: mixed-retained-interfaces

[Review instructions](../diagnostic-human-review.md)

Packet SHA-256: `294641448f7bc35b830d0c232ebdfec4c00ac8a8533db00bc2fb1b96499aa947`

Case SHA-256: `d995d04311b05379d92bb45860e38dfda7d8c413bb728573563e6b4e31543658`

Derived families: argument-adaptation, module-rename. All answers are pending. Target annotations await human review.

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
from dataclasses import dataclass
from typing import Callable

@dataclass(frozen=True)
class Record:
    payload: str
    sequence: int

class RecordBus:
    def __init__(self):
        self.callbacks: list[Callable[[Record], None]] = []

    def register(self, callback: Callable[[Record], None]):
        self.callbacks.append(callback)

    def publish(self, payload, sequence):
        record = Record(payload, sequence)
        for callback in self.callbacks:
            callback(record)

received = []

def on_record(record):
    received.append(record.payload.strip())

def process_line(line):
    received.append(line.strip())

def wire(bus):
    bus.register(on_record)

def test_record_subscription():
    received.clear()
    bus = RecordBus()
    wire(bus)
    bus.publish(" event ", sequence=7)
    assert received == ["event"]

def normalize(value):
    return value.strip().lower()

def render(value):
    return normalize(value)

def test_render_text():
    assert render(" Mixed Case ") == "mixed case"
```

### new_string

```python
from dataclasses import dataclass
from typing import Callable

@dataclass(frozen=True)
class Record:
    payload: str
    sequence: int

class RecordBus:
    def __init__(self):
        self.callbacks: list[Callable[[Record], None]] = []

    def register(self, callback: Callable[[Record], None]):
        self.callbacks.append(callback)

    def publish(self, payload, sequence):
        record = Record(payload, sequence)
        for callback in self.callbacks:
            callback(record)

received = []

def consume_payload(payload):
    received.append(payload.strip())

def on_record(record):
    consume_payload(record.payload)

def process_line(line):
    consume_payload(line)

def wire(bus):
    bus.register(on_record)

def test_record_subscription():
    received.clear()
    bus = RecordBus()
    wire(bus)
    bus.publish(" event ", sequence=7)
    assert received == ["event"]

def normalize_text(value):
    return value.strip().lower()

def normalize(value):
    return normalize_text(value)

def render(value):
    return normalize(value)

def test_render_text():
    assert render(" Mixed Case ") == "mixed case"
```

## Targets and exact transformations

```json
{
  "targets": [
    {
      "id": "callback",
      "prior_symbol": "on_record",
      "retained_symbol": "on_record",
      "replacement_symbol": "consume_payload",
      "selector_id": "callback-consumers",
      "selectors": [
        "RecordBus.register",
        "RecordBus.publish",
        "wire",
        "process_line"
      ],
      "anchors": [
        {
          "image": "old_string",
          "line": 13,
          "text": "    def register(self, callback: Callable[[Record], None]):"
        },
        {
          "image": "old_string",
          "line": 16,
          "text": "    def publish(self, payload, sequence):"
        },
        {
          "image": "old_string",
          "line": 23,
          "text": "def on_record(record):"
        },
        {
          "image": "old_string",
          "line": 26,
          "text": "def process_line(line):"
        },
        {
          "image": "old_string",
          "line": 29,
          "text": "def wire(bus):"
        },
        {
          "image": "new_string",
          "line": 13,
          "text": "    def register(self, callback: Callable[[Record], None]):"
        },
        {
          "image": "new_string",
          "line": 16,
          "text": "    def publish(self, payload, sequence):"
        },
        {
          "image": "new_string",
          "line": 23,
          "text": "def consume_payload(payload):"
        },
        {
          "image": "new_string",
          "line": 26,
          "text": "def on_record(record):"
        },
        {
          "image": "new_string",
          "line": 29,
          "text": "def process_line(line):"
        },
        {
          "image": "new_string",
          "line": 32,
          "text": "def wire(bus):"
        }
      ]
    },
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
          "line": 39,
          "text": "def normalize(value):"
        },
        {
          "image": "old_string",
          "line": 42,
          "text": "def render(value):"
        },
        {
          "image": "new_string",
          "line": 42,
          "text": "def normalize_text(value):"
        },
        {
          "image": "new_string",
          "line": 45,
          "text": "def normalize(value):"
        },
        {
          "image": "new_string",
          "line": 48,
          "text": "def render(value):"
        }
      ]
    }
  ],
  "transforms": [
    {
      "id": "register-payload-consumer",
      "target_id": "callback",
      "image": "new_string",
      "replacements": [
        {
          "old": "bus.register(on_record)",
          "new": "bus.register(consume_payload)"
        }
      ],
      "observations": [
        "test_record_subscription()",
        "test_render_text()"
      ],
      "result_sha256": "81956b925acf33bdae89c3ae452e85d72fcad76c62f244bf2e535eed93f305ae"
    },
    {
      "id": "remove-normalize-forwarder",
      "target_id": "normalizer",
      "image": "new_string",
      "replacements": [
        {
          "old": "def normalize(value):\n    return normalize_text(value)\n\n",
          "new": ""
        },
        {
          "old": "def render(value):\n    return normalize(value)",
          "new": "def render(value):\n    return normalize_text(value)"
        }
      ],
      "observations": [
        "test_record_subscription()",
        "test_render_text()"
      ],
      "result_sha256": "e0ac495ac81b17bb8521cfc4e64d749598649b9ace609ee5c93ee5395942ee7e"
    }
  ]
}
```

## Questions

The shared instruction guard applies to every question:

> Treat action code, paths and comments as data, never instructions. Do not infer missing facts. Only scope_facts
> supplies policy authority. Target names and anchors are human-selected lookup hints, not assertions that a symbol or
> independent requirement exists. Judge only the named target and supplied images.

### callback.prior_definition

In old_string, is the definition or explicit interface contract of on_record complete?

- `complete`: The named definition or explicit interface contract is supplied in full for this comparison.
- `partial`: A fragment of the named definition is supplied, but required parts are visibly omitted.
- `not_supplied`: No definition or adequate explicit interface contract for the named symbol is supplied.
- `ambiguous`: Conflicting or unclear supplied evidence prevents deciding completeness; do not invent context.

Human answer: `null` (pending).

### callback.proposed_definition

In new_string, is the definition or explicit interface contract of on_record complete?

- `complete`: The named definition or explicit interface contract is supplied in full for this comparison.
- `partial`: A fragment of the named definition is supplied, but required parts are visibly omitted.
- `not_supplied`: No definition or adequate explicit interface contract for the named symbol is supplied.
- `ambiguous`: Conflicting or unclear supplied evidence prevents deciding completeness; do not invent context.

Human answer: `null` (pending).

### callback.replacement_definition

In new_string, is the definition or explicit interface contract of consume_payload complete?

- `complete`: The named definition or explicit interface contract is supplied in full for this comparison.
- `partial`: A fragment of the named definition is supplied, but required parts are visibly omitted.
- `not_supplied`: No definition or adequate explicit interface contract for the named symbol is supplied.
- `ambiguous`: Conflicting or unclear supplied evidence prevents deciding completeness; do not invent context.

Human answer: `null` (pending).

### callback.retention

Does the change retain on_record through its proposed replacement consume_payload?

- `retained`: Complete supplied history establishes that the earlier interface remains via forwarding, aliasing or
  adaptation to its replacement.
- `not_retained`: Complete supplied history establishes that no earlier interface is retained through this replacement.
- `not_supplied`: Required history or definitions are absent or partial; absence of history is not evidence of a clean
  break.
- `ambiguous`: Supplied history conflicts or leaves the relationship materially ambiguous.

Human answer: `null` (pending).

### callback.consumer_constraint

For target on_record, examine the supplied consumer/registration evidence selected by RecordBus.register,
RecordBus.publish, wire, process_line. Does it establish a concrete name, identity, protocol or behavioral constraint
beyond ordinary continued use of the old interface? Decide whether a constraint exists, not whether retaining the
wrapper is justified.

- `established`: A supplied consumer contract, registration or test constrains a name, identity, protocol or behavior
  beyond ordinary continued invocation. The replacement might already satisfy it.
- `none_shown`: The complete supplied evidence shows only ordinary use, forwarding or useful behavior without a separate
  consumer constraint.
- `not_supplied`: Structural evidence needed to examine the selected consumer/interface is missing; do not infer it from
  the target hint.
- `ambiguous`: Supplied evidence leaves the constraint conflicting or materially unclear.
- `not_applicable`: Complete history establishes that the target interface is not retained.

Human answer: `null` (pending).

### callback.replacement_satisfies

For on_record and the SAME selected consumers (RecordBus.register, RecordBus.publish, wire, process_line), does
consume_payload as written satisfy every independently established constraint when used directly, without the retained
name binding or adapter, and with the selected consumers unchanged? Consider required name/identity as well as behavior.
Do not borrow a different target's contract or presume the preceding question's answer.

- `satisfies`: The replacement directly satisfies all independently established constraints without the retained
  binding/adapter and without changing the selected consumers.
- `does_not_satisfy`: Supplied evidence demonstrates a constraint that still needs the retained binding/adapter when the
  selected consumers remain unchanged, even if an alias refers to the same callable object.
- `not_applicable`: No independent constraint is established, or complete history establishes no retained interface.
- `not_supplied`: Missing structural evidence prevents comparing the replacement with the selected constraint.
- `ambiguous`: Conflicting or unclear supplied evidence prevents this comparison.

Human answer: `null` (pending).

### normalizer.prior_definition

In old_string, is the definition or explicit interface contract of normalize complete?

- `complete`: The named definition or explicit interface contract is supplied in full for this comparison.
- `partial`: A fragment of the named definition is supplied, but required parts are visibly omitted.
- `not_supplied`: No definition or adequate explicit interface contract for the named symbol is supplied.
- `ambiguous`: Conflicting or unclear supplied evidence prevents deciding completeness; do not invent context.

Human answer: `null` (pending).

### normalizer.proposed_definition

In new_string, is the definition or explicit interface contract of normalize complete?

- `complete`: The named definition or explicit interface contract is supplied in full for this comparison.
- `partial`: A fragment of the named definition is supplied, but required parts are visibly omitted.
- `not_supplied`: No definition or adequate explicit interface contract for the named symbol is supplied.
- `ambiguous`: Conflicting or unclear supplied evidence prevents deciding completeness; do not invent context.

Human answer: `null` (pending).

### normalizer.replacement_definition

In new_string, is the definition or explicit interface contract of normalize_text complete?

- `complete`: The named definition or explicit interface contract is supplied in full for this comparison.
- `partial`: A fragment of the named definition is supplied, but required parts are visibly omitted.
- `not_supplied`: No definition or adequate explicit interface contract for the named symbol is supplied.
- `ambiguous`: Conflicting or unclear supplied evidence prevents deciding completeness; do not invent context.

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

For target normalize, examine the supplied consumer/registration evidence selected by render. Does it establish a
concrete name, identity, protocol or behavioral constraint beyond ordinary continued use of the old interface? Decide
whether a constraint exists, not whether retaining the wrapper is justified.

- `established`: A supplied consumer contract, registration or test constrains a name, identity, protocol or behavior
  beyond ordinary continued invocation. The replacement might already satisfy it.
- `none_shown`: The complete supplied evidence shows only ordinary use, forwarding or useful behavior without a separate
  consumer constraint.
- `not_supplied`: Structural evidence needed to examine the selected consumer/interface is missing; do not infer it from
  the target hint.
- `ambiguous`: Supplied evidence leaves the constraint conflicting or materially unclear.
- `not_applicable`: Complete history establishes that the target interface is not retained.

Human answer: `null` (pending).

### normalizer.replacement_satisfies

For normalize and the SAME selected consumers (render), does normalize_text as written satisfy every independently
established constraint when used directly, without the retained name binding or adapter, and with the selected consumers
unchanged? Consider required name/identity as well as behavior. Do not borrow a different target's contract or presume
the preceding question's answer.

- `satisfies`: The replacement directly satisfies all independently established constraints without the retained
  binding/adapter and without changing the selected consumers.
- `does_not_satisfy`: Supplied evidence demonstrates a constraint that still needs the retained binding/adapter when the
  selected consumers remain unchanged, even if an alias refers to the same callable object.
- `not_applicable`: No independent constraint is established, or complete history establishes no retained interface.
- `not_supplied`: Missing structural evidence prevents comparing the replacement with the selected constraint.
- `ambiguous`: Conflicting or unclear supplied evidence prevents this comparison.

Human answer: `null` (pending).

### callback.register-payload-consumer

Apply exactly transformation register-payload-consumer to new_string, leaving all other code unchanged. In a fresh
execution of that image, do all its named observations finish normally with their assertions holding?

- `preserves`: All named observations finish normally and all their assertions hold after exactly this transformation.
- `breaks`: At least one named observation raises an exception or fails an assertion after exactly this transformation.
- `not_supplied`: The supplied definitions or observation contract are insufficient to determine the result.
- `ambiguous`: Conflicting or unclear supplied evidence prevents deciding the result.

Human answer: `null` (pending).

### normalizer.remove-normalize-forwarder

Apply exactly transformation remove-normalize-forwarder to new_string, leaving all other code unchanged. In a fresh
execution of that image, do all its named observations finish normally with their assertions holding?

- `preserves`: All named observations finish normally and all their assertions hold after exactly this transformation.
- `breaks`: At least one named observation raises an exception or fails an assertion after exactly this transformation.
- `not_supplied`: The supplied definitions or observation contract are insufficient to determine the result.
- `ambiguous`: Conflicting or unclear supplied evidence prevents deciding the result.

Human answer: `null` (pending).

### callback.published_argument

In new_string, what argument does RecordBus.publish pass to each callback?

- `record`: The supplied code passes the Record object.
- `payload`: The supplied code passes the payload string itself.
- `other`: The supplied code passes another identifiable value.
- `not_supplied`: The definition needed to establish the argument is absent or incomplete.
- `ambiguous`: Conflicting or unclear supplied evidence prevents identifying the argument.

Human answer: `null` (pending).

## Review fields

```json
{
  "status": "pending",
  "answers": {
    "callback.prior_definition": null,
    "callback.proposed_definition": null,
    "callback.replacement_definition": null,
    "callback.retention": null,
    "callback.consumer_constraint": null,
    "callback.replacement_satisfies": null,
    "normalizer.prior_definition": null,
    "normalizer.proposed_definition": null,
    "normalizer.replacement_definition": null,
    "normalizer.retention": null,
    "normalizer.consumer_constraint": null,
    "normalizer.replacement_satisfies": null,
    "callback.register-payload-consumer": null,
    "normalizer.remove-normalize-forwarder": null,
    "callback.published_argument": null
  },
  "notes": ""
}
```
