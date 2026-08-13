# Wave 6 correctness maintenance checklist

Current focus: PR #170 is merged; keep the remaining 6 members parked until the next accepted member is activated from
merged `main`.

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
- [ ] Keep the remaining 6 members in `todo/` behind their own fail-first gates.
- [ ] Close this epic only after every accepted member ships and the review ledger records each outcome.
