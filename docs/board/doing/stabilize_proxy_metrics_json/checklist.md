# Stabilize proxy metrics JSON checklist

Current focus: active in Wave 8 Batch 2 on `agent/wave8-batch-2` from pushed closeout `0eb68aea`; pin O086 before
implementation.

## Phase 1 -- Pin byte and shape failures

- [x] Recheck current `main`: explicit and aggregate JSON both render through `Console(width=200)`, while bare JSON
  special-cases one proxy into the explicit raw object instead of the aggregate proxy-ID mapping.
- [ ] Add fail-first coverage for whitespace-rich values beyond column 200 and Rich-markup-looking strings that must
  survive byte-for-byte JSON parsing.
- [ ] Pin zero-, one-, and many-proxy bare JSON mappings, including `null` for unreachable entries, while keeping the
  explicit proxy shape raw.

## Phase 2 -- Implement and document

- [ ] Route every metrics JSON success path through `click.echo(json.dumps(...))` without Rich rendering or markup
  interpretation.
- [ ] Make bare `metrics --json` always aggregate by proxy ID; preserve explicit-proxy errors, exit codes, and human
  rendering.
- [ ] Reconcile the stable JSON envelope in `docs/cli_reference.md` and `docs/end-user/proxy.md` at the Batch 2
  integration boundary.

## Phase 3 -- Verify and publish

- [ ] Run focused proxy CLI/regression tests and targeted Docker proxy-metrics coverage.
- [ ] Commit this card without mixing the cost-selector implementation.
- [ ] Run the combined unit, regression, pre-commit, documentation, board/link, and diff gates on the integrated Batch 2
  head.
- [ ] Publish with the cost card in one Batch 2 PR; close both cards together only after merge.

## Acceptance tests

| Boundary          | Fixture                                       | Assertion                                                     | Tier             |
| ----------------- | --------------------------------------------- | ------------------------------------------------------------- | ---------------- |
| Byte-safe JSON    | long whitespace and bracket-rich metric value | stdout parses and preserves the exact string                  | CLI regression   |
| Bare zero proxies | empty registry                                | output is `{}`                                                | CLI unit         |
| Bare one proxy    | one reachable proxy                           | output is `{proxy_id: metrics}`                               | CLI regression   |
| Bare many proxies | reachable and unreachable proxies             | one mapping includes metrics and `null` respectively          | CLI unit         |
| Explicit proxy    | one selected reachable proxy                  | output remains the raw metrics object                         | CLI unit         |
| Human/errors      | implicit/explicit human reads and bad targets | Rich layout and existing error/exit behavior remain unchanged | unit/integration |
