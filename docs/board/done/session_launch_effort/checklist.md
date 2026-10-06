# Session launch effort implementation checklist

**Branch**: `feat/session-launch-effort` · **Base**: `origin/main` · **Card**: `card.md`

## Current focus

Completed 2026-10-06. [PR #257](https://github.com/hapa1i/multi-forge/pull/257) merged to `main` as `845811c2`; its tree
matches verified head `54f320cf`, with all five GitHub checks passing.

## Evidence gathered

- Claude Code 2.1.289 accepts `--effort low|medium|high|xhigh|max` interactively and sends `output_config.effort` for
  Claude and non-Claude model names (default `medium` for Opus/Sonnet 5.5, `high` for unknown names).
- Codex 0.160 accepts `-c model_reasoning_effort=...` on the TUI, `resume`, and `exec`, and passes any string upstream
  without local validation.
- The translated proxy drops `output_config`; Anthropic passthrough forwards only allowlisted request headers.

## Shared launch arguments

- [x] Add a runtime launch-argument value object with per-runtime effort validation, reserved-flag rejection, advisory
  refusal, and argv projection (`core/runtime/launch_args.py`).
- [x] Split `--` before Click parsing so the optional session-name positional cannot capture runtime arguments
  (`cli/session_launch_args.py`).

## Claude launches

- [x] Wire `--effort` and passthrough through start, incognito, resume (all six modes), and fork.
- [x] Validate before any session, child, worktree, or proxy mutation against the launched session's effective
  authority; the authority transaction revalidates the locked manifest before launch events or active registration.
- [x] Reproduce effort and passthrough in route-recovery commands, including the persisted-proxy preflight refusal.
- [x] Refuse `--no-launch` with launch args before route realization.

## Codex launches

- [x] Wire effort and passthrough through interactive start/reattach and headless start/continue argv builders; ops
  validate inherited advisory authority before preflight or session creation.

## Translated proxy effort

- [x] Stamp `X-Forge-Effort-Source: client` for `--effort` proxy launches (host and sidecar) and scrub it from headless
  children.
- [x] Honor `output_config.effort` only under the header; preserve `between_tools`/`disabled` behavior; clamp.
- [x] Warn at launch when a selected translated route model cannot express the requested effort.

## Review fixes

- [x] Refuse passthrough if authority changes to advisory between the early validation and the launch lock, across
  Claude and Codex interactive/headless entrypoints; record no launch events or active registration on refusal.
- [x] Reserve runtime worktree flags, Codex `--yolo`, alternate provider/remote controls, and `--ephemeral`.
- [x] Send effort-clamp diagnostics to stderr and keep stdout clean.
- [x] Add regression coverage for all three findings; each regression failed before its fix.

## Documentation

- [x] Update CLI reference, end-user session/proxy guides, `design.md` §3.4, and the workflow effort note; refresh the
  provider token cache for changed docs.

## Test-client warning follow-up

- [x] Require Starlette `>=1.7.0,<1.8`, which includes the upstream AnyIO `BlockingPortal` fix; retain the existing
  FastAPI, AnyIO, and LiteLLM lock versions.
- [x] Reproduce the import warning in a fresh-interpreter regression, then pass 73 HTTP-client tests with deprecation
  warnings treated as errors after the upgrade.
- [x] Build the wheel/sdist and pass the clean-wheel LiteLLM start/health/stop smoke outside `uv.lock`.
- [x] Pass seven proxy integration checks covering health, translated and passthrough requests, streaming, request IDs,
  and error headers via `./scripts/test-integration.sh`.
- [x] Full unit and regression suites pass without warnings; full pre-commit and hooks on the new regression pass.

## Acceptance tests

| Test                 | Fixture                       | Assertion                                                       | Test File                                                         |
| -------------------- | ----------------------------- | --------------------------------------------------------------- | ----------------------------------------------------------------- |
| Launch-arg model     | Pure values                   | Vocabulary, reserved flags, advisory refusal, argv projection   | `tests/src/core/runtime/test_launch_args.py`                      |
| Passthrough parsing  | CliRunner                     | `start -- --debug` keeps the name unset and forwards `--debug`  | `tests/src/cli/test_session_launch_args.py`                       |
| Pre-mutation refusal | CliRunner + mocked manager    | Resume/fork advisory and reserved-flag refusals mutate nothing  | `tests/src/cli/test_session_launch_args.py`                       |
| Recovery commands    | Pure values                   | Effort before `--proxy`; passthrough after `--`                 | `tests/src/cli/test_session_launch_args.py`                       |
| Ops backstop         | Store + fake invoker          | Advisory passthrough refused with no authority event            | `tests/src/core/ops/test_claude_session.py`                       |
| Sidecar opt-in       | Patched sidecar runner        | Effort argv and header reach the container only with `--effort` | `tests/src/core/ops/test_claude_sidecar_launch.py`                |
| Translated effort    | Request stub + tier overrides | Header-gated client effort beats floor; no header is unchanged  | `tests/src/proxy/test_reasoning_effort.py`                        |
| Handler opt-in       | Stubbed `create_message`      | Header changes upstream `reasoning_effort`; no `output_config`  | `tests/src/proxy/test_server_model_resolution.py`                 |
| Header hygiene       | Env builder                   | Interactive proxy launch stamps the header; children scrub it   | `tests/src/core/reactive/test_env.py`, `test_claude_invoke.py`    |
| Codex argv           | Invoker builders              | Options precede positional prompt, thread id, and `resume`      | `tests/src/session/test_codex_invoke.py`, `test_codex_invoker.py` |
| Codex op refusal     | Project fixture               | Advisory parent refuses passthrough before preflight/creation   | `tests/src/core/ops/test_codex_interactive.py`                    |

## Verification and PR

- [x] Focused unit tests pass.
- [x] Initial integration tests: session commands, resume-proxy, Claude command, Codex session start, session routing,
  run-id correlation, passthrough headers, sidecar runtime, and sidecar hook injection pass (77 passed).
  `test_claude_to_codex_resume.py` fails at its Codex preflight because the test container has no `CODEX_API_KEY`.
- [x] Review-fix integration run: session commands, Claude command, session routing, Codex session start/resume, and
  real Claude/Codex authority tests pass (57 passed via `./scripts/test-integration.sh`). Codex preflight also passes
  with the integration runner's environment loaded.
- [x] `make test-unit` (10,539 passed) and `make test-regression` (1,331 passed), including all 15 launch-argument
  regression cases and the TestClient deprecation regression.
- [x] `make pre-commit` on the final tree (plus hooks on the untracked card and new files).
- [x] Commit, push, and open [PR #257](https://github.com/hapa1i/multi-forge/pull/257) with verification evidence.

## Closeout

- [x] Confirm the merge tree matches the tested PR head and all GitHub checks passed.
- [x] Verify the CLI reference, design/session/workflow docs, and end-user session/proxy guides describe the shipped
  launch-only arguments, authority validation, and translated effort behavior.
- [x] Record the completed work in the board change log and retain the reviewed authority-lock and effort opt-in
  invariants in the session and runtime implementation notes.
- [x] Move the card and checklist to `done/session_launch_effort/`; no inbound repository links used the old lane.
- [x] `make pre-commit-md` passes, including file-size checks; the repository link audit passes for all 620 Markdown
  sources. Refreshed provider token counts for the changed board ledgers.
