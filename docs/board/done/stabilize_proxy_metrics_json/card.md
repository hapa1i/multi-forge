# Stabilize proxy metrics JSON

**Epic**: [`epic_wave8_residual_maintenance`](../epic_wave8_residual_maintenance/card.md).

**Lane**: `done/` -- shipped with the cost card in Batch 2 PR #226 (`5f02bb0f`) on 2026-08-20.

**Execution**: `agent/wave8-batch-2` from pushed `main` at `0eb68aea`.

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

Focused proxy CLI/regression coverage passed 67 tests. The integrated Batch 2 head passed 97 focused tests, 9,331 unit
tests with 124 deselected, 1,005 regressions, a targeted live proxy-health Docker boundary, full pre-commit, board/link
checks, and all five GitHub checks. The stable bare JSON envelope is documented in the CLI reference and proxy guide.
