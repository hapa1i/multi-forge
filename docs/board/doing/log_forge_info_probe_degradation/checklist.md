# Log `forge info` probe degradation checklist

Current focus: pin O081's silent best-effort fallbacks and the direct Python-version control before implementation.

## Phase 1 -- Pin degradation evidence

- [ ] Add fail-first caplog coverage for package-version, `uv`, proxy-registry, and session-list probe failures.
- [ ] Require each debug record to name its probe without leaking exception text into normal stdout or stderr.
- [ ] Pin the actionable tracking-store early return and successful human/JSON shapes as unchanged controls.
- [ ] Characterize direct `sys.version_info` access so no impossible fallback branch remains.

## Phase 2 -- Implement

- [ ] Add one module logger and debug evidence at every recoverable optional-probe boundary.
- [ ] Remove only the impossible standard-library exception scaffold around Python version construction.
- [ ] Preserve best-effort continuation, tracking-store failure semantics, output schemas, and secret safety.

## Phase 3 -- Verify and publish

- [ ] Run focused info, output-stream, and O081 regression tests.
- [ ] Commit O081 as its own implementation boundary after O076 and before O085.
- [ ] Run full unit, regression, pre-commit, documentation, board/link, and diff gates on the combined head.
- [ ] Publish all three cards in one draft PR; close them together only after merge.

## Acceptance tests

| Boundary          | Fixture                          | Assertion                                                | Tier           |
| ----------------- | -------------------------------- | -------------------------------------------------------- | -------------- |
| Forge version     | metadata lookup raises           | `unknown` plus named debug record; no ordinary stderr    | CLI regression |
| uv version        | subprocess probe raises          | `unknown` plus named debug record; dashboard continues   | CLI regression |
| Proxy registry    | registry construction/read fails | empty proxies plus named debug record                    | CLI regression |
| Session inventory | manager construction/list fails  | empty sessions plus named debug record                   | CLI regression |
| Tracking store    | manifest read fails              | existing actionable result and early return are retained | existing unit  |
