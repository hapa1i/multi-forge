# LiteLLM streaming cost verification

Verified on 2026-10-28 against the locked LiteLLM 1.102.0 package. No provider inference was dispatched.

## Gateway characterization

The integration fixture calls the pinned package's public `completion` API with a fixed `ModelResponse`,
`mock_response`, `stream=True` and `stream_options={"include_usage": True}`. It uses the bundled model-cost map and
blocks socket connections during stream generation. This exercises LiteLLM's stream assembly and cost stamping without
contacting Gemini or a gateway deployment.

The synthetic `gemini/gemini-3.8-flash` response supplies 120 prompt tokens, 3 completion tokens and text `ok`. After
the text and stop chunks, LiteLLM emits one final usage chunk:

```json
{
  "prompt_tokens": 120,
  "completion_tokens": 3,
  "total_tokens": 123,
  "completion_tokens_details": {"reasoning_tokens": 0},
  "cost": 0.00010125000000000001
}
```

That amount comes from the gateway's calculation. Forge preserves the received amount, rounds it to 101 micro-USD for
downstream accounting, and labels it `reporter=litellm`, `confidence=gateway_calculated`. The test asserts positive
calculated cost rather than freezing the package's price table.

## Contract coverage

The [SDK transport cases](../../../../tests/src/core/llm/test_litellm_cost.py) exercise local and remote LiteLLM
providers through real OpenAI SDK SSE parsing. Cost and tokens survive both terminal events; cached tokens survive the
usage conversion. A deliberately misleading stream-start cost header is ignored.

The [proxy integration cases](../../../../tests/integration/proxy/test_litellm_streaming_cost_e2e.py) serve the pinned
gateway chunks over loopback HTTP to a real Forge proxy subprocess. Variants remove the cost, remove final usage, or set
explicit zero without changing the production path.

| Fixture              | Input/output tokens | Cost          | Downstream provenance            | Cap result                                   |
| -------------------- | ------------------- | ------------- | -------------------------------- | -------------------------------------------- |
| Pinned gateway usage | 120 / 3             | 101 micro-USD | `litellm` / `gateway_calculated` | Two requests count once each; third rejected |
| Cost omitted         | 120 / 3             | null          | null / `unavailable`             | No dollar increment                          |
| Final usage omitted  | 0 / 0 fallback      | null          | null / `unavailable`             | No dollar increment                          |
| Explicit zero        | 120 / 3             | 0             | `litellm` / `gateway_calculated` | Available zero, no dollar increment          |

Each completed request produces one downstream attempt with its own event ID. Both
`forge telemetry costs show <proxy> --by-model --json` and `forge proxy metrics <proxy> --json` agree with the records
and cap totals. The second charged stream is admitted and crosses the cap; the third is refused before upstream
dispatch, proving that the duplicate terminal cost fields do not double-charge one stream.

## Checks

- Focused cost client, OpenAI compatibility, proxy cost and cap tests: 89 passed.
- Standard integration runner with the new cost module and `test_finish_reason_e2e.py`: 8 passed, no skips or reruns.
  Provider credentials were unset and `PYTHON_DOTENV_DISABLED=1`; the runner's missing-Gemini-key warning refers to
  unrelated live tests, not these loopback fixtures.
- `make test-regression`: 2,212 passed.
- `make test-unit`: 11,234 passed, 120 integration tests deselected on 2026-10-29, including the document-cache hash
  check after the approved refresh.
- `make pre-commit`: all hooks passed on 2026-10-29, including lint, type checks, file-size limits and Markdown links.
- Final approved counts on 2026-10-29: telemetry design 23,461 and proxy guide 22,489 Claude Opus 5 tokens. All cached
  document hashes match their current contents.

This verifies the installed pin and Forge's transport/accounting contract. It does not verify billed provider spend or
the behavior of an independently deployed remote gateway.
