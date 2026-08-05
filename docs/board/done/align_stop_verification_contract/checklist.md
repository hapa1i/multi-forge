# Align Stop verification contract checklist

Current focus: complete; D006/U002/U003 are implemented and verified without activating the next Wave 2 member.

- [x] Create the execution branch from merged `main` and move this member to `doing/`.
- [x] Reproduce D006 synchronous latency and U002/U003 unknown-value behavior on current code (six failures).
- [x] Define strict authoring validation while preserving readable legacy manifests.
- [x] Separate passed, incomplete, misconfigured, and infrastructure outcomes at the Stop boundary.
- [x] Resolve the fixed test suite in the session worktree and bound/redact diagnostics.
- [x] Keep Forge-owned overhead under 100 ms outside the explicitly allowed test subprocess wall time.
- [x] Add one marked regression module for each finding and complete focused unit coverage.
- [x] Synchronize `docs/design.md` and `docs/design_workflows.md` with shipped behavior.
- [x] Run focused tests, required Docker policy-hook integration, regression/unit suites, and `make pre-commit`.
- [x] Record the outcome and move the verified member to `done/`.
