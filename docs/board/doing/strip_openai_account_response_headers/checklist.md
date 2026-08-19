# Strip OpenAI account response headers checklist

Current focus: prove and close O074 at the shared response-header boundary without narrowing safe provider metadata.

## Phase 1 -- Characterize and activate

- [x] Activate only Wave 8 order 3 from pushed closeout `cddfe5c3` on `agent/strip-openai-account-response-headers`;
  keep orders 4--19 parked.
- [x] Recheck that request construction strips `OpenAI-Organization` and `OpenAI-Project` while the shared response
  relay currently permits both through Messages and Responses.
- [x] Add fail-first regression coverage for both transports and mixed-case account header spellings; both cases failed
  on execution base `cddfe5c3` because the account headers were relayed.

## Phase 2 -- Implement

- [x] Add both OpenAI account headers to the shared case-insensitive response denylist.
- [x] Preserve safe provider metadata, rate-limit/retry headers, connection-token filtering, and Forge's canonical
  request ID overlay.
- [x] Synchronize the normative response-relay contract without broadening this member into request policy or general
  header allowlisting.

## Phase 3 -- Verify and publish

| Boundary             | Fixture                                      | Assertion                                                       | Tier       |
| -------------------- | -------------------------------------------- | --------------------------------------------------------------- | ---------- |
| Messages relay       | mixed-case upstream account headers          | organization/project absent; safe metadata remains              | regression |
| Responses relay      | mixed-case upstream account headers          | organization/project absent; safe metadata remains              | regression |
| Shared policy        | hop-by-hop, connection-token, and rate-limit | existing filtering and safe-header relay remain unchanged       | unit       |
| Canonical request ID | upstream request IDs plus Forge request ID   | Forge's canonical request ID remains the sole public request ID | unit       |

- [x] Run focused response-header, Messages, Responses, and O074 regression tests (135 passed).
- [x] Run `make test-unit` (9,312 passed, one skip), `make test-regression` (944 passed), targeted Docker proxy routing
  coverage (eight passed), and `make pre-commit`.
- [x] Verify documentation size (`design.md` 29,991; appendix 29,988 Opus-5 tokens), all 968 local board links, branch
  diff hygiene, and a source/diff boundary review.
- [x] Commit, push, and open independent draft PR #218.
- [ ] After merge, close order 3 before activating order 4.
