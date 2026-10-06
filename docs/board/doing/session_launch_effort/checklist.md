# Session launch effort implementation checklist

**Branch**: `feat/session-launch-effort` · **Base**: `origin/main` · **Card**: `card.md`

## Current focus

Review findings addressed and verified; ready for commit and PR.

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
- [x] `make test-unit` (10,539 passed) and `make test-regression` (1,330 passed), including all 15 new regression cases.
- [x] `make pre-commit` on the final tree (plus hooks on the untracked card and new files).
- [ ] Commit, push, and open the PR with verification evidence.
