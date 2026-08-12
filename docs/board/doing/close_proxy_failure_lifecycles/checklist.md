# Close proxy failure lifecycles checklist

Current focus: complete final quality and board gates, then prepare independent review.

## Activation and prior-member closeout

- [x] Merge D027/O012 independently in PR #166 (`5b50acc8`).
- [x] Record its post-merge closeout on `main` at `4774f69e`.
- [x] Start `agent/close-proxy-failure-lifecycles` from merged `main` at `4774f69e`.
- [x] Move D027/O012 to `done/`, activate only this member, and repoint inbound board links.

## Fail-first reproduction

- [x] Prove a failed restart discards an existing registry entry while preserving its proxy configuration.
- [x] Prove a failed config-only restart leaves no stopped ownership entry.
- [x] Prove an Anthropic non-200 body-read error skips stream/client cleanup and completion reporting.
- [x] Prove a Responses non-200 body-read error skips stream/client cleanup and completion reporting (`4 failed` across
  the ownership/read-error cases on unchanged production code from `4774f69e`).
- [x] Retain ordinary non-200 relay controls in both transports (`2 passed` before production changes) and successful
  startup coverage.

## Implementation

- [x] Restore prior registry ownership after a failed restart, or retain a stopped entry when only config existed.
- [x] Close both upstream contexts and report failure once when either transport cannot read a non-200 body.
- [x] Return the stable provider-safe upstream failure response without relaying partial provider content.
- [x] Preserve successful startup, adoption, response headers, and ordinary non-200 relay semantics.

## Verification and closeout

- [x] Run focused orchestrator and Anthropic/Responses passthrough tests (`193 passed`) and the full proxy unit package
  (`814 passed`).
- [x] Run the retained regression (`6 passed`) and targeted proxy Docker integration tier (`5 passed`).
- [x] Run full unit (`8,981 passed`, one existing platform skip, 122 deselected) and marked regression (`753 passed`)
  gates.
- [x] Run `make pre-commit`, an explicit new-file pass, and final board integrity checks (287 files, 720 local links,
  12-member graph: 3 `done` / 1 `doing` / 8 `todo`); size and diff checks pass.
- [x] Synchronize the design appendix and end-user proxy lifecycle contracts.
- [x] Record fail-first evidence, implementation outcome, verification, and compatibility boundaries.
- [ ] Open an independent draft PR without activating the next Wave 6 member.
