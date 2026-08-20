# Stabilize proxy metrics JSON

**Epic**: [`epic_wave8_residual_maintenance`](../../doing/epic_wave8_residual_maintenance/card.md).

**Lane**: `doing/` -- active in Wave 8 Batch 2 on `agent/wave8-batch-2` from `0eb68aea`.

**Finding**: O086 (LOW correctness/scriptability).

## Goal

Emit byte-valid proxy metrics JSON with a top-level shape that does not depend on how many proxies are registered.

## Verified Evidence

Both JSON paths call Rich `Console(width=200).print(json.dumps(...))`. A reproduced value with spaces beyond column 200
was hard-wrapped inside a JSON string and failed `json.loads`; Rich markup parsing can also reinterpret bracketed data.
Bare `metrics --json` returns raw metrics for one proxy but a proxy-ID mapping for multiple proxies.

## Acceptance Criteria

- Emit JSON through `click.echo` (or an equivalent non-rendering byte path), never Rich.
- Keep explicit `metrics <proxy_id> --json` as the selected proxy's raw metrics object.
- Make bare `metrics --json` always return a proxy-ID mapping for zero, one, or many registered proxies; use `null` for
  unreachable entries.
- Preserve human rendering, registry errors, and explicit-proxy exit behavior.
- Pin long whitespace-rich and Rich-markup-looking strings plus zero/one/many proxy shapes.

## Verification

Run focused proxy-command tests, full unit/regression suites, targeted Docker proxy metrics coverage, and
`make pre-commit`. Update `docs/cli_reference.md` and `docs/end-user/proxy.md` for the stable bare JSON envelope.
