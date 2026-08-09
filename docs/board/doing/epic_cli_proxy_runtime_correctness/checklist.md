# CLI, proxy, and runtime correctness checklist

Current focus: execute O001 User-Agent forwarding; O004 and D018 remain parked.

## Activation and sequencing

- [x] Merge the Wave 5 admission record (PR #147, `92b981a5`).
- [x] Start `fix/unify-downstream-retention` from merged `main`.
- [x] Move this epic and D015 to `doing/`, create their checklists, and repoint inbound links.
- [x] Retain a marked D015 regression that fails on the merged baseline before implementation.
- [x] Implement and verify D015 without activating any later member.
- [x] Independently review and merge D015 before moving O002 from `todo/` (PR #148, `8b997e6a`).
- [x] Start `fix/preserve-proxy-ownership-on-stop-failure`, move D015 to `done/`, and activate O002 from merged `main`.
- [x] Independently review and merge O002 before moving D016 from `todo/` (PR #149, `c20b8d10`).
- [x] Start `fix/stabilize-proxy-create-smoke-json`, move O002 to `done/`, and activate D016 from merged `main`.
- [x] Independently review and merge D016 before moving D017 from `todo/` (PR #150, `61580fdb`).
- [x] Start `fix/align-search-corruption-failures`, move D016 to `done/`, and activate D017 from merged `main`.
- [x] Review D017, add the missing corrupt `--scope all` control, and admit adjacent D051/D052 separately.
- [x] Merge D017 before moving O001 from `todo/` (PR #151, `efbefce9`).
- [x] Start `fix/forward-litellm-user-agent`, move D017 to `done/`, and activate O001 from merged `main`.

## Members

- [x] D015 -- global downstream retention ownership (PR #148, `8b997e6a`).
- [x] O002 -- preserve proxy ownership on stop failure (PR #149, `c20b8d10`).
- [x] D016 -- stabilize proxy create smoke-test JSON (PR #150, `61580fdb`).
- [x] D017 -- align search corruption failures (PR #151, `efbefce9`).
- [ ] O001 -- forward LiteLLM User-Agent metadata (active).
- [ ] O004 -- relay safe Anthropic response headers (parked).
- [ ] D018 -- make status-line sources segment-lazy (parked last).

## Coordination and closeout

- [ ] Keep the review ledger, parent epic cursor, member paths, and change log current after each merge.
- [ ] Keep later Wave 5 MEDIUM correctness rows outside this bounded seven-member epic pending separate admission.
- [ ] Close the epic only after all seven members ship independently with their required regression, focused, and Docker
  coverage.
