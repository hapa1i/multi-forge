# Claude policy feedback permissions checklist

## Current focus

Paused on 2026-10-15 after the user chose to skip paid native testing and keep PR #269 in draft.

Execution started 2026-10-14 on `codex/claude-policy-feedback-permissions`, based on `main` at `f7ce7a9a`, in a separate
managed worktree. This is A2's independent prerequisite; it does not add Jev behavior or change the epic's membership.
The [card](card.md) owns the acceptance contract. [PR #269](https://github.com/hapa1i/multi-forge/pull/269) is open in
draft. On 2026-10-15 the user chose to skip paid native testing and keep the PR in draft. Native receipt remains
unverified; no native inference has run.

## Response and fixtures

- [x] Verify the shared Claude responder emits unconditional `permissionDecision: "allow"` and that all allowed
  policy-summary paths use it, including ordinary deterministic policies.
- [x] Remove that field while retaining `hookEventName` and `additionalContext`. Keep block exits and feedback-off
  behavior unchanged; do not replace approval with `ask`, `defer` or another permission decision.
- [x] Pass focused responder/feedback tests and the 20-case regression matrix for Write/Edit, injected
  clean/warning/unavailable/deny/unresolved-review outcomes, and feedback on/off. Verify operator output and audit. The
  matrix mocks engine results and does not cover individual policy evaluation or supervisor registration.
- [x] Pass fixture-backed hook integrations through `./scripts/test-integration.sh`; assert emitted context and absence
  of native permission approval on a real hook subprocess. This proves serialization, not model receipt.

## Native receipt and permissions

- [x] Read the local CLI version/help without inference: Claude Code `2.1.296` on 2026-10-14.
- [x] Prepare synthetic Write/Edit inputs, isolated configuration and hook capture under `evidence/`. Record selected
  authentication/billing route, model, exact commands, turn/tool limits, wall deadline and cleanup ownership.
- [x] Record the user decision: skip paid native testing and keep PR #269 in draft (2026-10-15). Do not run the prepared
  trial or substitute another paid/native route. A later trial requires a new explicit request and approval.
- [ ] Observe default-mode permission handling and model receipt of an authored marker in `additionalContext`, without
  explicit hook approval. Use an explicit allow rule/mode as a control; bypass mode cannot prove default permissions.
- [ ] Compare feedback off: absent model context, retained diagnostics/audit and unchanged native permission behavior.
- [ ] Record failures and runtime limitations. Never restore blanket approval to make a trial pass.

## Verification and closeout

- [x] Sync workflow/session-execution design and end-user policy guidance, explicitly describing the changed permission
  behavior for existing policy users.
- [ ] Add the change-log entry when verified and merged.
- [x] Pass aggregate unit, regression, full pre-commit, board/link and file-size checks on this branch.
- [x] Open the separate PR with passing checks and any native-evidence gap visible. Keep it unmerged until acceptance is
  satisfied. Attach the PR to this task.
- [ ] After merge, record the final head and native evidence, move the card to `done/`, repoint links and reconcile A2's
  references. A2 must consume this card from its independent branch and retain one board state when integrating it.

## Execution evidence

2026-10-14: focused responder/feedback tests and the new permission regression matrix passed 110 tests. The first run
exposed an incorrect test expectation for unresolved review: the hook correctly retains its existing standard review
message rather than the fixture's violation text. The assertion was corrected; the blocking behavior was not changed.
The original 60-case matrix repeated the same mocked path under three policy IDs; its supervisor label did not establish
supervisor registration or evaluation coverage. The 2026-10-15 review correction removes that redundant dimension.

`PYTHON_DOTENV_DISABLED=1 ./scripts/test-integration.sh tests/integration/docker/test_policy_hooks.py` passed all 28
tests, including emitted context without a native permission decision in an actual hook subprocess. The harness warned
that `GEMINI_API_KEY` was absent; these injected policy tests need no provider key and passed without it. No inference
was run. Native receipt and permission evidence remain pending.

The [native trial plan](evidence/native-plan.md) and [exact manifest](evidence/native-manifest.json) are prepared. The
driver passed 16 offline tests, including refusal of altered manifests, synthetic output/permission validation, separate
homes, redacted saved output and stopping/reaping after a timeout or native failure. These fixtures do not claim a
native result. The user subsequently chose to skip the eight-case API trial; the evidence gate remains open.

Implementation commit: `a281be33`. Aggregate verification passed: `make test-unit` (10,923 passed; 117 integration tests
deselected), `make test-regression` (1,914 passed), full `make pre-commit` and both staged/working-tree
`git diff --check`. The final driver-specific run passed all 16 tests. Full pre-commit initially caught formatter
changes and a stale provider token count for the edited workflow design; formatting and the required cache refresh
resolved both. The Markdown link check initially ran before the new card was staged; it passed against the final
candidate Git state.

2026-10-15 review corrections: moved the Claude feedback paragraph from Codex Stop to Hook handlers and documented the
Read-hygiene input-correction exception, including its lack of installation ownership checks. The simplified matrix
contains 20 distinct tool/outcome/feedback combinations. Focused verification passed 54 tests:

- `uv run pytest tests/src/cli/hooks/test_policy_feedback.py tests/regression/test_bug_claude_policy_feedback_permissions.py -q`:
  46 passed.
- `uv run pytest tests/src/cli/hooks/test_responder.py -q`: eight passed.

This update changes documentation and tests only. The production responder and native-trial manifest are unchanged; no
native inference ran, and the native evidence gate remains open.
