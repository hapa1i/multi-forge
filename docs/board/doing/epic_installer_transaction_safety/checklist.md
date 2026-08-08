# Installer transaction safety checklist

Current focus: merge the independently reviewed D012 implementation; D019 remains parked until then.

## Activation and sequencing

- [x] Merge the Wave 4 admission record (PR #143, `afde43bf`).
- [x] Start `fix/rollback-codex-install-transaction` from merged `main`.
- [x] Move this epic and D013/D014 to `doing/`, create their checklists, and repoint inbound links.
- [x] Retain a marked D013/D014 regression that fails on the merged baseline before implementation.
- [x] Implement and verify D013/D014 without activating D012 or D019.
- [x] Independently review D013/D014 (2026-08-08; no design violations).
- [x] Merge D013/D014 before moving D012 from `todo/` (PR #144, `37a03209`).
- [x] Start `fix/preserve-install-settings-baseline`, move D012 to `doing/`, and create its checklist.
- [x] Independently review D012 and resolve its LOW tracked-baseline deletion race.

## Remaining members

- [ ] Ship D012 immutable pre-Forge settings-baseline ownership (active).
- [ ] Ship D019 value-aware legacy scalar/environment removal.

## Closeout

- [ ] Keep the review ledger, member paths, and parent epic cursor current after each merge.
- [ ] Close this epic only after all three independently reviewed members ship with their required regression, Docker,
  and clean-wheel coverage.
