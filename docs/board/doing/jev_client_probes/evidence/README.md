# A1 evidence

The user approved four early and 25 measurement requests on 2026-10-14. All 29 are accounted for in the
[results and limitations](2026-10-14/report.md). ZDR-required routing succeeded for all three typed question shapes. The
[execution checklist](../checklist.md) retains verification and review/merge work.

## Review verification

On 2026-10-14, the review was checked against `1ae9667d` and public OpenRouter GET endpoints, without credentials or
repository payloads. These observations refine the plan; they do not establish live Decisions routing.

- **Input limit and price.** The [ZDR catalog](https://openrouter.ai/api/v1/endpoints/zdr) lists `typesafe/jev-1.13`,
  endpoint `typesafe/jev-1.13-20260917`, `context_length=64000` and `max_prompt_tokens=32000`. Those fields describe
  different limits; the 32,000-token input ceiling remains the conservative contract. The listed input price is $0.042
  per million tokens and output price is zero. Four requests at 32,000 billed input tokens each would total $0.005376
  under that pricing; this is arithmetic, not a measured bill or guaranteed cap.
- **Schema versus prose.** The [Jev guide](https://openrouter.ai/docs/guides/community/jev) describes a 32,000-token
  input context and says cost is always returned. The
  [Decisions schema](https://openrouter.ai/docs/api/api-reference/alphadecisions/submit-a-decisions-request.md) requires
  input/output token fields within usage but makes cost optional, and includes `provider.zdr`. The client must retain
  absent cost as unknown. The schema also documents 402, 413, 524 and 529; the checklist gives them explicit
  failure/retry behavior. The top-level OpenAPI fetch returned HTTP 403; the reference's embedded schema was readable.
- **Telemetry.** `usage/measurement.py` reads completion-style token names. `usage/emit.py` leaves cost null and omits a
  local request ID. Downstream v2 and usage v1 already contain the necessary fields; strict decoding and the downstream
  version fence make a casual schema extension or bump inappropriate. The plan now preserves both schemas and the
  existing `core_llm` invocation-channel value.
- **Test and documentation ownership.** `tiktoken` belongs to the non-runtime `provider-check` group. Harness tests live
  in `tests/src/scripts/`; the existing Codex script loader has a fixed Codex path. Production transport injection does
  not require shipping fixtures. Installation ZDR ownership and the end-user authentication guide need explicit doc-sync
  tasks when implementation ships.

## Capture layout

Each authorized run will add its sanitized manifest and result record here, using a dated directory. Record the tested
commit/dirty state, endpoint/model, fixture hashes, request cap, cost assumptions, isolated-home setup and actual
attempt count. Link captures promoted to `tests/fixtures/jev/`; label documentation-derived and constructed fixtures
separately.

Keep early contract captures separate from the later latency/accounting report. Preserve failures, missing metadata and
inconclusive results. Secrets and raw private data do not belong in retained evidence. Record validation commands and
outcomes alongside the relevant implementation or measurement slice.
