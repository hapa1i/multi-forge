# November dependency security checklist

**Branch**: `codex/fix-dependabot-oauthlib-pyasn1` · **Base**: `main` (`fd6e57e8`) · **Card**: [card.md](card.md)

## Current focus

Implementation and verification are complete. The candidate graph addresses all six open alerts; the card remains active
until the separate security PR is merged and Dependabot confirms closure.

## Implementation

- [x] Read all six alerts and trace both packages through the reviewed lock.
- [x] Verify there are no running managed host proxies or local backends to stop before the update.
- [x] Reproduce outdated security floors with regression expectations: both new expectations failed before the fix.
- [x] Update declarations, lock, and generated runtime constraints without unrelated package changes.
- [x] Validate source-only pyasn1 scope and the packaged OAuthLib floor.

## Acceptance

| Check           | Assertion                                                                                                    | Evidence                               |
| --------------- | ------------------------------------------------------------------------------------------------------------ | -------------------------------------- |
| Security floors | Installed wheel metadata requires OAuthLib 4.0.1+; provider-check constraints and lock require pyasn1 0.6.5+ | Dependency floor regressions           |
| Graph ownership | Only the two affected package versions change; pyasn1 stays outside the runtime export                       | Lock comparison and dependency checker |
| Runtime         | Clean wheel and rebuilt image layers load patched OAuthLib and start the existing LiteLLM runtime            | Wheel smoke and targeted integration   |

## Verification

- [x] Full unit and regression suites.
- [x] Build, clean installed-wheel/runtime smoke, and optional provider-check dependency smoke.
- [x] Rebuilt Docker base/sidecar images and targeted local backend integration.
- [x] Full pre-commit, board/link, file-size, and diff checks.
- [x] Prepare advisory coverage and verification evidence for the separate PR.

## Verification evidence

- Both security-floor regressions failed against the previous declarations; the focused floor/export run then passed all
  17 cases. Full `make test-unit test-regression` passed 11,624 unit tests and 2,471 regressions.
- The lock diff changes only OAuthLib 4.0.0 -> 4.0.1 and pyasn1 0.6.4 -> 0.6.5. The runtime export changes only
  OAuthLib; build inputs are unchanged. An automated comparison against refreshed alerts 63-68 confirms every selected
  version is outside its advisory's vulnerable range.
- `make build` produced the wheel and sdist. Reading the wheel's `Requires-Dist` verified `oauthlib>=4.0.1,<5` and no
  direct pyasn1 runtime dependency. `./scripts/test-wheel-runtime.sh` passed its clean hash-checked install, LiteLLM
  start/health, and process-group teardown with final exit status zero.
- An isolated `uv run --locked --isolated --only-group provider-check` smoke imported google-auth/google-genai, verified
  pyasn1 0.6.5, and decoded a small DER value without provider calls.
- `./scripts/test-integration.sh` passed 15 cases across backend CLI, proxy/backend ownership, local LiteLLM proxy
  health, and detached-process teardown. It rebuilt `forge-claude-test:2.1.245-codex-0.167.0` and
  `forge-sidecar:latest`. Both images then imported OAuthLib, fastapi-sso, and the LiteLLM proxy with `--network none`
  and reported OAuthLib 4.0.1. LiteLLM's remote metadata lookup warned and used its local fallback in those offline
  imports; both exited zero.
- `make pre-commit` passed after formatting the new board files. No live model inference ran.

## Closeout

- [ ] After merge, verify alerts close, record shipped evidence, and move the card to `done/`.
