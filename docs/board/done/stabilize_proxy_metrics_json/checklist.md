# Stabilize proxy metrics JSON checklist

Current focus: complete -- O086 shipped in Batch 2 PR #226 and the card is closed.

## Phase 1 -- Pin byte and shape failures

- [x] Recheck current `main`: explicit and aggregate JSON both render through `Console(width=200)`, while bare JSON
  special-cases one proxy into the explicit raw object instead of the aggregate proxy-ID mapping.
- [x] Add fail-first coverage for whitespace-rich values beyond column 200 and Rich-markup-looking strings that must
  survive byte-for-byte JSON parsing.
- [x] Pin zero-, one-, and many-proxy bare JSON mappings, including `null` for unreachable entries, while keeping the
  explicit proxy shape raw.

## Phase 2 -- Implement and document

- [x] Route every metrics JSON success path through `click.echo(json.dumps(...))` without Rich rendering or markup
  interpretation.
- [x] Make bare `metrics --json` always aggregate by proxy ID; preserve explicit-proxy errors, exit codes, and human
  rendering.
- [x] Reconcile the stable JSON envelope in `docs/cli_reference.md` and `docs/end-user/proxy.md` at the Batch 2
  integration boundary.

## Phase 3 -- Verify and publish

- [x] Run focused proxy CLI/regression tests and targeted Docker proxy-metrics coverage.
- [x] Commit this card without mixing the cost-selector implementation (`e53a96ce`).
- [x] Run the combined unit, regression, pre-commit, documentation, board/link, and diff gates on the integrated Batch 2
  head.
- [x] Merge Batch 2 as `5f02bb0f`, confirm all five GitHub checks, record the closeout, and move both cards to `done/`.

Focused evidence (2026-08-20):

- Fail-first: the new O086 regression file produced three intended failures -- a long whitespace-rich value became
  invalid JSON, Rich stripped markup-looking text, and bare one-proxy JSON returned the raw object; three shape controls
  passed.
- `uv run pytest tests/src/cli/test_proxy_commands.py::TestProxyMetrics tests/regression/test_bug_o086_proxy_metrics_json.py tests/src/cli/test_output_streams.py -q`:
  `67 passed`.
- `./scripts/test-integration.sh tests/integration/proxy/test_proxy_local_litellm_e2e.py::TestProxyWithLocalLiteLLM::test_health_endpoint -q`:
  `1 passed`.
- Repository hooks on the card's source, regression, and checklist plus `git diff --check`: passed.
- Integrated Batch 2 head: `97` focused, `9,331` unit with `124` deselected, and `1,005` regression tests passed; both
  targeted Docker boundaries and final `make pre-commit` passed.

## Acceptance tests

| Boundary          | Fixture                                       | Assertion                                                     | Tier             |
| ----------------- | --------------------------------------------- | ------------------------------------------------------------- | ---------------- |
| Byte-safe JSON    | long whitespace and bracket-rich metric value | stdout parses and preserves the exact string                  | CLI regression   |
| Bare zero proxies | empty registry                                | output is `{}`                                                | CLI unit         |
| Bare one proxy    | one reachable proxy                           | output is `{proxy_id: metrics}`                               | CLI regression   |
| Bare many proxies | reachable and unreachable proxies             | one mapping includes metrics and `null` respectively          | CLI unit         |
| Explicit proxy    | one selected reachable proxy                  | output remains the raw metrics object                         | CLI unit         |
| Human/errors      | implicit/explicit human reads and bad targets | Rich layout and existing error/exit behavior remain unchanged | unit/integration |
