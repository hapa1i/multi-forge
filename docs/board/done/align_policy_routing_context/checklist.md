# Align policy routing context checklist

Current focus: complete -- shipped in PR #172 (`366c216a`); the remaining five Wave 6 members stayed parked through
merge.

## Activation

- [x] Close D054/D055 after PR #171 (`5cd268c1`) and record the bookkeeping on `main` at `f6df4a40`.
- [x] Start `agent/align-policy-routing-context` from that merged-main cursor.
- [x] Move only O013/O034 to `doing/` and keep the remaining five Wave 6 members parked.

## Fail-first reproduction

- [x] Prove a matching confirmed current proxy is treated as a routing no-op rather than an auto-seeded change.
- [x] Prove shadow `show` and `status` select the same explicit, current, and sole-local session.
- [x] Prove missing and ambiguous implicit selection fail cleanly in both human and JSON modes (`6 failed, 10 passed` in
  the retained final artifact on `f6df4a40`).

## Implementation

- [x] Read the current proxy id from confirmed runtime routing without adding it to `ProxyIntent` or changing intent
  ownership.
- [x] Route shadow `show` and `status` through one policy-session resolver while preserving stderr and JSON contracts.
- [x] Keep explicit supervisor-routing behavior and unrelated policy commands unchanged.

## Verification and closeout

- [x] Run focused policy command-core and CLI tests plus the retained regression artifact (`248 passed`).
- [x] Run the marked regression (`815 passed`) and unit (`9001 passed, 1 skipped, 122 deselected`) gates.
- [x] Run the affected non-slow policy/supervisor integration slice (`9 passed, 1 deselected`).
- [x] Run full pre-commit (all hooks passed after the expected Markdown normalization pass).
- [x] Confirm the implementation preserves the existing design/end-user contracts; no synchronization change is
  required.
- [x] Run board link/lane/size and diff checks (292 Markdown files, 718 relative links with none missing, Wave 6 at 7
  done / 1 doing / 5 todo, 680-token checklist, clean `git diff --check`).
- [x] Open PR #172 for independent review before activating another Wave 6 member.

## Acceptance tests

| Test                      | Fixture                                                   | Assertion                                              | Test file                                                       |
| ------------------------- | --------------------------------------------------------- | ------------------------------------------------------ | --------------------------------------------------------------- |
| Matching proxy route      | intent proxy plus matching confirmed current/source proxy | no redundant supervisor proxy override                 | `tests/regression/test_bug_o013_o034_policy_routing_context.py` |
| Shared implicit selection | one local session and no `FORGE_SESSION`                  | both shadow reads select that session                  | `tests/regression/test_bug_o013_o034_policy_routing_context.py` |
| Resolver precedence       | explicit/current/local candidates                         | both reads use explicit, then current, then sole local | `tests/regression/test_bug_o013_o034_policy_routing_context.py` |
| Resolver failures         | zero or multiple local sessions                           | stderr-only human or JSON error and exit 1             | `tests/regression/test_bug_o013_o034_policy_routing_context.py` |
