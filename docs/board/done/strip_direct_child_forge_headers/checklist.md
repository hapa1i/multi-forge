# Strip inherited Forge headers checklist

Current focus: closed after PR #164 (`26ab5f29`).

- [x] Activate D020 from merged `main` on `agent/d020-inherited-forge-headers`.
- [x] Add a marked regression proving a direct child retains inherited Forge-owned headers on merged `main`; the
  targeted run failed because all four stale Forge-owned lines remained (`1 failed`).
- [x] Move inherited-header filtering before the proven-proxy gate.
- [x] Preserve unrelated user headers and malformed unrelated lines.
- [x] Preserve fresh run/root/session/command headers for proven Forge proxies.
- [x] Run the focused reactive-env unit and D020 regression tests (`85 passed`), including the review-added
  all-Forge-lines-to-absent-variable case.
- [x] Run `make test-regression` (`727 passed`) and the targeted proxy-correlation integration canary (`6 passed`).
- [x] Run `make pre-commit` after its expected mdformat normalization pass.
- [x] Run final board integrity checks (284 files, 719 relative links, 12 changed-file fragments, and the 12-member lane
  graph pass).
- [x] Record implementation outcome, verification, and deferred boundaries.
- [x] Open independent draft PR #164 without activating the next Wave 6 member.
- [x] Complete independent review and merge D020 before activating the next ordered member (PR #164, `26ab5f29`).
