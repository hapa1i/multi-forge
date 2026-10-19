# A1: Jev client and probes execution checklist

## Current focus

A1 is **done** after [PR #268](https://github.com/hapa1i/multi-forge/pull/268) merged as `9778007a` on 2026-10-14.
Execution used `codex/jev-client-probes`, based on `main` at `1ae9667d` (`v1.1.0`). The
[Jev epic closeout](../../retired/epic_jev_support/checklist.md) records the subsequent cancellation and retirement of
the epic and A2/A3 on 2026-10-19. A1 remains done.

The user approved four early synthetic requests and then 25 measurement requests; all 29 physical requests are accounted
for in the [evidence report](evidence/2026-10-14/report.md). ZDR-required Choice/Noul/Score routing succeeded. Live
captures corrected score-rounding tolerance and the provider's HTTP 400 size-error wrapper. A2/A3, Direct TypeSafe, its
SDK and Jev Router remain outside A1. No consumer work remains active under the retired epic.

## Verified starting points

- [x] Inspect the completion boundary, credential owner, ZDR helper, measurement/emission code and strict telemetry
  readers at `1ae9667d`. No Jev implementation exists in `src/forge`, `tests` or `scripts`.
- [x] Recheck the official guide, Decisions schema and public ZDR catalog on 2026-10-14. The
  [review verification](evidence/README.md#review-verification) records the distinctions and source links; no inference
  or live routing result is implied.

| Existing owner                                                                                                                              | A1 responsibility                            |
| ------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------- |
| [`core.llm.protocols`](../../../../src/forge/core/llm/protocols.py)                                                                         | Separate typed judgment capability           |
| [`CredentialManager`](../../../../src/forge/core/llm/credentials.py)                                                                        | Existing auth chain and attribution headers  |
| [`openrouter_policy`](../../../../src/forge/core/llm/openrouter_policy.py)                                                                  | Authoritative ZDR invariant                  |
| [`usage.correlation`](../../../../src/forge/core/usage/correlation.py)                                                                      | Opt-in hashed provider grouping              |
| [`usage.measurement`](../../../../src/forge/core/usage/measurement.py) / [`usage.emit`](../../../../src/forge/core/usage/emit.py)           | Decisions token, cost and request-ID mapping |
| [`telemetry.downstream`](../../../../src/forge/core/telemetry/downstream.py) / [`usage.ledger`](../../../../src/forge/core/usage/ledger.py) | Existing schemas and per-attempt attribution |
| [OpenRouter experiments](../../../../scripts/experiments/openrouter/README.md)                                                              | Capture and redaction conventions            |

`CredentialManager.get_credentials("openrouter")` returns a default base ending in `/api/v1`; Decisions uses
`/api/alpha/decisions`. Resolve that difference explicitly without silently discarding custom routing.

The current ZDR helper accepts completion hyperparameters. Preserve its invariant without making typed judgments depend
on completion text or `ModelHyperparameters`. Only supported attribution fields may be sent; transport alone does not
prove provider recognition.

`emit_direct_llm_usage` is not a drop-in emitter: it expects `prompt_tokens`/`completion_tokens`, leaves cost null,
omits the downstream `request_id`, and needs ambient run identity. Decisions reports `input_tokens`/`output_tokens`.
Trace show/explain require a usable local request ID. Correct all three mappings through the existing telemetry owners.

Downstream readers admit only schema v2 and strictly decode fields and typed values; usage readers are strict too.
Bumping downstream to v3 would hide existing v2 history. Emitting new fields or closed-vocabulary values would make
older readers reject new records. A1 will use the existing downstream v2 and usage v1 schemas without new fields or
literals.

## Slice 1: minimal transport and early capture

- [x] Settle the small typed interface and ownership. Proposed home: `src/forge/core/judgments/`, with an async `httpx`
  adapter and mirrored unit tests. Keep test payloads and fake transports in `tests/fixtures/jev/` or the harness;
  callers inject an `httpx` transport. Do not add a vendor SDK or a completion adapter.
- [x] Record the dated wire contract and provisional documentation-derived fixtures for Choice, Noul and Score. Include
  complete Noul true/false criteria, required/optional response fields, distributions, identity and usage. Keep consumer
  thresholds outside the adapter and preserve requested versus resolved model identity.
- [x] Implement the minimum dispatch path: existing credential chain, canonical/custom URL validation, attribution
  headers, option merging followed by authoritative `provider.zdr: true`, one attempt, hard timeout and resource
  cleanup. Test no-`.env` resolution, environment/file precedence, `auth_ignore_env`, missing-key diagnostics, wrong
  bases and caller `zdr: false` without network calls. Pin an explicit model, not a moving `latest` alias.
- [x] Create the minimal `scripts/experiments/jev/` harness with a README and zero-network fixture/dry-run default.
  Reuse that dispatch path. Apply the run controls below before any live request; retain bounded sanitized responses
  even if the provisional answer parser rejects them. A synthetic-only malformed-wire control may bypass local question
  validation, but never auth, ZDR, timeout, redaction or the request cap.
- [x] Prepare the early run manifest: one small synthetic request per question type plus one malformed request, at most
  four physical requests, retries disabled. Record exact payloads/hashes, selected model, per-request timeout, current
  price assumptions, estimated total cost and isolated `FORGE_HOME`. Size-boundary probes belong to slice 4.
- [x] Obtain explicit authorization for the prepared manifest, then capture the four cases or stop early on failed
  auth/routing or a run-control breach. Retain returned model/provider, IDs, tokens, cost and error shapes. A failed
  typed success or unavailable ZDR route is a failed/inconclusive gate, not permission to weaken retention.
- [x] Promote sanitized real responses into regression fixtures, keeping their capture provenance distinct from
  documentation examples and constructed malformed cases. Reconcile schema disagreements before finalizing validation
  and accounting. Small captures establish observed shapes, not exhaustive correctness, latency or tokenizer accuracy.

**Early evidence gate:** passed after the approved four-request capture and offline replay. All three typed shapes
succeeded with ZDR required. The capture wrapper's decompression defect was fixed without repeating the first request;
its original local failure remains in evidence. Later measurement corrections and remaining limitations are recorded in
the [report](evidence/2026-10-14/report.md).

## Slice 2: validation, size admission and bounded retries

- [x] Validate supported question types, unique/nonempty IDs, Choice labels, complete Noul criteria and ordered Score
  criteria. Validate exact answer coverage and type correspondence; reject invalid labels/legends, malformed counts,
  non-finite/out-of-range probabilities and missing required fields. Record numeric tolerances; do not invent or
  silently renormalize distributions. Preserve absent optional metadata as unknown.
- [x] Define typed failures with status and sanitized diagnostics: local validation, auth/permission, insufficient
  credit, unsupported route, payload too large, rate limit, provider overload, ambiguous timeout, transport and invalid
  response. A documented 404 alone does not prove a ZDR refusal; retain provider details without guessing the cause.
- [x] Enforce an input admission policy over serialized state, all questions and criteria, with reserved headroom below
  the 32,000-token prompt ceiling. `tiktoken` is only in the `provider-check` dependency group, and no verified Jev
  tokenizer is available. Start with a documented conservative serialized UTF-8 byte cap; do not claim that byte count
  proves the exact provider token count or silently add a runtime tokenizer dependency.
- [x] Use early counts to check assumptions, then calibrate any less restrictive ratio on slice 4's varied request
  shapes, including non-English text, code and many criteria. Keep the limit provisional until that evidence exists;
  provider 413 remains an explicit failure even below the local estimate. Never truncate, split or omit evidence
  silently, and never retry the same oversized payload.
- [x] Accept a caller-owned absolute monotonic deadline. Bound credential work, I/O and backoff by remaining time;
  propagate cancellation and close resources. Zero remaining time means zero dispatches. A3 reserves reviewer time
  before invoking this client; retries never reset the deadline.
- [x] Implement the status policy below with a physical-attempt limit and bounded backoff. Every attempt still requires
  ZDR. Preserve independently valid usage and IDs on failed/invalid-answer responses; a retry must not erase potentially
  billed evidence. Unknown statuses default to a visible failure without automatic retry.

| Status / failure                  | Automatic retry policy                                   |
| --------------------------------- | -------------------------------------------------------- |
| 400 / 401 / 402 / 403 / 404 / 413 | None for the unchanged request                           |
| 429 / 500 / 502 / 503 / 529       | Bounded transient retry; shared deadline and request cap |
| 524 / post-dispatch read timeout  | None by default; possibly billed outcome unknown         |
| Cancellation / invalid answer     | None                                                     |

Honor valid `Retry-After` within the same deadline; do not wait or dispatch beyond it. A retryable status does not prove
the preceding attempt was free. Keep local pre-dispatch rejection separate from a provider-reported error.

`JudgmentError.attempts` is empty for an initial local rejection. Each attempted transport call has its own record;
`status_code` identifies an observed HTTP response, and its absence does not prove that nothing was billed. Unexpected
attempt failures become `internal_error`, never successful telemetry or an automatic retry. These existing fields
distinguish local refusal, attempted I/O and provider response without a second dispatch flag.

## Slice 3: compatible usage and operator visibility

- [x] Implement a small Decisions-specific emission adapter through existing telemetry owners. Explicitly map
  `input_tokens`/`output_tokens` and valid reported cost; preserve existing completion callers. Keep downstream schema
  v2 and usage schema v1, including their existing field sets and literals. No parallel ledger or history migration.
- [x] Mint a nonempty local `request_id` and distinct `downstream_event_id` per physical attempt; group logical retries
  through run identity. Record requested/resolved model, selected provider and returned provider IDs separately. Supply
  the existing source/backend attribution needed by cost readers; do not invent a proxy or session.
- [x] Use existing `reporter="openrouter"`, `request_mode="non_streaming"` and `confidence="reported"` when cost is
  present, otherwise `confidence="unavailable"`. Populate cost and provider-trace cost fields consistently; convert to
  established monetary units with tested rounding. Explicit zero and absent cost differ; model confidence is separate.
- [x] Use the existing usage `route="core_llm"` for the direct Forge HTTP invocation channel. Identify Jev through
  existing command/model/provider fields, not a new route literal. Document that compatibility choice without making the
  typed client implement `LLMClient`; verify baseline readers accept emitted records.
- [x] Establish standalone probe run identity through existing ownership. Check with and without a managed session; keep
  attempts, logical runs and future reviewer escalations distinguishable. Duplicate writes for an attempt count once,
  while retries remain separate. Preserve previously stored v2 cost/trace records alongside new Jev records.
- [x] Exercise trace list/show/explain, cost by-model/by-verb and activity in an isolated `FORGE_HOME`. Assert token
  mapping, request-ID lookup, null/known costs and retry counts. Existing proxy metrics must not gain fake Jev traffic;
  document which surfaces apply without a session. Run focused integration tests during this slice and sync telemetry
  design as the accounting change lands.

## Probe run controls

These controls apply to the early capture and later measurement runs. No paid run is authorized by this checklist.

- [x] Require an explicit live flag and an authorized fixed manifest: endpoint/model, fixture hashes, request shapes,
  repetition counts, deadlines, retry policy, maximum physical requests and dated pricing assumptions. Count all retries
  and control probes; reject dynamic unbounded fan-out.
- [x] Use a static per-run cost estimate and a hard physical-request counter, not per-attempt cost reservations. For
  ordinary single-question requests, `N * 32,000 * input_price` is a conservative planning estimate under the catalog's
  input/output pricing assumptions. Validate those assumptions first; give multi-question and over-limit controls
  separate estimates rather than treating 32,000 as a proven maximum billed input for every shape.
- [x] Stop on reported cost above the manifest's per-request allowance, unexpected billed usage/model identity or
  changed pricing assumptions. Retain missing cost as unknown. A post-response check cannot undo a charge, and a static
  estimate is not a guaranteed invoice cap; do not advertise it as one.
- [x] Use an isolated `FORGE_HOME` for all live attempts and copy no existing telemetry or sessions into it. Resolve
  credentials read-only through the existing owner; provide only the required secret to the isolated process, never the
  full credentials file. Verify no real-home telemetry/configuration mutation.
- [x] Retain sanitized evidence under this card's `evidence/`: manifests, capture records, provenance, results and
  verification. Link promoted test fixtures back to the capture. Keep secrets/raw private data out of both locations;
  use synthetic state first. Repository examples require a separate explicit data decision.

## Slice 4: size, latency and accounting measurements

- [x] Expand the harness and obtain authorization for the full manifest after the early gate. Reuse the production
  adapter and verify final telemetry emission alongside capture records. Ordinary tests remain offline.
- [x] Run the matrix below, recording explicit unsupported/inconclusive results. A deliberately over-limit wire probe
  needs its own payload size and cost estimate; do not weaken the production admission guard to run it.
- [x] Report end-to-end p50/p95 by shape with sample counts and percentile method, plus failures, timeouts and retry
  overhead. Compare reported usage for one versus many questions over the same state without assuming linear billing.
  These measurements are not an SLA or evidence of decision quality.
- [x] Finalize size-admission assumptions and document their empirical limits. Retain route/model/provider identity,
  available IDs/usage/cost and the public catalog date. Transported attribution is not recognized attribution, and
  catalog membership or a successful ZDR request does not prove internal retention practices.

| Probe                          | Control                                                            | Evidence                                    |
| ------------------------------ | ------------------------------------------------------------------ | ------------------------------------------- |
| Typed success / schema failure | Slice 1 captures                                                   | Reconciled response fixtures                |
| ZDR routing / refusal          | Valid request; reproducible refusal if available                   | Actual result; fixture-only refusal labeled |
| Input size / estimator         | Small, medium, near-budget, diverse text; separate over-limit case | Local decisions; provider counts / 413      |
| Shared-state accounting        | Fixed state; one versus multiple questions                         | Reported usage / cost by shape              |
| Retry / rate limit             | Deterministic failures; naturally observed live errors             | Attempt counts and timing                   |
| Latency                        | Declared shapes and repetitions                                    | Samples, percentiles, failures              |

## Acceptance tests

`core/judgments` owns the implemented boundary. Transport fakes and payloads stay outside production code. Put harness
tests in `tests/src/scripts/test_jev_probe.py`, following the script-loading pattern in `tests/fixtures/codex_probe.py`;
that existing loader is hard-coded to Codex scripts, so it is not directly reusable.

| Test                   | Fixture                                                                 | Assertion                                                         | Test file                                                                                        |
| ---------------------- | ----------------------------------------------------------------------- | ----------------------------------------------------------------- | ------------------------------------------------------------------------------------------------ |
| Typed boundary         | Captured and constructed Choice/Noul/Score                              | Preserved values; exact IDs/types                                 | `tests/src/core/judgments/test_types.py`                                                         |
| Invalid answers        | Bad IDs/labels/legends/counts/probabilities                             | No judgment; valid usage retained                                 | `tests/src/core/judgments/test_openrouter.py`                                                    |
| Input admission        | State plus criteria; varied encodings                                   | Whole-input byte screen                                           | `tests/src/core/judgments/test_budget.py`                                                        |
| Size refusal           | Attribution exceeds cap; provider 413                                   | Zero local-reject dispatches; no 413 retry                        | `tests/src/core/judgments/test_openrouter.py`                                                    |
| Auth / URL / ZDR       | Env/file/ignored-env; custom bases; false ZDR                           | Existing precedence; valid route; ZDR every attempt               | `tests/src/core/judgments/test_openrouter.py`                                                    |
| Deadline / statuses    | 400/401/402/403/404/413; 429/500/502/503/524/529; cancellation          | Status policy; exact attempts; one deadline                       | `tests/src/core/judgments/test_openrouter.py`                                                    |
| Usage / trace identity | Decisions token names; zero/null cost; retry                            | Correct tokens/cost; nonempty local IDs                           | `tests/src/core/judgments/test_usage.py`                                                         |
| History compatibility  | Existing v2 plus Jev records; baseline strict readers                   | Old history retained; new records accepted; no double count       | `tests/src/core/judgments/test_usage.py`; existing `tests/src/core/telemetry/test_downstream.py` |
| Operator visibility    | Isolated home/run; trace opt-in on/off                                  | Lookup by request ID; matching trace/cost/activity                | `tests/integration/core/judgments/test_observability.py`                                         |
| Probe controls         | Dry-run with keys; cap exhausted; unexpected cost; secret-bearing error | Zero default calls; bounded live calls; redacted isolated capture | `tests/src/scripts/test_jev_probe.py`                                                            |

## Verification and documentation

- [x] Run `make deps`, focused unit tests and affected regression tests. Preserve credential, usage-ledger and CLI
  trace/cost/activity regression coverage. Add a named regression reproduction for any existing bug fixed.
- [x] Run
  `PYTHON_DOTENV_DISABLED=1 ./scripts/test-integration.sh tests/integration/core/judgments/test_observability.py` after
  adding that fixture-based file. Include affected existing auth/trace/cost integrations when shared owners change;
  select deterministic cases explicitly to avoid paid inference in fixture gates.
- [x] Verify `forge telemetry trace list|show|explain`, `forge telemetry costs show --by-model|--by-verb`,
  `forge telemetry activity` and `forge proxy metrics --json` against isolated evidence. Extend output-stream tests if a
  CLI leaf changes; exposing this internal client does not itself require a new leaf.
- [x] Sync `docs/design.md`, `docs/design_runtime.md` and `docs/design_telemetry.md` as ownership/data flow ship. Add
  Jev to the direct-OpenRouter ZDR owners in `docs/design_installation.md` section 3.6.2. Update
  `docs/end-user/authentication.md` for credentials/readiness and opt-in API spend; distinguish client readiness from
  unshipped policy consumers. Update `docs/end-user/proxy.md` and `docs/cli_reference.md` for direct reported costs in
  the unfiltered spend view. Document repository-only probe usage in the harness README.
- [x] Verify imports and an externally injected offline transport without `provider-check` dependencies. If packaging
  configuration, bundled assets or resource loading changes, run `make build` and a clean-wheel smoke under the repo
  release rules. A new pure-Python module alone does not make that packaging gate mandatory; fixture code is never
  shipped to support the smoke.
- [x] Run `make test-unit`, `make test-regression` and `make pre-commit` on the final implementation head, plus board
  links. Record commands, outcomes and non-passing cases; rerun affected checks after subsequent changes.

## Closeout and handoff

- [x] Retain contract, limits, sanitized captures/manifests, measurement results, telemetry compatibility evidence and
  unresolved behavior under `evidence/`. Consumers must distinguish unusable judgments from unsupported routing.
- [x] Review A1's acceptance evidence and the epic's Gate 1. Record live ZDR readiness explicitly; an unexecuted capture
  is not a pass. Preserve any consumer dependency blocker even if offline transport work is useful independently.
- [x] Record reviewed PR, tested head and merge evidence; add the completed-work change-log entry. Promote durable
  lessons to implementation notes only after human review.
- [x] Move A1 to `done/` when shipped and verified. Repoint links and record the epic handoff. The epic remained active
  at A1's closeout to select A2 or A3 separately; its later retirement is recorded above.

## Planning verification

2026-10-14: initial activation and the review revisions passed `make pre-commit-md` and `git diff --check`. The final
standalone Markdown link audit passed for 673 sources, including the new evidence index. Implementation had not started
at that planning checkpoint.

## Initial implementation verification — 2026-10-14

- Final `make test-unit`: 10,908 passed, 117 integration-marked tests deselected. `make test-regression`: 1,843 passed.
  The new client/harness subset accounts for 103 offline tests.
- Final `make pre-commit`: passed, including mypy, pyright, formatting, secrets, size limits and links. Standalone
  Markdown audit: 676 sources passed. `git diff --check` and staged whitespace checks passed.
- `PYTHON_DOTENV_DISABLED=1 ./scripts/test-integration.sh tests/integration/core/judgments/test_observability.py`: four
  cases passed (managed/standalone, grouping on/off). The harness rebuilt Docker images. Its missing-Gemini-key warning
  does not affect these fixture-based tests; no Gemini inference was requested.
- Import and injected transport smoke passed with `tiktoken`, Anthropic and `google.genai` deliberately unavailable; the
  existing runtime OpenAI dependency remained available. No packaging configuration, bundled assets, resources or
  dependency changes require a clean-wheel gate.
- Initial `make test-unit`: 10,899 passed, 117 deselected, two documentation-state failures. New linked files were not
  staged yet, and changed design docs needed token-cache refresh. Staging the new targets and refreshing the three
  design-doc counts fixed both; the full rerun passed.
- Live CLI readback: all 25 measurement request IDs found; cost joins, missing cost and proxy-metrics isolation passed.
  See [operator evidence](evidence/2026-10-14/observability.json).

Planning is committed as `bde11e5f`; implementation is `04f3c01d`, the tested code head.
[PR #268](https://github.com/hapa1i/multi-forge/pull/268) was opened against `main`, followed by a docs-only handoff.
The merged closeout below supersedes that review checkpoint.

## PR review verification — 2026-10-14

Review fixes are committed as `0d6b923c`. The [replay record](evidence/2026-10-14/replay.json) identifies matching
source hashes for that code head. All 27 saved successes pass answer/accounting validation; the malformed and over-limit
controls retain their distinct failure kinds. No further paid inference ran.

- `make test-unit`: 10,910 passed, 117 integration-marked tests deselected. `make test-regression`: 1,854 passed.
- Focused client/harness/review regressions: 116 passed, including deeply nested JSON, unexpected transport/cleanup
  errors, extended size-error detail and cached-config isolation. Failed attempts retain valid reported usage and do not
  retry. Local nested-input rejection dispatches nothing.
- `PYTHON_DOTENV_DISABLED=1 ./scripts/test-integration.sh tests/integration/core/judgments/test_observability.py`: four
  passed. A separate session-end assertion confirmed the cached grouping flag was restored after all four cases.
- Full `make pre-commit` passed. The documentation follow-up also passed `make pre-commit-md` and `git diff --check`.

The report now distinguishes historical capture code from offline replay, records answer variance and separates early
cost from measurement-ledger totals. Cost guidance includes direct attempts without calling Jev the first direct-cost
producer; existing Claude paths already support reported direct cost. The `core_llm` route compatibility choice remains
unchanged.

Retry/deadline policy remains conservative. Three-sample latency measurements do not establish a minimum safe retry
window, and arbitrary deadline ceilings would constrain callers without a supported limit. The consumer contract at Gate
1 assigned the monotonic deadline and reviewer reserve to each caller. The epic remained active after A1's merge.

## Merged closeout

[PR #268](https://github.com/hapa1i/multi-forge/pull/268) merged on 2026-10-14 as
`9778007a281e896c12758e8df95cd08af2869d24`. Its tree is identical to reviewed head
`d02627ab60cf8eb8557d9420e70b9939e7638769`; GitHub pre-commit, tests, both CodeQL analyses and the CodeQL check all
passed. The tested runtime fix is `0d6b923c`; the final PR commit changes documentation only.

The PR passed 10,910 unit tests, 1,854 regressions, four targeted integrations and full pre-commit. Closeout passed all
116 focused client/harness/regression cases after moving evidence to `done/`, full `make pre-commit`, the Markdown link
audit for 676 sources and `git diff --check`. The replay test's fixture path follows the card move; historical
capture/replay hashes still identify their recorded source revisions. No production behavior changed or paid inference
ran during closeout.

Runtime, telemetry, installation, authentication and cost guidance describe the shipped transport and accounting.
Reviewed invariants are retained in the [runtime/telemetry notes](../../impl_notes/runtime_telemetry.md), and completion
is recorded in the [change log](../../change_log.md#2026-10-14).

Handoff: OpenRouter Decisions supports the three typed question shapes with ZDR required, default requested model
`typesafe/jev-1.13` and captured resolved model `typesafe/jev-1.13-20260917`. Preserve the 30,000-byte screen, unknown
cost on both HTTP 400 controls, measured answer variance and caller-owned deadline. Captures prove transport readiness,
not decision quality, guaranteed latency or quota savings. A2/A3 required separate activation and data/spend decisions;
neither consumer reached runtime activation before its cancellation and retirement on 2026-10-19. The client and its
evidence remain shipped independently of that decision.
