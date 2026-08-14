# Unify git-root discovery contracts checklist

Current focus: complete -- O066/O092 shipped independently in PR #181 and its Wave 7 member is closed.

## Phase 1 -- Characterize and activate

- [x] Close order 3 on `main` at `9817cad3`, branch from that exact commit, and activate only order-4 O066/O092.
- [x] Recheck the two parent walkers: `core.paths.find_git_root(Path)` returns a resolved path or `None`, while
  `session.claude.paths.find_project_root(str | None)` defaults to cwd and raises the established `FileNotFoundError`.
- [x] Keep Git-subprocess repository identity in `session.git`, Forge-root boundary walks, Codex `.codex` discovery,
  hook-dispatcher enrollment walks, and bare-repository behavior outside this member.
- [x] Recheck `ProjectRootNotFoundError` across production, tests, docs, commands, skills, and agents: only its
  definition and deletion-ledger references remain; correct the stale O066 source pointer to the Claude path helper.
- [x] Run the unchanged core-path, Claude-path, Git, artifact, resume, guard, and worktree characterization: 181 passed.

## Phase 2 -- Share traversal and delete dead type

- [x] Keep `core.paths.find_git_root` as the one public optional parent walker for `.git` directories and worktree
  marker files, including resolved starting paths and filesystem-root handling; avoid a single-caller private identity
  helper.
- [x] Route the strict Claude wrapper through that optional walker while retaining its signature, cwd default, exception
  type, capitalization, quoting, and message text.
- [x] Remove `ProjectRootNotFoundError` and prove no production, test, documentation, command, skill, agent, or packaged
  resource imports or references it as a live contract.
- [x] Update normative design ownership if the shared optional/strict path boundary is not already explicit; verify no
  end-user command or error documentation changes.

## Phase 3 -- Verify and close

- [x] Run focused core-path, Claude-path, artifact, launch/resume, guard, and worktree tests: 182 passed. The targeted
  Docker start, resume, and isolated-worktree integration slice passes 3 tests.
- [x] Run `make test-unit` (9,065 passed, 1 skipped), `make test-regression` (898 passed), and `make pre-commit`.
- [x] Resolve all 854 board links and changed-document fragments, verify the 3-done/1-doing/30-todo Wave 7 graph and all
  34 member backlinks, and run `git diff --check`.
- [x] After review and merge, record PR #181 (`a8cff31f`), move this member to `done/`, and leave order 5 parked until
  the closeout lands. The final audit resolves all 854 local path links across 332 board Markdown files and both
  fragments from the nine changed board documents; the Wave 7 graph is four done, zero doing, and 30 todo members.
