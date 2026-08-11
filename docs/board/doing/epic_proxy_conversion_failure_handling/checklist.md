# Proxy conversion failure handling checklist

Current focus: independently review and merge the verified O007 member, then close this child epic.

- [x] Review and merge the bounded admission record (PR #160, `cf77c175`).
- [x] Activate this epic and D053 from merged `main` on `fix/sanitize-proxy-conversion-failure-logs`.
- [x] Retain D053's fail-first non-streaming and streaming log-hygiene regressions.
- [x] Replace provider-controlled exception rendering with safe exception-class metadata only.
- [x] Preserve D053's non-streaming fallback, streaming wire, lifecycle, callback, and raw opt-in controls.
- [x] Run focused converter tests, the unit and regression suites, targeted translated-proxy Docker integration, and
  pre-commit.
- [x] Review and merge D053 independently before activating O007 (PR #161, `8088ceae`).
- [x] Activate O007 on `fix/fail-non-streaming-response-conversion` from merged `main`.
- [x] Implement and verify O007 on its own execution branch.
- [ ] Independently review and merge O007.
- [ ] Synchronize the ledger and member paths, then close this epic after both members ship.
