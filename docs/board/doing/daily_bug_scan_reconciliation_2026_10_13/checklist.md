# Execution checklist

Base: `2ec4a22a`. Branch: `fix/daily-bug-scan-reconciliation-2026-10-13`. Current focus: exact reproductions, minimal
fixes, and integrated verification.

## Implementation

- [x] R1 Gate native readiness on the actual inherited child's enabled policy.
- [x] R2 Empty interrupted turns do not spend review budget; edited work still carries.
- [x] R3 Submodule edits cannot produce falsely complete evidence.
- [x] R4 Oversized patch actions retain bounded evidence and an explicit omission.
- [x] R5 Fresh Codex reviewers cannot write executor observation receipts.
- [x] R6 Fail-closed denied tools leave no impossible Stop outcome obligation.
- [x] L1 Noncanonical raw UUID aliases cannot delete another session's transcript.
- [x] L2 Symlinked encoded Claude project directories cannot authorize external cleanup.
- [x] L3 Codex launch tails cannot replace lifecycle or thread positionals.
- [x] L4 Dedicated compaction snapshots validate before any mutation.
- [x] L5 Sidecar recovery suggests only accepted commands.
- [x] I1 Codex-only installation does not read unrelated Claude settings.
- [x] I2 Sync preserves files with unattributed ownership.
- [x] I3 Invalid Codex config paths fail before ownership mutation.
- [x] I4 Hook migration preserves the original settings baseline.
- [x] I5 Worktree config copying uses confined, exclusive destination creation.
- [x] Q1 Installed QA resolves a validated source checkout independently of skill ancestry.
- [x] Q2 Missing provider profile or required infrastructure cannot produce a release pass.
- [x] Q3 QA selections include step and section prerequisites.
- [x] Q4 Changed credentials/configuration refuse stale container reuse.
- [x] Q5 Certificate changes invalidate runtime-base reuse.
- [x] Q6 Section `.0` range boundaries match existing state semantics.
- [x] D1 Spend-cap coverage points to concrete existing behavior tests.
- [x] D2 Historical Markdown count is corrected from 579 to 581.

## Acceptance

| Area       | Fixture                                       | Assertion                               |
| ---------- | --------------------------------------------- | --------------------------------------- |
| Supervisor | Stub reviewer, real hook/journal              | Correct identity, evidence and spending |
| Lifecycle  | Published sessions, temporary native files    | Retention and pre-mutation refusal      |
| Installer  | Isolated tracking/settings and directory swap | Ownership retained; no escaped copy     |
| QA         | Synthetic wheel, Docker transport fixtures    | Exact source, scope, inputs and verdict |

- [x] Every behavioral fix has a regression that fails on the base and passes with the fix.
- [x] Focused unit/regression checks pass.
- [x] Targeted Docker integrations pass through the standard runner.
- [x] Build wheel/sdist and verify affected packaged behavior in a clean install.
- [x] Aggregate unit/regression checks pass on the integrated head.
- [x] Full pre-commit and board/link checks pass.
- [x] Design and end-user docs match changed contracts.
- [x] Independent final review resolved.
- [ ] Review and merge the single PR with validation and remaining evidence limits.
- [ ] After merge, record closeout and move this card to `done/`.

## Evidence

All reproductions use temporary files, synthetic credentials, or stub reviewers. The API-home race remains a passing
control; no implementation change is attributed to it. Independent review extended the fixes to cover worktree-root
replacement, mixed-case raw cleanup IDs regardless of relocation metadata, and explicit Codex auth-file changes.

- Supervisor: disabled-policy inheritance and actual relaunch; empty versus edited interrupted turns; nested submodule
  edits; a 300-file patch; fresh-reviewer hook isolation; fail-closed denial followed by Stop.
- Lifecycle: raw current/artifact UUID variants with unrelated canonical cleanup controls; symlinked project paths;
  option-aware launch tails; malformed dedicated snapshots; actual start/incognito recovery messages.
- Installer: isolated Codex settings, both sync runtime-selection forms, invalid tracking paths before writes,
  migration/disable restoration, and late source/destination/root swaps through actual copy operations.
- QA: installed driver plus source checkout; incomplete provider evidence; every category's transitive prerequisites;
  `.0` boundaries; environment/auth ingress changes and refreshed-auth preservation; certificate
  addition/rotation/removal.

Initial integrated regression run: 1,718 passed. The first full unit run had 10,774 passes and one stale token-cache
failure. Refreshed the three affected documentation counts. Full hooks also caught and corrected a test type assertion,
formatting, and four excess comment lines in the session manager. Final aggregate results are recorded below.

Live native/provider tests remain outside this verification. An initial integration selection reached the
native-relocate fixture's missing `ANTHROPIC_API_KEY` refusal (35 other tests passed), then was interrupted and rerun
with `-m "integration and not slow"`. This does not establish native quota exhaustion or post-fix live cancellation
behavior.

Clean-wheel candidate: `multi_forge-1.0.2-py3-none-any.whl`, SHA-256
`755fc6b4a213f8a146fb6437a003ed7ce68de5e7a91de65d98481777b09813ca`. `make build` produced wheel and sdist. A fresh venv
resolved 94 packages independently of `uv.lock`; all 580 tests across 35 affected files passed with no skips. Imports
and bundled QA resources came from the wheel, with no checkout Forge source in the harness. Sixteen isolated extension
lifecycle commands passed, including the expected changed-`CODEX_HOME` refusal. QA transport fixtures are model-free;
the venv doctor check does not establish global-tool or minimal-GUI-PATH behavior.

Independent final review replayed the original mixed-case cleanup and explicit-auth reuse probes and confirmed both
refuse the unsafe behavior. Supervisor/lifecycle review found no remaining defect within scope. Submodule checkouts
intentionally retain explicit incomplete evidence instead of claiming complete coverage.

Final integrated checks:

- `make test-unit`: 10,775 passed, 117 integration-marked tests deselected.
- `make test-regression`: 1,728 passed.
- Targeted integration runner below: 56 passed.
- `make pre-commit`: all hooks passed, including formatting, types, security, file limits, and Markdown links.
- `git diff --check`: passed. Refreshed `origin/main` remains `2ec4a22a`.

```bash
PYTHON_DOTENV_DISABLED=1 ./scripts/test-integration.sh \
  tests/integration/docker/test_installer.py \
  tests/integration/hooks/test_worktree_create.py \
  tests/integration/cli/test_artifact_hooks_integration.py \
  tests/integration/docker/test_session_routing.py \
  tests/integration/core/test_codex_fork_supervisor.py \
  tests/integration/core/test_codex_stop_recovery.py \
  tests/integration/core/test_codex_stop_ignores.py \
  tests/integration/docker/test_qa_release_artifact.py \
  -m "integration and not slow" -q --tb=short
```
