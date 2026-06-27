## Summary

<!-- What changed and why?
Keep it concrete. Avoid generic agent phrasing (e.g., "comprehensive", "robust", "seamless").
-->

## Changes & Design Decisions

<!--
What changed? Predict the shape of the diff for the reviewer.
- Write for a reviewer deciding whether this should merge.
- Focus on non-obvious decisions. Group by review concern, not component inventory.
- Prefer information density over completeness theater.
- Call out risks, migrations, and where the reviewer should focus.
- DO NOT repeat what is obvious from the diff or narrate your process. Observe brevity.
-->

## Test plan

- [ ] `make pre-commit` passes (ruff, black, isort, mypy, pyright, mdformat, etc)
- [ ] `make test` passes or more targeted:
  - `make test-unit`,
  - targeted `make test-integration` / `./scripts/test-integration.sh`,
  - `make test-regression`

<!-- If this is a bug fix, include a regression test (see docs/developer/testing_guidelines.md) -->

## Documentation

- [ ] Design docs updated if architecture changed:
  - `docs/design.md`
  - `docs/design_appendix.md`
  - `docs/design_workflows.md`
  - `docs/cli_reference.md`
- [ ] N/A — no doc updates needed
