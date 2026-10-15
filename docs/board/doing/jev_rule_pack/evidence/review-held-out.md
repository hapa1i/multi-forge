# A2 human review: held-out

Rendered from [human-review-packet.json](human-review-packet.json). These 5 cases remain pending. Read the
[review instructions](human-review.md) and exact question criteria first. No model responses or proposed labels appear
here. Case names may suggest author intent; they are retained for identity, not treated as labels.

Every action is constructed, with provenance `assistant-authored-wrapper-fixtures-2026-10-15`. The supplied scope facts
are invented governance for these examples, not real repository declarations. Judge only the complete action shown and
these facts; unavailable evidence must remain unknown. No additional file content or caller inventory is asserted.

## decorator-instrumentation

Family: `decorator-instrumentation`. Case SHA-256: `d9f60ab21a0f003d0c899344cf16cc25266d65fd252954f3e54b1639d0bd1bcd`.

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

Human review: **pending**. Record outcome, coverage, compatibility retention, independent boundary and notes in the
matching packet row.

## write-without-history

Family: `insufficient-context`. Case SHA-256: `4dfc9172a08b90db2f59da266828280970a02fe381fd7e515219ddb84912317b`.

Surface: `internal`; compatibility decision: `not_approved`. Runtime/tool: `claude_code` / `Write`.

Path: `src/example.py`. Full proposed content:

```python
from backend import fetch_config

def load(path):
    return fetch_config(path)
```

Human review: **pending**. Record outcome, coverage, compatibility retention, independent boundary and notes in the
matching packet row.

## partial-edit

Family: `insufficient-context`. Case SHA-256: `d8b46e7d92c06473fb6446f0d06cb2870d9c0635460492c6255bb30be84057d8`.

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

Human review: **pending**. Record outcome, coverage, compatibility retention, independent boundary and notes in the
matching packet row.

## return-shape-adapter

Family: `return-shape-adaptation`. Case SHA-256: `b429b81e0ef621ff9700b9ace8d35e00bbec71e487b077f983a5e7c275f7a616`.

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

Human review: **pending**. Record outcome, coverage, compatibility retention, independent boundary and notes in the
matching packet row.

## return-shape-direct-update

Family: `return-shape-adaptation`. Case SHA-256: `c1b5621f9815d06e38d3727fd4c53b2711bfe7a8c3b39f450052fc9269b7eb3c`.

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

Human review: **pending**. Record outcome, coverage, compatibility retention, independent boundary and notes in the
matching packet row.
