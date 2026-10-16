# A2 human review: held-out

Rendered from [human-review-packet.json](human-review-packet.json), with confirmed review status added. All five cases
are reviewed. Read the [review instructions](human-review.md) and exact question criteria first. No model responses or
authored proposals appear here. Rule `draft-3` / evidence contract 4 uses the advisory standard: absent supplied
boundary justification can support a warning when interface evidence is otherwise complete. Case names may suggest
author intent; they are not labels.

Every action is constructed, with provenance `assistant-authored-wrapper-fixtures-2026-10-15`. The supplied scope facts
are invented governance for these examples, not real repository declarations. Judge only the complete action shown and
these facts; unavailable evidence must remain unknown. No additional file content or caller inventory is asserted.

## decorator-instrumentation

Family: `decorator-instrumentation`. Case SHA-256: `609cd48a1a83e6a2d0593005d02d55afbb5a4383d0adf2366f506176fb520ca6`.

Surface: `internal`; compatibility decision: `not_approved`. Runtime/tool: `claude_code` / `Edit`.

Path: `src/example.py`; `replace_all=false`.

Before:

```python
def traced(fn):
    return fn

@traced
def handle(value):
    return value + 1

def process(values):
    return [handle(value) for value in values]
```

After:

```python
events = []

def traced(fn):
    def wrapper(*args, **kwargs):
        events.append(fn.__name__)
        return fn(*args, **kwargs)
    return wrapper

@traced
def handle(value):
    return value + 1

def process(values):
    return [handle(value) for value in values]
```

Human review: **reviewed, 2026-10-16**. Outcome: `no_warning`; coverage: `true`; compatibility retention: `false`;
independent boundary: `false`. The [retained ledger](human-review-2026-10-16-batch-7.json) holds the confirmed notes and
case identity.

## write-without-history

Family: `insufficient-context`. Case SHA-256: `6278ba9ad3d9c7fb8470b330485cda5c03689540556b5dd7b77c687a1bfd7469`.

Surface: `internal`; compatibility decision: `not_approved`. Runtime/tool: `claude_code` / `Write`.

Path: `src/example.py`. Full proposed content:

```python
from backend import fetch_config

def load(path):
    return fetch_config(path)
```

Human review: **reviewed, 2026-10-16**. Outcome: `unavailable`; `question_answers: null`. This host-decided Write lacks
prior-interface evidence (`write_without_prior_interface_evidence`), so no model request is dispatched. The
[retained ledger](human-review-2026-10-16-batch-7.json) holds the confirmed explanation and case identity.

## partial-edit

Family: `insufficient-context`. Case SHA-256: `674fc6de1fbdeb72af5a51959b339ce5940fe4d3cace414c344e5c733343bb88`.

Surface: `internal`; compatibility decision: `not_approved`. Runtime/tool: `claude_code` / `Edit`.

Path: `src/example.py`; `replace_all=false`.

Before:

```python
return parse(path.read_text())
```

After:

```python
return fetch_config(path)
```

Human review: **reviewed, 2026-10-16**. Outcome: `unavailable`; coverage: `false`; compatibility retention: `null`;
independent boundary: `null`. These unknown semantic answers remain in the model candidate's answer object; this is not
a host-decided case with `question_answers: null`. The [retained ledger](human-review-2026-10-16-batch-8.json) holds the
confirmed notes and case identity.

## return-shape-adapter

Family: `return-shape-adaptation`. Case SHA-256: `d57fd194f32e397e8e8c19151fce465ee1e4ad40951e43cbbb7e55c458b37ef8`.

Surface: `internal`; compatibility decision: `not_approved`. Runtime/tool: `claude_code` / `Edit`.

Path: `src/example.py`; `replace_all=false`.

Before:

```python
def describe(values):
    return len(values), sum(values)

def render(values):
    count, total = describe(values)
    return f"{count}: {total}"
```

After:

```python
def summarize(values):
    return {"count": len(values), "total": sum(values)}

def describe(values):
    summary = summarize(values)
    return summary["count"], summary["total"]

def render(values):
    summary = summarize(values)
    return f"{summary['count']}: {summary['total']}"
```

Human review: **reviewed, 2026-10-16**. Outcome: `warning`; coverage: `true`; compatibility retention: `true`;
independent boundary: `false`. The [retained ledger](human-review-2026-10-16-batch-8.json) holds the confirmed notes and
case identity.

## return-shape-direct-update

Family: `return-shape-adaptation`. Case SHA-256: `82f0c26ca9bcd281c334fa9ec5d62ecf82a4eccb4b697e491529cbeacd0db414`.

Surface: `internal`; compatibility decision: `not_approved`. Runtime/tool: `claude_code` / `Edit`.

Path: `src/example.py`; `replace_all=false`.

Before:

```python
def describe(values):
    return len(values), sum(values)

def render(values):
    count, total = describe(values)
    return f"{count}: {total}"
```

After:

```python
def summarize(values):
    return {"count": len(values), "total": sum(values)}

def render(values):
    summary = summarize(values)
    return f"{summary['count']}: {summary['total']}"
```

Human review: **reviewed, 2026-10-16**. Outcome: `no_warning`; coverage: `true`; compatibility retention: `false`;
independent boundary: `false`. The [retained ledger](human-review-2026-10-16-batch-8.json) holds the confirmed notes and
case identity.
