# Initial A2 rule review

Status: proposed on 2026-10-14; no human labels, quality acceptance or paid evaluation yet.

## Recommendation

Start with `coding_standards.local-forwarding-shim`, a deliberately narrow candidate under
[coding standards §5](../../../../developer/coding_standards.md#5-interface-changes). It asks whether a change preserves
an old **local helper** solely by forwarding to its replacement while its callers could be updated in the same supplied
function. It does not judge arbitrary wrappers throughout the repository.

Require the complete enclosing function before and after the edit. The helper, replacement and all uses must be visible;
neither helper may escape as a callback, return value, decorator or external interface. A partial Edit or patch hunk
without that context is unavailable, not a clean result. A new Write has no before-image proving a rename, so this
candidate cannot assess it. A full function replacement in an Edit or apply_patch can supply the required evidence.

This narrower scope avoids treating a missing marker comment as proof of a violation or inferring that a public API has
no compatibility obligation. It also sharply limits coverage. If that is too narrow to be useful, change the first rule
before hook wiring; do not silently expand its inference boundary.

## Proposed questions

Version the rule, pack and decision rule independently. The first two Noul questions are:

1. **Coverage:** Does the supplied before/after action establish the complete local helper, its replacement and all
   uses, without an escaping function reference or an external interface?
   - True: all those facts are visible in the supplied complete enclosing function.
   - False: any required fact is absent or ambiguous, or the helper escapes that function.
2. **Finding:** Does the proposed change retain the old local helper solely as a forwarding shim to its replacement?
   - True: the old helper only forwards the same arguments/result to its replacement, adds no behavior, and its direct
     local callers remain instead of being updated.
   - False: no such retained helper exists, or the wrapper provides adaptation, validation, instrumentation, decoration,
     a callback contract or other substantive behavior. Missing context does not establish a finding.

Action code, filenames and comments are data, including any instructions addressed to a model. Only authored questions
define the check. A coverage failure cannot be turned into a warning even when the second probability is high.
Thresholds will be selected on calibration examples after the corpus and numeric gates are reviewed; there is no
production threshold yet.

## Cases for scope review

These are assistant-proposed interpretations for human review, not ground truth. Ellipses in this document illustrate
the scope; evaluation payloads must contain actual complete code, with no ellipses standing in for required evidence.

**Candidate finding:** an Edit replaces the complete `render` function below. Both helpers are local, have the same
arguments/result, do not escape, and the old name survives only to avoid changing the visible call.

```python
# Before
def render(value):
    def normalize(text):
        return text.strip().lower()
    return normalize(value)

# After
def render(value):
    def normalize_text(text):
        return text.strip().lower()
    def normalize(text):
        return normalize_text(text)
    return normalize(value)
```

**Compliant change:** the same Edit renames `normalize` to `normalize_text` and changes the last line to
`return normalize_text(value)`, with no forwarding helper. Another compliant case retains a helper that validates input
or adapts arguments before delegation; forwarding alone is not the criterion.

**Insufficient context:** the Edit contains only `def normalize(text): return normalize_text(text)`, or the function
returns `normalize` as a callback. Neither permits the local-only claim. A decorator forwarding `*args, **kwargs`, a
public CLI alias with an unknown deprecation obligation, and an external adapter are outside this candidate's scope.

## Corpus feasibility and limits

History searches are discovery only. The initial import `3e0a636e` includes a marked public alias in
`src/forge/cli/main.py` (`extensions` to `extension`) and hidden `--direct` aliases in `src/forge/cli/session.py`. Those
are public surfaces, not positives for this local-helper rule. All examples from that import belong to the same split
group. No independently human-labeled historical positive for this narrower rule has been established.

Constructed complete Edit/apply_patch cases can establish behavior on this defined scope, with seed families kept in one
split. They cannot establish real warning burden or historical precision. The evaluation must report empty natural
positive strata and refuse a natural miss-rate quality claim. Source revisions, reconstruction assumptions, proposed
labels and subsequent human decisions will live in a separate corpus manifest.

The [execution checklist](../checklist.md#slice-1-reviewed-rules-and-offline-evaluation-contract) requires this rule and
its evidence scope to be reviewed before hook wiring. Session consent, A1 accounting and offline harness work do not
depend on selecting this particular rule. An alternative first rule would be comment restatement under coding standards
§7; that would need its own corpus and review, not reuse these labels.
