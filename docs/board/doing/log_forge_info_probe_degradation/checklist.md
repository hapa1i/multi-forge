# Log `forge info` probe degradation checklist

Current focus: implementation commit `a7cea967` and all local gates are complete; publish the shared Batch 4 review.

## Phase 1 -- Pin degradation evidence

- [x] Add fail-first caplog coverage for package-version, `uv`, proxy-registry, and session-list probe failures.
- [x] Require each debug record to name its probe without leaking exception text into normal stdout or stderr.
- [x] Pin the actionable tracking-store early return and successful human/JSON shapes as unchanged controls.
- [x] Characterize direct `sys.version_info` access so no impossible fallback branch remains.

## Phase 2 -- Implement

- [x] Add one module logger and debug evidence at every recoverable optional-probe boundary.
- [x] Remove only the impossible standard-library exception scaffold around Python version construction.
- [x] Preserve best-effort continuation, tracking-store failure semantics, output schemas, and secret safety.

## Phase 3 -- Verify and publish

- [x] Run focused info, output-stream, and O081 regression tests.
- [x] Commit O081 as its own implementation boundary after O076 and before O085.
- [x] Run full unit, regression, pre-commit, documentation, board/link, and diff gates on the combined head.
- [ ] Publish all three cards in one draft PR; close them together only after merge.

## Acceptance tests

| Boundary          | Fixture                          | Assertion                                                | Tier           |
| ----------------- | -------------------------------- | -------------------------------------------------------- | -------------- |
| Forge version     | metadata lookup raises           | `unknown` plus named debug record; no ordinary stderr    | CLI regression |
| uv version        | subprocess probe raises          | `unknown` plus named debug record; dashboard continues   | CLI regression |
| Proxy registry    | registry construction/read fails | empty proxies plus named debug record                    | CLI regression |
| Session inventory | manager construction/list fails  | empty sessions plus named debug record                   | CLI regression |
| Tracking store    | manifest read fails              | existing actionable result and early return are retained | existing unit  |

## Focused evidence (2026-08-21)

- Fail first: the O081 regression produced five intended failures: four exception fallbacks emitted no debug evidence,
  and a non-zero `uv --version` result omitted the fallback field (`5 failed, 1 passed`).
- Final: the info, output-stream, stale-tracking, and O081 regression slice passed (`66 passed`).
- Debug evidence names only the probe plus exception type or exit code; the sentinel exception/stderr secret is absent
  from logs and ordinary stderr.
- Repository-pinned Ruff, isort, Black, mypy, Pyright, secret, and hygiene hooks passed for both changed Python files.
- Integrated: the 165-test combined slice, 9,331 unit tests, 1,035 regressions, and full pre-commit gate passed without
  changing normal `forge info` streams or schemas.
