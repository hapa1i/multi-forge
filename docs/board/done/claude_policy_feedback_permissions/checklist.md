# Claude policy feedback permissions checklist

## Final status

[PR #269](https://github.com/hapa1i/multi-forge/pull/269) merged on 2026-10-15 as `e9c144eb`, from reviewed head
`c9a7a0a5`. The user authorized merge after choosing to skip paid native testing. That instruction superseded the draft
hold; it supplies no native delivery evidence. Native context receipt and permission handling remain unverified, and
A2's native warning-delivery gate stays open. No native inference ran.

Execution started 2026-10-14 on `codex/claude-policy-feedback-permissions`, based on `main` at `f7ce7a9a`, in a separate
managed worktree. This is A2's independent prerequisite; it does not add Jev behavior or change the epic's membership.
The [card](card.md) owns the acceptance contract, with the native trial deferred by the user's merge decision.

## Response and fixtures

- [x] Confirm the original shared Claude responder emitted unconditional `permissionDecision: "allow"` and that all
  allowed policy-summary paths use it, including ordinary deterministic policies.
- [x] Remove that field while retaining `hookEventName` and `additionalContext`. Keep block exits and feedback-off
  behavior unchanged; do not replace approval with `ask`, `defer` or another permission decision.
- [x] Pass focused responder/feedback tests and the 20-case regression matrix for Write/Edit, injected
  clean/warning/unavailable/deny/unresolved-review outcomes, and feedback on/off. Verify operator output and audit. The
  matrix mocks engine results and does not cover individual policy evaluation or supervisor registration.
- [x] Pass fixture-backed hook integrations through `./scripts/test-integration.sh`; assert emitted context and absence
  of native permission approval on a real hook subprocess. This proves serialization, not model receipt.

## Native receipt and permissions: deferred

- [x] Read the local CLI version/help without inference: Claude Code `2.1.296` on 2026-10-14.
- [x] Prepare synthetic Write/Edit inputs, isolated configuration and hook capture under `evidence/`. Record selected
  authentication/billing route, model, exact commands, turn/tool limits, wall deadline and cleanup ownership.
- [x] Record both user decisions on 2026-10-15: skip paid native testing, then merge PR #269. The latter supersedes the
  draft hold without authorizing the trial or another native route. Any later trial needs its own explicit
  authorization.

The following observations were deferred, not passed:

- Default-mode permission handling and model receipt of an authored `additionalContext` marker without explicit hook
  approval, with an explicit allow rule/mode as a control. Bypass mode cannot prove default permissions.
- Feedback off: absent model context, retained diagnostics/audit and unchanged native permission behavior.
- Native failures and runtime limitations. No native result is available, and blanket approval must not be restored to
  make a later trial pass. A2 owns its remaining native warning-delivery acceptance.

## Verification and closeout

- [x] Sync workflow/session-execution design and end-user policy guidance, explicitly describing the changed permission
  behavior for existing policy users.
- [x] Add the change-log entry with the merge evidence and the deferred native verification made explicit.
- [x] Pass aggregate unit, regression, full pre-commit, board/link and file-size checks on this branch.
- [x] Open the separate PR with passing checks and the native-evidence gap visible; merge only after the user's explicit
  instruction to proceed with that gap. Attach the PR to this task.
- [x] Record the final head and native-evidence limit, move the card to `done/` and repoint merged-tree inbound links.
  A2's separate branch must consume the merged card without recreating the former paused copy; its native gate remains
  separate from this implementation closeout.

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

## Merged closeout

2026-10-15: PR #269 merged as `e9c144ebbb0c873086041b40a498f91f26d1ca8e` from reviewed head
`c9a7a0a5b13bf7be96275811c22edeae4dda7dd0`. The merge tree matches the reviewed head. GitHub's pre-commit, test and both
CodeQL analysis checks passed; the aggregate CodeQL result was neutral and accepted by the check summary.

The user authorized merge with native verification still skipped. The shared responder, policy output and audit paths
have fixture evidence; actual native context receipt and permission handling are unverified. The retained trial is an
unexecuted proposal, and this closeout authorizes no inference or additional data sharing. A2 still needs its native
warning-delivery evidence.

Moved this card to `done/`, updated the design link and change log, and preserved the exact native manifest. Closeout
verification uses Markdown, link, file-size and whitespace checks; no runtime behavior changed after the reviewed head.
