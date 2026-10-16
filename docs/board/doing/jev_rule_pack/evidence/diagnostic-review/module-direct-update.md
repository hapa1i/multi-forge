# Diagnostic review: module-direct-update

[Review instructions](../diagnostic-human-review.md)

Packet SHA-256: `294641448f7bc35b830d0c232ebdfec4c00ac8a8533db00bc2fb1b96499aa947`

Case SHA-256: `325b07446db35ec5544f74596582b824b9b3f1a5bbfabdea8a64eb9c64ab1927`

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
def normalize_text(value):
    return value.strip().lower()

def render(value):
    return normalize_text(value)
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
          "text": "def normalize_text(value):"
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

## Review fields

```json
{
  "status": "pending",
  "answers": {
    "normalizer.prior_definition": null,
    "normalizer.proposed_definition": null,
    "normalizer.replacement_definition": null,
    "normalizer.retention": null
  },
  "notes": ""
}
```
