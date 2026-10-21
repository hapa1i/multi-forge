# Dependency security checklist

- [x] Read all open alerts and normalize package names without losing advisory identities.
- [x] Trace runtime and development dependency paths; verify patched releases and parent constraints.
- [x] Add failing distribution-metadata regressions before raising packaged runtime floors.
- [x] Raise floors and resolve the lock while preserving unrelated compatibility constraints.
- [x] Audit the complete lock and include the six additional certifi/virtualenv advisories.
- [x] Verify every captured affected range against the resolved lock; repeat the full dependency audit.
- [x] Verify OAuthlib client compatibility locally and the focused metadata regressions.
- [x] Run `make test-regression` with provider credentials and dotenv loading disabled.
- [x] Run `make test` with the same credential isolation.
- [x] Build wheel/sdist and verify a clean wheel's dependency resolution and LiteLLM start/health/stop.
- [x] Run full pre-commit, Markdown links, file limits and diff checks.
- [x] Finish the validation evidence for PR review.
- [x] After merge, verify the default-branch alerts, record closeout and move the card to done.

## Merged closeout

[PR #279](https://github.com/hapa1i/multi-forge/pull/279) merged as `93b558d2` on 2026-10-22 (Europe/Berlin). Its tree
matches reviewed head `c33c3529`; all five GitHub checks passed. The card moves to `done/`, with both advisory JSON
snapshots preserved unchanged and a completed-work entry in the change log. No inbound repository links required
repointing. Dependency ownership and installation workflows are unchanged, so no design or end-user contract update is
outstanding.

Pre-merge validation passed `make test` (11,138 unit and 523 integration tests), `make test-regression` (2,091 tests),
full pre-commit, build, a Python 3.11 clean-wheel runtime check and a disposable virtualenv seed/launcher check. The
[verification record](evidence/verification.md) preserves the initial watchdog timeout failure and passing reruns. The
complete lock audit checked all 126 third-party packages, with zero known vulnerabilities and no skipped packages.

GitHub's [post-merge snapshot](evidence/post-merge-status.json) reports the patched dependency-graph versions for all
seven affected packages and zero open Dependabot alerts. No alert was dismissed or manually closed during this work. The
repository fix is shipped; existing virtualenvs, old images and custom CA bundles retain the migration limits documented
in the verification record.
