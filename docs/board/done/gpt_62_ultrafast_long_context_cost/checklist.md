# GPT-6.2 Ultrafast long-context accounting

Merged into `main` on 2026-11-23 as `ae188cb6`. Its tree matches the tested PR head `5eb82a0e`.
[PR #306](https://github.com/hapa1i/multi-forge/pull/306)

- [x] Reproduce the launch-price undercount in LiteLLM 1.102.2. With 272,001 uncached input tokens and ten output
  tokens, the offline calculator returns $1.088154 for both Standard and Ultrafast on Sol. The Ultrafast launch price
  for that request is $3.264462.
- [x] Backport the pricing correction to LiteLLM 1.102.2. The offline pricing test for each model checks the token
  calculator and gateway response cost.
- [x] Verify Standard, Flex, Priority, Fast and Ultrafast for both models at 272,000 and 272,001 input tokens, including
  cached reads, 30-minute cache writes and output.
- [x] Load the pre-upgrade deployment entries with the pricing backport. At 272,001 inputs, including 1,000 30-minute
  writes, and ten outputs, the gateway reports $13.069848 on Astra and $3.267462 on Sol.
- [x] Verify mixed retention through the Responses endpoint. With 272,001 inputs, 1,000 cached, 200 writes at 30
  minutes, 300 at 12 hours, and ten outputs, Ultrafast costs $13.036248 on Astra and $3.259062 on Sol.
- [x] Verify the same amounts in downstream telemetry and in both daily and monthly caps. Each proxy rejected the next
  request before forwarding it. Eleven Docker cases passed across the Ultrafast, OpenAI routing and LiteLLM
  streaming-cost suites.
- [x] Document the managed restart, saved 12-hour rates and independently operated gateways.
- [x] Start the module with Uvicorn `--num_workers 2`. Six loopback Sol receipts from two distinct worker PIDs each
  reported $3.259062 for the mixed-retention long-context request.
- [x] Install the built wheel in a clean environment and verify that the managed gateway starts and passes its health
  check with the existing local configuration.
- [x] Run the repository checks. All 12,060 unit tests, all 2,733 regression tests and the full pre-commit suite passed.
  Both Python CI lanes and the test-selection comparison passed.
  [CI run](https://github.com/hapa1i/multi-forge/actions/runs/45146378664)
- [x] Move the merged card to `done/` and update its links from the GPT-6.2 models checklist and the March pricing card.
