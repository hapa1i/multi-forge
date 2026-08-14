# Remove a redundant dependency declaration checklist

Current focus: active as Wave 7 order 8 on `refactor/remove-stale-dependencies`; keep orders 9--35 parked.

## Activation and evidence

- [x] Close the PR #185 corrective member on `main` at `5bd69ef5` before selecting order 8.
- [x] Create the order-8 branch, move only O071 to `doing/`, and repoint its board links.
- [x] Recheck direct imports, Starlette's optional import, repository `TestClient` use, and dependency history: `httpx2`
  is a live test-infrastructure dependency added deliberately in `d50d8635`, so reject that half of O071.
- [x] Recheck `python-dotenv`: runtime and transitive consumers remain live, while the separate dev declaration is
  redundant.

## Implementation

- [x] Remove only dev-group `python-dotenv`; retain runtime `python-dotenv`, runtime `httpx`, and dev `httpx2`.
- [x] Regenerate `uv.lock` and verify only the redundant root dev edge disappears, with the package graph unchanged.
- [x] Prove Starlette selects `httpx2` under warnings-as-errors and pass the focused test-client suite.
- [x] Confirm built wheel metadata retains runtime `python-dotenv` and `httpx` without leaking dev-group metadata.

## Acceptance tests

| Boundary         | Fixture                                         | Assertion                                                |
| ---------------- | ----------------------------------------------- | -------------------------------------------------------- |
| Dev graph        | root project and lock metadata                  | duplicate `python-dotenv` edge absent; `httpx2` retained |
| Test client      | strict Starlette import and focused proxy tests | `httpx2` selected with no warning                        |
| Runtime metadata | built wheel requirements                        | runtime `python-dotenv` and `httpx` remain               |
| Clean install    | isolated wheel environment                      | dependency check and `forge --help` succeed              |

## Verification and closeout

- [x] Build wheel/sdist and run the clean-wheel runtime smoke plus isolated `forge --help`.
- [x] Run full unit (9,115 passed, one expected skip) and regression (906 passed) suites.
- [x] Run full pre-commit, Markdown, dependency-tree, board-size, board-link/lane, and diff checks.
- [x] Record the verified outcome and adjusted O071 disposition without activating order 9.
- [ ] Open an independent PR without activating order 9.
- [ ] After merge, add the change-log entry, move this card to `done/`, and only then select order 9.
