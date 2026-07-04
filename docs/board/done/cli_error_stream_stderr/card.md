# CLI error-stream fix (stdout -> stderr) -- cli_style A1

**Graduated slice** of [`docs/board/done/cli_style_ux_compliance/card.md`](../../done/cli_style_ux_compliance/card.md)
item **A1** (the audit headline). The index now lives in `done/`; this card owns the A1 execution unit only.

**Lane**: `done/`. **Branch**: `fix/cli-error-stream-stderr`. **Merged**: PR #70 on 2026-07-03. **Interleave**: Step 1
of the agreed backend/cli sequencing (below).

## Problem

`cli_style_guidelines.md` "Output Streams": results (incl. all `--json`) -> stdout; diagnostics/warnings/errors ->
stderr. Today most CLI error paths route to **stdout**, so `forge ... --json | jq` chokes when an error object lands in
the data stream.

**AST-verified model** (scope = top-level `src/forge/cli/*.py`, the terminal CLI; `cli/hooks/` uses a separate hook-JSON
output contract and is out of scope). Base commit of `fix/cli-error-stream-stderr`, 2026-07-02:

| Surface                                                   | Shape                                              | Count | Fix                                                       |
| --------------------------------------------------------- | -------------------------------------------------- | ----- | --------------------------------------------------------- |
| `print_error*`                                            | `console=console` (module `console` = stdout)      | 240   | Phase 2: AST sweep, drop the arg (use new stderr default) |
| `print_error*`                                            | `console=err_console`                              | 90    | already stderr -- leave                                   |
| `print_error*`                                            | `console=out` (handler-internal)                   | 4     | leave                                                     |
| `print_error*`                                            | `console=<expr>`                                   | 1     | Phase 2: audit individually                               |
| `print_error*`                                            | bare (no `console=`)                               | **0** | none today -- Phase 1 default flip is a forward guard     |
| `handle_session_error(e)`                                 | bare -> `_resolve` -> **stdout** (`output.py:108`) | 11    | Phase 1: fix the handler default                          |
| `handle_corrupt/unreadable_state_error(e)`                | bare -> `err_console` (`:124`,`:143`)              | 2     | already stderr -- leave                                   |
| `click.echo(json.dumps({"error"\|"routing_error": ...}))` | no `err=True`                                      | 13    | Phase 3: add `err=True`                                   |
| `click.secho(..., fg="red")`                              | no `err=True`                                      | 4     | Phase 3: add `err=True`                                   |

Module/func `console = Console(...)` in `cli/*.py`: **44 stdout, 2 stderr**. So `console=console` == stdout.

## Correction to the index card's A1 model (AST-verified 2026-07-02)

The index's grep-derived "~253 sites; flip the `print_error` default = one change closes 1b" is wrong on two counts:

1. **There are 0 bare `print_error*` calls today**, so flipping the default fixes **no current site** -- it is a
   *forward guard* against future bare calls. The real bulk is **240** `console=console` explicit-stdout overrides (grep
   undercounted at 173 by missing multiline calls; a same-line `grep -v console=` also miscounted those multiline calls
   as "bare"). These are neutralized by dropping the arg *after* the default flip -- an AST/semantic sweep, not a grep
   count.
2. **The index missed the error-handler defaults.** `handle_session_error` resolves `console=None` via `_resolve` to the
   **stdout** module console (`output.py:108`), so its **11 bare call sites** route errors to stdout; flipping
   `print_error` does not touch them (the handler passes an explicit stdout console in). One-line fix in the handler.
   (`handle_corrupt_state_error`/`handle_unreadable_state_error` already default to `err_console` -- no change.)

So A1 = default flip (guard) **+** handler-default fix (11 sites) **+** 240-override AST sweep **+** 13 JSON `err=True`
**+** 4 `secho` `err=True` **+** guard extension.

## Scope

**In (Step 1 only):** route all CLI *error/diagnostic* output to stderr on the top-level `cli/*.py` surface --
`print_error`/`print_error_with_tip` default flip, the `handle_session_error` default, the 240 explicit-stdout
overrides, the 13 `--json` error sites, the 4 red `secho` sites, and the guard extension that would have caught this.

**Out:** every other cli_style row (A2/A4/A5, B1-B5, C) -- they stay in the `doing/` index. B1 (backend help) folds into
the Step-2 backend PR. `cli/hooks/` (hook-JSON contract) is a different surface, not A1.

## Interleave / pause plan (agreed 2026-07-02)

1. **Step 1 (this card):** cli_style A1 error-stream root fix. **Shipped in PR #70**; cli_style is paused.
2. **Step 2 (next cursor):** `backend_runtime_cleanup` (full) + fold in cli_style **B1** backend-help (help-only, no
   metavar rename).
3. **Step 3:** resume cli_style for A2/A4/A5, B2-B5, C by review concern.

## Resolved decisions (maintainer, 2026-07-02)

- **D-json = `err=True`:** `--json` errors emit a machine-readable JSON object on **stderr** (matches compliant
  `proxy.py:135` / `session_manage.py:454`); stdout stays parser-safe.
- **D-codemod = drop-the-arg via AST/semantic sweep:** neutralize all 240 `print_error*(console=console)` calls by
  removing the arg (they fall to the new stderr default); the `console`-param helpers + the 1 `console=<expr>` site are
  audited individually (if a test captures that console for error text, repoint to `console=err_console` rather than
  dropping).
- **D-scope = errors-only:** do NOT flip `print_tip`'s global default. Make the error *wrappers*
  (`print_error_with_tip`, `handle_session_error`) use stderr so an error-associated tip follows the error stream.

## Grounding refs

- Fix surface: `src/forge/cli/output.py` (`err_console:30`, `_resolve:33`, `print_error:64`, `print_error_with_tip:69`,
  `handle_session_error:108`).
- Guard: `tests/src/cli/test_output_streams.py` -- today trips only pre-flight / success `--json` paths, never in-branch
  error paths (why the bug shipped green).
- Falsifiable check (must be empty after Phase 3):
  `rg 'click\.echo\(json\.dumps\(\{"(error|routing_error)"' src/forge/cli/ | grep -v 'err=True'`
- Re-scan (must be 0 after Phase 2): AST count of `print_error*` calls with `console=console` (grep is unreliable for
  multiline calls -- use the AST scanner, not a line grep).
