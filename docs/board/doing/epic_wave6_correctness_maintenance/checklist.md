# Wave 6 correctness maintenance checklist

Current focus: reproduce and ship D023/D028/O022 without activating or absorbing any later member.

- [x] Merge the Wave 5 closeout and Wave 6 handoff in PR #163 (`55fcda59`).
- [x] Activate this epic and D020 from merged `main` on `agent/d020-inherited-forge-headers`.
- [x] Retain a fail-first D020 regression before changing production code (`1 failed` on merged `main` at `55fcda59`).
- [x] Strip inherited Forge-owned headers for direct children while preserving unrelated user headers.
- [x] Preserve freshly derived correlation headers for proven Forge proxies.
- [x] Run the reactive-env unit slice (`85 passed`), full regression suite (`727 passed`), and targeted correlation
  integration canary (`6 passed`).
- [x] Run pre-commit after its expected mdformat normalization pass.
- [x] Run final board integrity checks (284 files, 719 relative links, 12 changed-file fragments, and the 12-member lane
  graph pass).
- [x] Review and merge D020 independently before activating the next ordered member (PR #164, `26ab5f29`).
- [x] Keep the remaining 11 members in `todo/` until D020 merges.
- [x] Close D020 and activate only D023/D028/O022 on `agent/align-transfer-preflight-cli-contract`.
- [x] Retain D023/D028/O022 fail-first regressions on merged `main` (`7 failed, 2 passed` on `26ab5f29`).
- [x] Implement and verify the shared transfer-source, depth, and non-fresh flag contracts.
- [ ] Review and merge D023/D028/O022 independently before activating the next ordered member.
- [ ] Keep the remaining 10 members in `todo/` behind their own fail-first gates.
- [ ] Close this epic only after every accepted member ships and the review ledger records each outcome.
