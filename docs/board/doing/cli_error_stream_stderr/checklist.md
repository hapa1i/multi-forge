# Checklist -- CLI error-stream fix (cli_style A1)

**Branch**: `fix/cli-error-stream-stderr` - **Card**: [`card.md`](card.md)

**Current focus**: Step 1 of the interleave -- route CLI error/diagnostic output to stderr so `forge ... --json | jq`
never sees an error on stdout. **Status: PLAN FOR REVIEW (no code written yet).**

**Guiding rule** (`cli_style_guidelines.md` "Output Streams"): results + all `--json` -> stdout; errors/diagnostics ->
stderr. **AST-verified base counts** (branch base, 2026-07-02, scope `src/forge/cli/*.py`): **0** bare `print_error*`;
**240** `print_error*(console=console)` (stdout); 90 `console=err_console`; 4 `console=out`; 1 `console=<expr>`; **11**
bare `handle_session_error` (resolves to stdout via `output.py:108`); 2 bare corrupt/unreadable handlers (already
stderr); 13 `--json` error echoes; 4 red `secho`. Module `console` ctors: 44 stdout / 2 stderr. **Use the AST scanner,
not line greps -- greps miscount multiline calls.**

## Phase 1 -- Default flip (forward guard) + the handler-default fix (the 11 real sites)

- [ ] Flip `print_error` (`output.py:64`) and `print_error_with_tip` (`:69`) defaults to `err_console`. **Fixes 0
  current sites** (no bare calls exist today) but is the correct default and the guard against future bare calls.
  **Assertion:** bare `print_error("x")` writes to stderr; `print_tip`'s own default stays stdout (D-scope).
- [ ] Fix `handle_session_error` (`output.py:108`): `out = _resolve(console)` -> `out = console if console is not None
  else err_console`, so its **11 bare call sites** (`main.py`, `session_fork.py`, `session_lifecycle.py`,
  `session_manage.py`, `session_resume_modes.py`) route the plain-error path to stderr; its tip already follows via
  `print_tip(console=out)` (D-scope: wrapper uses stderr). **Assertion:** bare `handle_session_error(<plain
  ForgeSessionError>)` writes error+tip to stderr, exit 1.
- [ ] Confirm `handle_corrupt_state_error` (`:124`) and `handle_unreadable_state_error` (`:143`) already default to
  `err_console` -- **no change**. **Assertion:** diff does not touch them.

## Phase 2 -- Neutralize the 240 explicit-stdout overrides (AST sweep, D-codemod)

- [ ] AST/semantic sweep: for every `print_error`/`print_error_with_tip` call passing `console=console` (240,
  AST-identified -- NOT a line grep), drop the `console=console` arg so it uses the new stderr default. **Assertion:** an
  AST re-scan reports 0 `print_error*(console=console)` calls (excluding the param-helpers below).
- [ ] **Audit individually**: the `console`-param helper functions (e.g. `backend.py:_exit_click_error/_show_source`,
  `config_cmd.py:_set_nested_key`, `editor.py:open_in_editor`, `model.py:_print_catalog`) **and** the 1 `console=<expr>`
  site. Error belongs on stderr regardless of the injected console; if a test captures that console for error text,
  repoint to `console=err_console` rather than dropping the arg. **Assertion:** each resolved with a one-line rationale;
  no error path in them lands on stdout.
- [ ] Leave the 90 `console=err_console` and 4 `console=out` sites untouched. **Assertion:** diff touches none of them.

## Phase 3 -- JSON (1a) + red secho (1c) -- corrected anchors

- [ ] Add `err=True` to the **13** `click.echo(json.dumps({"error"|"routing_error": ...}))` sites: `auth.py:358,495`,
  `gc.py:122`, `proxy.py:1715,1724`, `policy.py:665,837,872,1606`, `activity.py:58`, `workflow.py:197`,
  `session_manage.py:776,782`. (`proxy.py:135` and `session_manage.py:454` already carry `err=True` -- the compliant
  references; leave.) D-json: JSON object on stderr; stdout empty; exit non-zero. **Assertion:** falsifiable grep empty.
- [ ] Add `err=True` to the **4** red `secho` sites: `auth.py:191,396,505,508` (`auth.py:182` is already correct).
  **Assertion:** `grep -rn 'secho(.*fg="red"' src/forge/cli/ | grep -v err=True` returns 0.

## Phase 4 -- Close the guard gap (SAME PR -- else it re-slips through green)

- [ ] Extend `tests/src/cli/test_output_streams.py` to trip an **in-branch** `--json` *error* path (post-arg-parse, not
  pre-flight): stdout empty, error JSON on stderr, exit non-zero. Pick a command whose `--json` branch raises after
  parsing.
- [ ] Guard the two default fixes: bare `print_error("x")` -> stderr, and bare `handle_session_error(<plain error>)` ->
  stderr. Locks Phase 1 against regression.
- [ ] (Optional) repo-grep/AST meta-tests mirroring the falsifiable check + the `console=console` re-scan, so a
  re-introduced offender fails CI.

## Phase 5 -- Verify + docs

- [ ] Focused suite: `uv run pytest tests/src/cli -q`. Watch for tests asserting error text on `result.stdout` that must
  move to `result.stderr` (the handler-default + 240-sweep will shift many). **Assertion:** green; list every assertion
  moved stdout->stderr.
- [ ] `make pre-commit` clean.
- [ ] Docs: compliance, not a behavior change -- no design-doc edit expected. Touch `cli_style_guidelines.md` only if it
  still calls the stdout/stderr JSON guard "planned/not yet wired" (Slice 07 wording).
- [ ] `change_log.md` entry (bug-fix size): goal, the AST-corrected root strategy (default flip guard + handler-default
  fix + 240-override sweep + 13 JSON + 4 secho + guard), verification.

## Acceptance tests

| Test                                  | Fixture                                             | Assertion                                                                | Test File                              |
| ------------------------------------- | --------------------------------------------------- | ------------------------------------------------------------------------ | -------------------------------------- |
| Bare error -> stderr                  | `print_error("boom")` no console                    | text on stderr; stdout empty                                             | `tests/src/cli/test_output.py`         |
| Session-error handler -> stderr       | `handle_session_error(<plain ForgeSessionError>)`   | error + tip on stderr; exit 1; stdout empty                              | `tests/src/cli/test_output.py`         |
| `--json` error -> stderr              | a command whose `--json` branch raises post-parse   | `result.stdout` empty; error JSON on `result.stderr`; exit != 0          | `tests/src/cli/test_output_streams.py` |
| No JSON error on stdout (falsifiable) | repo grep                                           | falsifiable grep returns empty                                          | meta / CI                              |
| No stdout override on errors          | AST re-scan                                         | `print_error*(console=console)` count 0 (ex the param-helpers)          | AST meta guard                         |
| Red secho -> stderr                   | the 4 `auth.py` sites                               | each `fg="red"` echo carries `err=True`                                  | grep guard                             |

## Blockers / deferred

- Decisions **D-json / D-codemod / D-scope** are resolved (see card). No open blockers.
- Everything else in cli_style (A2/A4/A5, B, C) is **out of scope** and stays in the `proposed/` index. B1 -> Step-2
  backend PR. `cli/hooks/` is a separate surface, not A1.

## Closeout items

- [ ] All phases ticked with verification recorded.
- [ ] `change_log.md` entry added.
- [ ] Falsifiable grep + AST `console=console` re-scan + extended guard all green.
- [ ] cli_style index annotated: A1 shipped (row struck), pause of the remaining rows continues.
- [ ] Card moved `doing/ -> done/` after merge to `main`; index note points to Step 2 (`backend_runtime_cleanup`) as the
  next cursor.
