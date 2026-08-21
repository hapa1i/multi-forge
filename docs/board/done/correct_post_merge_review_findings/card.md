# Correct post-merge review findings

**Epic**: [`epic_repo_maintenance_round`](../epic_repo_maintenance_round/card.md).

**Lane**: `done/` -- shipped in PR #185 (`8ccbf387`) before Wave 7 order 8.

**Related shipped members**:

- [`restore_proxy_request_semantics`](../../done/restore_proxy_request_semantics/card.md) (O035 request intent)
- [`align_policy_routing_context`](../../done/align_policy_routing_context/card.md) (O013/O034 selector guidance)
- [`preserve_session_launch_preconditions`](../../done/preserve_session_launch_preconditions/card.md) (O017 rollback)
- [`harden_walkthrough_sandbox_provenance`](../../done/harden_walkthrough_sandbox_provenance/card.md) (O036 boundary)
- [`centralize_time_parsing_and_periods`](../../done/centralize_time_parsing_and_periods/card.md) (O060/O061/O094
  timezone boundary)

These are post-merge edge cases in the implementations above, not unresolved instances of the original ledger claims.
The shipped finding counts remain unchanged.

## Goal

Close five verified defects found by a review of PRs #170--#180 before resuming structural cleanup: retain the validated
walkthrough root after `env.sh`, reject impossible translated tool selection, honor valid process `TZ` forms, surface
failed session rollback, and print valid positional shadow-session recovery.

## Evidence and authority

- A marked walkthrough repository could replace `FORGE_TEST_REPO` from its sourced environment after the denylist and
  provenance checks, redirecting later gates and command execution.
- Tool filtering could remove every eligible tool while forwarding OpenAI `required`, or remove a specifically named
  tool while retaining that impossible selection.
- `_local_timezone()` treated only IANA keys as process-local `TZ`; valid absolute/colon TZif paths and POSIX rule
  strings silently fell back to the host zone.
- Rewind/native-relocate rollback caught deletion failure without telling the operator that the child manifest and index
  row remained.
- Ambiguous `policy shadow show|status` guidance recommended the nonexistent `--session` option even though `SESSION` is
  positional.

Authority comes from the bundled walkthrough safety contract, translated proxy request-intent contract,
[`docs/design.md`](../../../design.md) timestamp/session boundaries, and the CLI recovery-output conventions.

## Acceptance criteria

- Every post-source walkthrough gate and final `cd` derives from one retained canonical root; a canonically different
  reassignment fails before command execution, while an equivalent safe symlink alias remains compatible.
- Filtered `any` or named tool selection returns typed HTTP 400 before acquiring an upstream client.
- IANA, absolute/colon TZif, and POSIX-rule `TZ` values produce exact transition-aware local-period bounds; invalid
  values retain the `/etc/localtime` fallback.
- Failed child rollback names the retained session and prints an exact transcript-preserving delete command;
  same-directory resume includes `--keep-worktree`, worktree forks do not.
- Ambiguous shadow read recovery uses the positional `SESSION` form in both human and JSON output.

## Scope boundaries

- Do not reopen or renumber the original Wave 6/Wave 7 findings.
- Do not change optional `tool_choice:auto` or `none` behavior without a reproduced upstream incompatibility and a
  separate contract decision.
- Do not use process-global `tzset`, weaken invalid-`TZ` fallback, change stored timestamps, or alter period ranges.
- Keep Wave 7 orders 8--35 parked until this corrective member merges and closes.

## Verification

Primary verification passes: 230 focused tests; 9,115 unit tests with one skip and 122 deselected; 906 regressions; five
targeted proxy/rewind Docker integrations; 23 session-lifecycle Docker integrations; full pre-commit; sdist/wheel build;
and the clean-wheel LiteLLM runtime smoke. The review-strength amendment passes 71 focused tests; final pre-commit,
Markdown, diff, and board-link checks pass across 338 board documents and 871 relative links. PR #185 merged as
`8ccbf387` with all five GitHub checks passing.
