# Wave 6 correctness maintenance checklist

Current focus: D034/D037/D038/O027 implementation and every verification gate are complete on
`agent/harden-command-state-boundaries`; obtain independent review while keeping the remaining 2 members parked.

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
- [x] Activate only O014/O026 from merged `main` at `4774f69e` on `agent/close-proxy-failure-lifecycles`.
- [x] Retain O014/O026 fail-first regressions before production changes (`4 failed, 2 passed` on `4774f69e`).
- [x] Implement and verify failed-restart ownership plus non-200 body-read cleanup in both passthrough transports.
- [x] Review and merge O014/O026 independently before activating the next ordered member (PR #167, `33e3db7f`).
- [x] Keep the remaining 8 members in `todo/` through the O014/O026 merge; no later member is active.
- [x] Activate only D029/O025 from merged `main` at `7c76a099` on `agent/complete-proxy-instance-config-wiring`.
- [x] Retain D029/O025 fail-first regressions before production changes (`3 failed, 2 passed` on `7c76a099`).
- [x] Implement and verify template-to-instance-to-runtime tool-ignore and prompt-cache wiring.
- [x] Review and merge D029/O025 independently before activating the next ordered member (PR #168, `9b18edc3`).
- [x] Record PR #169 (`ece999d4`) as post-merge O012 and retention-status hardening without changing the admitted
  finding count.
- [x] Activate only D030/O008/O015/O035 from merged `main` at `7f705aad` on `agent/restore-proxy-request-semantics`.
- [x] Retain D030/O008/O015/O035 fail-first regressions before production changes (the final artifact collects
  `6 failed, 3 passed` on `7f705aad`, including the adapter seam and satisfied-floor control; the separate GPT Responses
  seam also failed).
- [x] Implement and verify tier authority, auth-retry tier identity, reasoning/sampling compatibility, and required-tool
  translation.
- [x] Review and merge D030/O008/O015/O035 in PR #170 (`acae1b9e`) before activating the next member.
- [x] Verify and admit follow-up D054/D055 as one new proxy-boundary member on merged `main` at `22071fcd`.
- [x] Activate only D054/D055 on `agent/harden-proxy-boundary-failures`.
- [x] Retain D054/D055 fail-first regressions before production changes (`24 failed, 2 passed` on `22071fcd`).
- [x] Implement and verify proxy direct-field validation plus atomic typed spawn failure.
- [x] Review and merge D054/D055 independently in PR #171 (`5cd268c1`) before activating another member.
- [x] Keep the remaining 6 members in `todo/` through the D054/D055 merge.
- [x] Activate only O013/O034 on `agent/align-policy-routing-context` from merged `main` at `f6df4a40`.
- [x] Retain O013/O034 fail-first regressions before production changes (`6 failed, 10 passed` on `f6df4a40`).
- [x] Implement and verify confirmed current-proxy identity plus one shadow-session resolver.
- [x] Review and merge O013/O034 independently in PR #172 (`366c216a`) before activating another member.
- [x] Keep the remaining 5 members in `todo/` behind their own fail-first gates.
- [x] Activate only D031 on `agent/exclude-interactive-usage-cost` from merged `main` at `7280d177`.
- [x] Retain D031 fail-first regressions before production changes (`3 failed, 3 passed` on `7280d177`).
- [x] Implement and verify the two-plane interactive-cost exclusion (`223` focused, `821` regression, `9001` unit, and
  `1` targeted integration test passed).
- [x] Review and merge D031 independently in PR #173 (`a55ab218`) before activating another member.
- [x] Keep the remaining 4 members in `todo/` behind their own fail-first gates.
- [x] Activate only D032/D041/O005/O031--O033 on `agent/align-cli-failure-surfaces` from merged `main` at `13ecef87`.
- [x] Retain fail-first regressions for every CLI/status/editor failure surface (`19 failed, 4 passed` on `13ecef87`).
- [x] Implement and verify the status-line, exit/stream, and shared editor-argv contracts (`809` focused, `844`
  regression, `9005` unit, and `19` targeted Docker integration tests passed).
- [x] Review and merge this member independently in PR #174 (`095fcd90`) before activating another member.
- [x] Keep the remaining 3 members in `todo/` behind their own fail-first gates.
- [x] Close PR #174 bookkeeping and activate only D034/D037/D038/O027 from merged production code at `095fcd90` on
  `agent/harden-command-state-boundaries`; keep the remaining 2 members parked.
- [x] Retain fail-first regressions for the hook-silence, reserved-passport, strict-search-read, and Optional-unwrapping
  boundaries before production changes (`21 failed, 5 passed` on production code at `095fcd90`).
- [x] Implement and verify silent no-session hooks, reserved passport mutations, strict search-store shapes, and
  Union-only Optional unwrapping (`681` focused, `872` regression, `9004` unit, and `24` targeted Docker integration
  tests passed).
- [ ] Close this epic only after every accepted member ships and the review ledger records each outcome.
