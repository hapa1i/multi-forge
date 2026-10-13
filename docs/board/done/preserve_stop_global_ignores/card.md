# Preserve global ignores in Stop evidence

Status: done, 2026-10-11. [PR #264](https://github.com/hapa1i/multi-forge/pull/264) merged as `d33721a2`. Execution
branch: `codex/preserve-stop-global-ignores`, based on `main` at `5613b185`. Discovered during
[B5 planning](../../done/codex_fork_supervisor/card.md). This is a separate correction to shipped
[B4 Stop evidence](../../done/codex_stop_review/card.md), not B5 implementation work.

## Problem and evidence

`src/forge/policy/semantic/turn_evidence.py` suppresses global/system Git configuration to prevent execution of user Git
helpers during evidence capture. It then enumerates untracked files with `git ls-files --others --exclude-standard`. An
exclusion supplied only through a global `core.excludesFile` is lost when `GIT_CONFIG_GLOBAL` is `/dev/null`.

Verified against `5613b185` on 2026-10-11 using a disposable repository, one tracked file, a synthetic `.env`, and a
temporary global config pointing to an ignore file containing `.env`. Ordinary Git enumeration returned no untracked
files. `turn_evidence.capture()` included `.env`; after changing the synthetic value, `compare()` emitted its diff. No
real credentials or native/model calls were used, and the fixture was removed.

Incidental files can therefore enter the private snapshot store and later review evidence despite the user's Git ignore
configuration. This does not imply that every ignored file is sent on every turn: outgoing changes depend on the
captured baseline, observed endpoints, and evidence bounds. Global ignores also do not protect tracked files or content
explicitly supplied in a tool request.

## Scope and acceptance

- Preserve the effective global exclusion rules for untracked enumeration without restoring unsafe global execution
  settings, hooks, filters, textconv, external diff, fsmonitor, or credential helpers.
- Resolve ignore configuration as data with explicit precedence and path/error handling. Do not fix this by loading the
  entire global config into capture subprocesses or claiming an ignore rule is a general secret filter.
- Add fixtures for explicit global `core.excludesFile`, the default global ignore location, repository-local rules and
  overrides, missing/unreadable ignore inputs, and linked worktrees. Cover unchanged capture and changed evidence.
- Prove an ignored synthetic untracked file stays out of both snapshot blobs and outgoing review evidence, while normal
  tracked/untracked work and executable-helper isolation retain their existing behavior.
- Run focused unit/regression and targeted Stop integration checks, update the evidence-scope documentation, and retain
  a clean closeout. Keep this fix on a separate branch and PR.

## Dependency

B5's native Stop product admission waits for this correction and a composition regression. B5's disposable runtime
experiments may continue after their own review using synthetic content. This correction does not reopen or rewrite B4's
historical captures. B5 planning was committed separately at `a5428554`; its duplicate proposal was removed when that
branch rebased onto `225ab3dd`.
