# Real-runtime authority E2E execution checklist

Closeout: shipped in [PR #235](https://github.com/hapa1i/multi-forge/pull/235) (merge `8e47f017`) and moved to `done/`
on 2026-08-22.

**Card**: [card.md](card.md). **Branch**: `test/authority-real-runtime-e2e`, based on `main` at `5dfec4c2`.

## Current focus

The validation shipped via PR #235 and this checklist retains its execution evidence. Both runtimes execute inside the
disposable integration container. Codex receives only an ephemeral API credential and the two non-secret trusted hook
hashes recreated at their original absolute paths; host auth/config files remain untouched.

## Phase 1 -- Real Claude through Forge launch

- [x] Add a dedicated slow Docker test module with a hard `ANTHROPIC_API_KEY` prerequisite.
- [x] Install a temporary PATH-scoped passthrough wrapper that preserves Forge's argv/environment, adds one fixed
  `--print` tool task, logs marker presence without logging marker contents, and leaves the real executable untouched.
- [x] Prove an advisory `Bash` request is denied: sentinel absent, marker present at the child, same-run
  `request_denied`, and complete launch lifecycle.
- [x] Prove the producer control is not denied: sentinel content present, marker absent at the child, complete launch
  lifecycle, and no `request_denied`.

Evidence (2026-08-22): the two real-Claude cases passed together in 30.39 s against Claude Code 2.1.238. The advisory
model requested `Bash`; the sentinel stayed absent and the journal carried a same-run denial. The producer model wrote
the expected sentinel with no marker or denial event.

## Phase 2 -- Real Codex through Forge launch

- [x] Version the Docker test image by both host-selected Claude and Codex CLI versions and install the real Codex
  binary in its cached toolchain layer.
- [x] Recreate only the enrolled SessionStart/PreToolUse hash records at the same absolute config path, let
  `forge extension enable` install the exact hook rows and dispatcher, and never copy `auth.json`.
- [x] Start an advisory Codex session through the public CLI with `workspace-write`, a structured fixture parent, and an
  explicit `apply_patch` task; do not patch enrollment, marker construction, invocation, or hooks.
- [x] Assert the sentinel remains absent and at least one same-run `request_denied` sits between `run_started` and
  `run_ended`.
- [x] Fail with actionable setup guidance when the user registration or empirical enrollment prerequisite is absent.

Evidence (2026-08-22): the real-Codex case passed in 23.67 s against Codex CLI 0.149.0. Forge's required empirical
SessionStart probe ran before the marked launch; the model then requested `apply_patch`, the sentinel stayed absent, and
the launch journal recorded the same-run denial and terminal event.

## Acceptance tests

| Test                         | Fixture                                                                      | Assertion                                                                                | Test file                                         |
| ---------------------------- | ---------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------- | ------------------------------------------------- |
| Real Claude advisory denial  | Docker image, real Claude, API key, user hooks                               | marker reaches child; real `Bash` request is denied; sentinel absent; journal correlated | `tests/integration/docker/test_real_authority.py` |
| Real Claude producer control | Docker image, real Claude, API key, user hooks                               | no marker; real `Bash` request writes sentinel; no denial event                          | `tests/integration/docker/test_real_authority.py` |
| Real Codex advisory denial   | Docker image, real Codex, API key, path-faithful non-secret enrollment state | real `apply_patch` request is denied; sentinel absent; journal correlated                | `tests/integration/docker/test_real_authority.py` |

## Phase 3 -- Verification and closeout

- [x] Run the new real-Claude Docker cases through `./scripts/test-integration.sh` (2 passed).
- [x] Run the new real-Codex Docker case through `./scripts/test-integration.sh` (1 passed); record any external
  prerequisite failure exactly and do not substitute a mocked pass.
- [x] Run the existing authority Docker/lifecycle cases (8 passed), focused authority unit suites (207 passed),
  `make test-unit` (9,447 passed, 117 deselected), and `make test-regression` (1,056 passed after review repairs).
- [x] Run `make pre-commit`, `git diff --check`, and a relative Markdown-link sweep (1,227 links across 453 files).
- [x] Add a compact completed-work entry to `docs/board/change_log.md`; design and end-user docs remain unchanged
  because this card adds validation only.
- [x] Commit, push the separate branch, and open a PR with real-model cost/prerequisite disclosure and exact evidence.
- [x] After merge, move this card `doing/ -> done/` and repoint inbound board links. PR #235 merged as `8e47f017`; the
  card moved to `done/` on 2026-08-22, and no inbound board links required changes.

## Review repair

- [x] Keep the bundled QA runner on the same Claude/Codex-versioned image identity and build arguments as the canonical
  integration runner; pin the three surfaces with regression coverage.
- [x] Make the installer absence test establish a Claude-present/Codex-absent PATH instead of depending on base-image
  contents.
- [x] Accept additional correctly denied Claude retries, clear the marker probe around each launch, and bound the real
  Codex command with an in-container timeout.
- [x] Stream fixture file content over `docker exec -i`, publish through an atomic same-directory temporary file, and
  use mode `0600` for all real-runtime credentials and prompts.

Evidence (2026-08-22): 3 real-model authority cases passed in 46.73 s; the canonical integration runner collected and
passed all 13 Docker file-helper cases after their integration marker was added; the 32-case proxy/Claude/installer
regression cluster passed; the pre-marker complete non-slow integration target passed with 437 tests and 10,615
deselections in 10m17s; 9,447 unit tests passed with 117 deselections; 1,057 regression tests passed; full pre-commit,
diff checks, and all five GitHub checks passed.
