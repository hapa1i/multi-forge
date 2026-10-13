# Execution checklist

Base: `2ec4a22a`. Branch: `codex/gemini-4-argon`. Scope: Gemini Argon catalog/default adoption.

- [x] Create a separate worktree from freshly fetched main.
- [x] Verify public model identity, context/output limits, thinking and sampling controls.
- [x] Add catalog aliases, model routes and workflow selection while retaining explicit older models.
- [x] Promote fresh Gemini Sonnet/Opus templates and verify native adapter support.
- [x] Preserve saved proxy/backend snapshots and document opt-in migration.
- [x] Run focused model/routing/accounting checks and targeted Docker integration.
- [x] Build wheel/sdist and verify packaged resources from an isolated install.
- [x] Reproduce and fix local Pro routing with only `GEMINI_API_KEY`.
- [x] Run the keyed session-routing integration tests and verify truncation over HTTP.
- [x] Verify fresh and saved backend readiness, snapshot preservation, and explicit migration.
- [x] Run `--available`, Codex preflight, and native/mixed/Argon workflow panels.
- [x] Run final full pre-commit and aggregate checks after review fixes.
- [x] Review/merge and record closeout before moving to done.

## Evidence

Commands requiring credentials used `direnv exec /Users/habib/workspace/multi-forge` from the isolated worktree. The
first PR integration run did not load that environment; it did not establish live Gemini compatibility.

- The real route planner reproduced six failures with only `GEMINI_API_KEY`. Seven regression cases now pass for Argon,
  3.1 Pro, 2.5 Pro, explicit Opus selection, and unchanged Flash priority.
- `PYTHON_DOTENV_DISABLED=1 ./scripts/test-integration.sh tests/integration/proxy/test_session_routing_e2e.py -q --tb=short`
  reproduced both stale 3.1 Pro assertions: two failed, five passed. After correction, the same file plus
  `tests/integration/proxy/test_finish_reason_e2e.py` passed all 11 tests with the Gemini credential loaded. The four
  hermetic cutoff cases exercise unary/streaming text and partial tools through a real proxy subprocess.
- `PYTHON_DOTENV_DISABLED=1 ./scripts/test-integration.sh tests/integration/cli/test_workflow_integration.py -q --tb=short`:
  12 passed, covering Docker worker launch and workflow wiring.
- An isolated `FORGE_HOME` with real LiteLLM verified fresh Argon readiness and a successful Argon panel. A saved
  backend without either Argon deployment was absent from `workflow list-models --available --json`; its panel failed
  before worker launch with migration guidance. Adding complete deployments without restart remained unavailable.
  Restarting the backend restored readiness and a successful Argon panel through the unchanged older proxy tiers.
  Read/start checks preserved backend and proxy bytes, mode, and mtime; cleanup stopped both owned processes.
- `forge runtime preflight codex --json`: ready with ChatGPT authentication. Codex 0.162.1 is newer than Forge's
  validated 0.161.0 version, reported as a non-blocking doctor warning.
- `forge workflow panel -p "<termination-invariant review>" -m codex --context blind --timeout 90 --json`: one worker
  succeeded. The corresponding `-m claude-opus,codex --effort low` run succeeded for both workers.
- Termination/core-client checks: 312 passed. Responses `content_filter` and token exhaustion retain distinct stop
  reasons; an independent rerun of the termination regressions passed all 36 cases.
- Readiness/routing checks: 313 passed, including exact/wildcard deployments, failed inventories, API path prefixes,
  per-invocation caching, saved-file preservation, and sidecar compatibility. Documentation cache checks: 49 passed.
- `make test-unit`: 10,804 passed, 117 integration tests deselected. `make test-regression`: 1,727 passed.
- `make pre-commit`: passed after applying formatter changes and correcting two new mypy typing issues. A final focused
  run after those type-only changes passed all 49 termination/readiness regressions.
- `make build`: passed. The clean wheel verified packaged Argon resources and LiteLLM start/health/stop. Its first
  attempt exceeded the existing ten-second backend startup health timeout while aggregate suites were running; a clean
  retry after those suites finished passed without runtime changes. Dependencies remain unchanged. The earlier offline
  actual-LiteLLM pipeline covered 18 alias/effort/streaming combinations.

## Merged closeout

[PR #267](https://github.com/hapa1i/multi-forge/pull/267) merged into `main` on October 13, 2026 as `42c150b7`. All five
PR checks passed. PR #266 preceded the merge, so the merged tree includes additional changes beyond tested Argon head
`d036a368`.

- [x] Recheck merged main: 300 focused catalog, local-route, session-planner, native-thinking, Vertex-limit,
  termination, workflow-model, and backend-readiness tests passed after `make deps`.
- [x] Verify the runtime design and proxy/workflow guides describe shipped defaults, saved-config migration, loaded
  deployment checks, and cutoff reporting.
- [x] Record the completed change and promote the reviewed route/readiness/termination lessons to the runtime ledger.
- [x] Move the card and checklist to `done/`; no pre-existing inbound links required repointing.
- [x] Run closeout checks on `main`: `make pre-commit-md`, the 670-source Markdown link audit, file limits, lane
  assertions, and staged/unstaged diff checks passed.
