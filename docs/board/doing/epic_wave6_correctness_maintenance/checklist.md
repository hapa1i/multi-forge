# Wave 6 correctness maintenance checklist

Current focus: D027/O012 shipped; keep O014/O026 parked until its own fail-first activation begins.

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
- [x] Review and merge D023/D028/O022 independently before activating the next ordered member (PR #165, `b3150184`).
- [x] Close D023/D028/O022 and activate only D027/O012 on `agent/harden-detached-process-teardown`.
- [x] Retain D027/O012 fail-first regressions on merged `main` at `b3150184` (`3 failed, 2 passed`).
- [x] Implement and verify detached backend and single-shot headless process-group teardown.
- [x] Review and merge D027/O012 independently before activating the next ordered member (PR #166, `5b50acc8`).
- [x] Keep the remaining 9 members in `todo/` through the D027/O012 merge; no later member is active.
- [ ] Activate only O014/O026 from merged `main` and retain its fail-first reproduction before production changes.
- [ ] Close this epic only after every accepted member ships and the review ledger records each outcome.
