# A2 feasibility progress

2026-10-16 continuation from PR #272 (`64317485`). The 17 constructed human judgments and rule contract are unchanged.
This checkpoint records preparation and an acquisition shortfall; it does not establish runtime feasibility.

## Approved local inventory

The user approved the [local study scope](feasibility-study-plan.md) before collection. The corrected metadata inventory
found 88 matching session-index rows. The fixed recency cap considered 24 and left 64 untouched. Five active-registry
entries were excluded; the other 19 candidates were eligible, all Claude. The newest three consumed the Claude source
slots. No Codex source was eligible within the cap.

Independent review caught an initial exclusion of supported version-1 manifests. The correction required unchanged index
and active-index hashes before rereading the same candidate cohort. It raised eligible metadata rows from nine to 19;
both the original and corrected ledgers are retained. No native content was read during either pass.

All three corrected selected confirmed native paths were missing. The study did not search for replacements, expand its
date window or inspect older candidates. It read zero native transcript bytes and collected zero actions. The metadata
and source-admission ledgers remain in a private local directory with no source identities or payloads committed here.
`rule-pack-inventory.py` implements only this metadata and source-admission stage; a native action extractor was not
built without an admitted source.

Consequently, action coverage, governance, exception mapping and practical usefulness are **unmeasured**. A zero-action
sample supplies no denominator and cannot pass or fail those gates. The next real-evidence step needs a revised,
concrete acquisition scope, such as another bounded metadata cohort or explicitly selected available native sources.
Missing sources do not authorize a broader scan. The proposed numerical gates remain unratified.

## Constructed baseline comparison

The [retained baseline report](constructed-baselines.json) binds the same case/payload identities and input admission as
Jev. Across the 13 model candidates, existing compatibility-marker patterns flag none. The bounded AST detector flags
eight cases, finds no recognized retention shape in three, and reports two unsupported cases: a partial Edit and a
multi-file patch. Both preserve the other four host decisions.

The AST candidates include the required callback and validation boundaries as well as retained shims. These are
structural signals, not semantic warnings, and their absence does not prove compliance. Parameters, imports and other
supplied bindings that make target identity ambiguous remain unavailable. No caller inventories or file reads extend the
supplied action. Baseline supported syntax and source digests are recorded before any held-out model output.

## Synthetic capture boundary

The user separately approved the [calibration plan](calibration-run-plan.md), and its nine constructed requests
completed on the expected Jev 1.13 snapshot with ZDR required, no retries and isolated telemetry. The
[capture result](calibration-2026-10-16/README.md) records $0.000461370 reported cost and a 523.75 ms median latency.

The semantic calibration decision is **revise**: neither legitimate-boundary case can produce its human `no_warning`
outcome under any allowed threshold bands. Boundary-positive scores are 0.14 and 0.16, below every allowed true cutoff.
Threshold settings remain unset; no held-out manifest is prepared. Revisit the question/model fit before another
separately approved capture. Constructed observations cannot replace the missing representative evidence or justify
runtime implementation.

## Verification

The combined rule-pack, A1 probe, evaluation/review, capture, baseline, inventory and regression selection passed 345
tests. These tests use synthetic metadata and injected transports. The retained manifest and baseline report reproduce
from the current source. All nine live response contracts, model/accounting guards and telemetry request-ID joins pass;
numerical quality gates and runtime admission remain open.
