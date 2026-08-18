# Share passthrough SSE framing checklist

Current focus: closed -- order 30 shipped in PR #209; orders 31--35 remain parked.

## Activation and evidence

- [x] Close order 29 on pushed `main` at `1d02b0cb`, create the execution branch from that exact commit, and move only
  this member to `doing/`.
- [x] Re-run source and caller searches: Anthropic and Responses retain the same framing loop, no neutral framer exists,
  and their `_merge` methods remain protocol-specific.
- [x] Record the pre-change baseline for both complete passthrough unit files (126 passed).

## Implementation

- [x] Add one neutral incremental SSE JSON data-line framer that owns buffering, split lines, `[DONE]`, malformed JSON,
  and generic fail-open diagnostics without retaining or changing forwarded chunks.
- [x] Compose both usage accumulators with the framer while keeping Anthropic and Responses event merging, lifecycle
  flags, usage normalization, forwarding, teardown, and completion callbacks local.
- [x] Add direct framer characterization for split chunks, multiple events, CRLF/noise, empty/`[DONE]`, malformed JSON,
  and invalid UTF-8 input.
- [x] Record the shared framing and protocol-owned merge boundary in the normative proxy design.

## Acceptance tests

| Boundary            | Fixture                                                                          | Assertion                                                         | Test file                                     |
| ------------------- | -------------------------------------------------------------------------------- | ----------------------------------------------------------------- | --------------------------------------------- |
| Incremental framing | JSON data lines split across byte chunks                                         | complete decoded events are delivered once and in order           | `tests/src/proxy/test_sse_framing.py`         |
| Tolerance           | comments, event lines, empty data, `[DONE]`, malformed JSON, CRLF, invalid UTF-8 | bad/no-op lines are ignored without payload logging or exceptions | `tests/src/proxy/test_sse_framing.py`         |
| Anthropic merge     | start/content/final usage events                                                 | first-content and last cumulative usage semantics are unchanged   | `tests/src/proxy/test_passthrough.py`         |
| Responses merge     | output and completed/incomplete/failed events                                    | terminal status and final usage semantics are unchanged           | `tests/src/proxy/test_responses_transport.py` |
| Relay boundary      | streaming passthrough request                                                    | raw chunks and completion/accounting lifecycle remain unchanged   | targeted proxy integration                    |

## Verification and closeout

- [x] Run the shared-framer and both complete passthrough unit files.
- [x] Run the conversion/accounting regression slice and targeted streaming proxy integrations.
- [x] Run `make test-unit`, `make test-regression`, full `make pre-commit`, diff/design-size checks, and the board audit
  without a Forge workflow.
- [x] Merge PR #209 as `a1efd5d7` and close this member without activating order 31.
