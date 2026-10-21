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
- [ ] After merge, verify the default-branch alerts, record closeout and move the card to done.
