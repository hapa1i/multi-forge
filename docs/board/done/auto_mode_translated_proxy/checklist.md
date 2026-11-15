# Auto mode on translated proxies execution

Shipped on `main` November 15, 2026 via [PR #299](https://github.com/hapa1i/multi-forge/pull/299) (`f10a66d3`).

## Implementation

- [x] Add `apply_auto_mode_server_policy`: known translated shapes get `CLAUDE_CODE_AUTO_MODE_SERVER=0` plus the
  `FORGE_AUTO_MODE_SERVER_MANAGED` marker; unmarked values stay user-owned; direct, passthrough, and unknown shapes drop
  a marked `0`.
- [x] Apply the policy in `build_claude_env`, in the interactive builder after `unset_vars`, and in the sidecar
  launcher, which carries a host user value into the container.
- [x] Record the predicted classifier request model on `ClaudeLaunchReady` and print one stderr notice from the session
  presenters and bare `forge claude start`, naming the backend through read-side route prediction.
- [x] Classify the marker in the env vocabulary and update the proxy, session, config, runtime, and installation docs.

## Verification

| Check                   | Fixture                                                           | Assertion                                                              | Test File                                                               |
| ----------------------- | ----------------------------------------------------------------- | ---------------------------------------------------------------------- | ----------------------------------------------------------------------- |
| Translated launch       | Managed session on translated and Responses-capable saved proxies | Child env has `0`; event predicts `claude-sonnet-5`                    | `tests/regression/test_bug_auto_mode_translated_proxy_server_review.py` |
| Passthrough and nesting | Passthrough proxy; direct launch inheriting Forge's marked `0`    | No auto-mode server value reaches the child                            | same regression file                                                    |
| Ownership               | User `0`/`1`, user-changed marked value, unknown wire shape       | User values kept; unknown shapes untouched; policy idempotent          | `tests/src/core/reactive/test_env.py`                                   |
| Sidecar                 | Translated and passthrough templates; host user value             | `-e` flags carry Forge's default or the host value only                | `tests/src/sidecar/test_container.py`                                   |
| Notice                  | Runtime snapshots with tier maps, alternatives, other proxy       | One stderr line names the backend; mismatched snapshot not trusted     | `tests/src/cli/test_auto_mode_notice.py`                                |
| Docker launch path      | Real translated proxy, mock `claude`, isolated home               | Bare and session launches get `0`; user `1` survives; nesting drops it | `tests/integration/cli/test_auto_mode_launch_integration.py`            |

- [x] Confirm the regression fails without the policy (both translated cases fail; passthrough and nesting pass).
- [x] Run focused, aggregate unit/regression suites and targeted Docker integration tests.
- [x] Run `make pre-commit` on the final tree.

## Review follow-up

- [x] Sidecars forward a host `CLAUDE_CODE_AUTO_MODE_MODEL`, and the sidecar notice predicts from it.
- [x] `build_claude_env` re-resolves the wire shape when it replaces the endpoint without a caller-supplied shape, from
  that URL's subprocess metadata or registry entry only, and both policies use that one result. Bare and session launch
  builders scrub an inherited shape when the selected proxy's shape is unknown. Attribution had the same defect.
- [x] Classifier prediction applies the Sonnet 4.6 session-model rule from `--model` or `ANTHROPIC_MODEL`.
- [x] Regression `tests/regression/test_bug_subprocess_route_stale_wire_shape.py` fails both directions on the prior
  `env.py`; unit tests cover caller-owned shapes, unchanged routes, unresolvable routes, and subprocess fallback.

## Closeout

- [x] Open the PR; GitHub Tests (3.11, 3.13), test-selection comparison, Pre-commit, and CodeQL passed on `dbf341aa`.
- [x] Squash-merge, record shipped closeout and the change log entry, and move the card to `done/`.

## Evidence and limits

- Fake-endpoint probes of Claude Code 2.1.325: the default run sent `safeguards` and logged `server_no_result`. With
  `CLAUDE_CODE_AUTO_MODE_SERVER=0`, alone or with `CLAUDE_CODE_ATTRIBUTION_HEADER=0`, no `safeguards` were sent and 10
  local classifier requests used `claude-sonnet-5`. `CLAUDE_CODE_AUTO_MODE_MODEL=anthropic/claude-sonnet-5` produced
  that exact wire model.
- Stub-`claude` launch against the live `slate-lime` proxy (`GET /` only): the child received the managed `0`; stderr
  named `google/gemini-4-carbon (requested as claude-sonnet-5, sonnet tier)`.
- `./scripts/test-integration.sh tests/integration/cli/test_auto_mode_launch_integration.py tests/integration/cli/test_claude_command_integration.py`:
  5 passed, rerun after the presenter consolidation.
- `make test-unit`: 11,689 passed after refreshing four stale provider token counts; the first run failed only the token
  cache check. `make test-regression`: 2,531 passed. `make pre-commit` passed after formatter rewrites and after routing
  both presenter notices through one call, which keeps `session_lifecycle.py` at its 2,499-line baseline.
- Not exercised live: a paid interactive auto-mode session through a translated proxy, server review through
  `anthropic_passthrough`, and a real sidecar container launch (the `-e` flags have unit coverage only).
