# Verify and correct token totals on direct Codex resume

**Done.** Merged into `main` as `0df6abb1` on 2026-11-28. [PR #312](https://github.com/hapa1i/multi-forge/pull/312) ·
[Completed checklist](checklist.md)

Before this change, a native-auth `forge session resume <name> --task ...` forwarded the terminal JSONL counters to the
session usage event and downstream attempt. On Codex 0.172.0 the terminal included earlier turns. Across two resumes,
activity counted 167,502 input tokens for 95,341 tokens of work, including transfer curation.
[Live measurement](evidence/native-resume-usage.json) · [Codex invoker](../../../../src/forge/core/invoker/codex.py) ·
[Telemetry design](../../../design_telemetry.md)

## Evidence before implementation

- A direct Codex 0.161.0 start and resume on the same thread reported 31,522 then 63,316 input tokens. Cached input rose
  from 27,776 to 59,008 and output from 46 to 92. This supports the cumulative interpretation. The receipt lacks an
  independent rollout total for either launch. A 0.162.1 native resume also preserves a raw terminal triplet and its
  matching ledger values. [Paired direct launches](../../done/codex_0160_validation/evidence/product.json) ·
  [Native resume JSONL](../../done/codex_policy_warnings/evidence/multi.json)
- Native review forks have stronger evidence for a different operation. On Codex 0.162.1 a copied review inherited
  812,603 input tokens and finished at 974,814. Subtracting the rollout baseline matched the new requests for input,
  cached input and output. [PR #265](https://github.com/hapa1i/multi-forge/pull/265) ·
  [Fork counters](../../done/codex_fork_supervisor/evidence/usage-counters.json) ·
  [Native supervision](../../../end-user/native_supervision.md)
- The managed proxy matrix summarizes the corrected headless events as 16 input and 2 output tokens on 0.141.0 and
  0.172.0. It omits the raw terminal counters, rollout baselines and cached counts. The ordinary direct measurement
  therefore needed independent before, terminal and after values for each field.
  [Proxy matrix](../../done/codex_session_proxy_routing/evidence/managed-cli-matrix.json)

## Acceptance

- Measure one ChatGPT subscription thread across a start, a rejected resume and two successful resumes. Retain the raw
  counter triplets and their launch identities in `evidence/native-resume-usage.json`. Verify the event, attempt and
  operator-visible activity totals against that evidence.
- If the terminal counters are cumulative, subtract only when all three match a fresh rollout total attributable to the
  resumed launch. Both rollout samples must belong to the same thread, provider and counter history. Use the native fork
  reader's counter semantics and the existing delta calculation. If direct counters are demonstrably per-launch, retain
  that calculation for the verified format. Evidence from one binary or auth route cannot establish the others.
- Accounting uncertainty leaves all three token fields unknown. An otherwise admissible native resume still runs and
  keeps its ordinary outcome and thread-drift handling. Compacted direct histories stay in this category until measured.
- Document the historical reporting boundary in the telemetry design and change log when the correction ships.
  Previously recorded direct resumes can overstate activity. Their ordinary events lack the inputs needed to identify
  and repair affected rows reliably. Keep the existing schema and historical records.
