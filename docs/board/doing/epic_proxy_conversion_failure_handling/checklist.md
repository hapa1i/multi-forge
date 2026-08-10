# Proxy conversion failure handling checklist

Current focus: review and merge verified D053; keep O007 parked until then.

- [x] Review and merge the bounded admission record (PR #160, `cf77c175`).
- [x] Activate this epic and D053 from merged `main` on `fix/sanitize-proxy-conversion-failure-logs`.
- [x] Retain D053's fail-first non-streaming and streaming log-hygiene regressions.
- [x] Replace provider-controlled exception rendering with safe exception-class metadata only.
- [x] Preserve D053's non-streaming fallback, streaming wire, lifecycle, callback, and raw opt-in controls.
- [x] Run focused converter tests, the unit and regression suites, targeted translated-proxy Docker integration, and
  pre-commit.
- [ ] Review and merge D053 independently before activating O007.
- [ ] Activate, implement, verify, review, and merge O007 on its own execution branch.
- [ ] Synchronize the ledger and member paths, then close this epic after both members ship.
