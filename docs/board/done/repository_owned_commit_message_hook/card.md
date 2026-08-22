# Repository-Owned Commit Message Hook

**Lane**: `done/`

## Goal

Make Multi-Forge's existing commit-message normalization explicit and repository-owned so contributors do not depend on
the personal `core.hooksPath`, normalizer, or mapping to create the same commit message.

## Existing Behavior

The active global `commit-msg` hook in `personal-artifacts` delegates to `scripts/normalize-commit-msg.py`, which reads
`config/normalize-text-mapping.json`. It replaces configured emoji and phrases, deletes matching attribution lines, and
preserves a bracketed label when normalization would otherwise empty the complete message.

## Decisions

- Port the existing normalizer and mapping without changing their normalization semantics.
- Register the normalizer as pre-commit's `commit-msg` stage. Pre-commit installs a real Git `commit-msg` hook; ordinary
  file and code checks remain in the existing `pre-commit` stage.
- Do not add a tracked `.githooks` directory or another pre-commit launcher.
- Treat the repository files as authoritative after migration. `personal-artifacts` may remain a fallback for other
  repositories but is not a Multi-Forge dependency.
- Document that pre-commit refuses hook installation while `core.hooksPath` is configured, so contributors must remove
  or migrate that override before installing this repository's hooks.

## Acceptance

1. The mapping and executable normalizer are tracked in Multi-Forge and preserve the current normalization behavior.
2. The repository's pre-commit configuration installs both `pre-commit` and `commit-msg` hook types; the latter runs
   before Git creates the commit.
3. Focused tests cover the complete shipped mapping, phrase deletion, inline replacement, whitespace preservation,
   empty-message fallback, file mutation, and filter mode.
4. Contributor documentation names the repository-owned files, installation command, and `core.hooksPath` conflict.
5. `AGENTS.md` no longer attributes staged-file behavior to a hidden global hook.

## Non-goals

- Do not introduce a new commit-message style or conventional-commit validator.
- Do not rewrite existing Git history.
- Do not move ordinary source/document checks out of the `pre-commit` stage.
- Do not require a tracked `.githooks` dispatcher.
