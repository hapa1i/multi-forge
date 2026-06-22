# CLI Style Guide

Developer-facing rules for Forge terminal commands (`forge ...`) and user-facing CLI recovery output.

This is the authority for CLI command shape and recovery-tip style. It applies two normative sources to the CLI surface
and does not restate them:

- General clean-break and durable-state rules: [coding_standards.md §5](coding_standards.md).
- Command-core architecture (shared `forge ...` / `%...` implementation): [design.md §3.12](../design.md) and the
  `src/forge/core/ops/__init__.py` module docstring.

## Command Shape

Forge CLI commands use explicit verbs and predictable command boundaries.

- **Groups orient.** Non-leaf groups print help when invoked without a subcommand. Do not hide work behind a bare group
  command. Use an explicit leaf such as `forge config show` or `forge search query`.

- **Leaves act.** Leaf commands do the sensible action when optional arguments are omitted. For example,
  `forge proxy metrics` shows all proxy metrics rather than failing only because no proxy ID was supplied.

- **Removed shortcuts are clean breaks.** In the current research-preview phase, remove deleted commands, options, and
  group-level shortcuts outright and let Click report `No such command` or `No such option`. Do not leave hidden
  tombstone commands or flag aliases that exist only to error. Name the replacement in the changelog and docs, not in a
  runtime shim.

- **Add deliberate aliases only.** The short root aliases are an intentional UX affordance, not a general compatibility
  pattern. They are defined in two maps in `src/forge/cli/main.py`: `_ALIASES` (resolution) and `_DISPLAY_ALIASES`
  (surfaced in `--help`). The current set is `auth` -> `authentication`, `ext` -> `extension`, `sess` -> `session`,
  `mem` -> `memory`, `cfg` -> `config`. Add a new alias only when the proposal explicitly justifies it, and update both
  maps. (`extensions` -> `extension` also exists in `_ALIASES` as a one-off rename shim; that is back-compat, not the
  alias pattern.)

- **Support scripting on read surfaces.** List/show and other scriptable read commands expose a `--json` flag with a
  stable structured shape. Use the project idiom, which names the option destination `as_json` so it does not shadow the
  stdlib `json` module:

  ```python
  @click.option("--json", "as_json", is_flag=True, help="Output as JSON")
  def list_sessions(..., as_json: bool) -> None:
      ...
  ```

- **Share business logic through command-core ops.** Logic shared between `forge ...` terminal commands and `%...`
  direct commands (routed through `forge hook user-prompt-submit`) belongs in `src/forge/core/ops/`. Command-core ops
  must be UI-agnostic: no Click, no printing, and no hook JSON. They return structured results (DTOs); the CLI and
  direct-command layers own all rendering. (Many ops use frozen dataclasses, but that is a local convention, not part of
  the contract.)

When adding a new CLI command:

1. Put the Click command in `src/forge/cli/`.
2. Register it in `src/forge/cli/main.py` or the appropriate subgroup.
3. Add tests under `tests/src/cli/`.
4. Update `docs/cli_reference.md` and the relevant end-user guide when the surface is user-facing.

## Tips And Recovery Output

All Rich-styled recovery output goes through `forge.cli.output`. Never hand-roll a `[dim]Tip: ...[/dim]` in a CLI
module: `tests/src/cli/test_output.py::test_cli_rich_tips_go_through_output_helpers` scans `src/forge/cli/**` for the
literal `[dim]Tip:` and fails if it appears anywhere except `output.py`.

```python
from forge.cli.output import print_error, print_error_with_tip, print_tip, handle_session_error
```

| Helper                 | Use for                                      | Exits?                          |
| ---------------------- | -------------------------------------------- | ------------------------------- |
| `print_error`          | A red `Error:` line, no tip                  | No                              |
| `print_tip`            | A standalone `Tip:` recovery block           | No                              |
| `print_error_with_tip` | The common error-plus-next-step shape        | No -- caller owns the exit code |
| `handle_session_error` | A `ForgeSessionError`: prints it, then exits | Yes -- `sys.exit(1)`            |

- **Pass the local `console`.** Whenever the call site keeps its own `Console` (e.g. for width-200 tables), pass it via
  `console=` so widths and rendering stay consistent. Only `output.py`'s own fallback console is width-less.
- **Context-free tips only in the map.** `handle_session_error` auto-attaches a recovery tip only for exceptions whose
  fix is identical regardless of caller (mapped in `_SESSION_ERROR_TIPS`, e.g. `SessionExistsError`). For
  context-sensitive recovery (e.g. `SessionNotFoundError`, whose fix differs for `start` vs `delete`/`show`), build the
  tip at the call site with `print_error_with_tip` and exit yourself -- do not route through `handle_session_error`.
- **Collapse home paths.** Render filesystem paths through `forge.core.paths.display_path` so a `$HOME` prefix shows as
  `~`.

Tip wording:

| Subject                | Form                                | Example                         |
| ---------------------- | ----------------------------------- | ------------------------------- |
| A command              | `Run '<full command>'`              | `Run 'forge proxy start'`       |
| A flag or option       | `Use --flag`                        | `Use --force to override.`      |
| Inline command         | single quotes, never backticks      | `'forge session delete <name>'` |
| Multi-line/placeholder | the helper's `commands=[...]` block | renders as copy-pasteable lines |

- Do not use `Hint:`. Use `Tip:` for actionable recovery or next-step guidance only.

Non-recovery output carries no `Tip:`/`Error:` prefix and is usually dimmed:

- **Informational**: `Already up to date.`
- **Status**: `Backup: {path}`
- **Dry-run**: `(dry-run) Would patch ...`
- **Next steps**: a `Next steps:` line followed by a bullet list.

Example:

```python
print_error_with_tip(
    f"Proxy '{proxy_id}' not found at {display_path(proxy_path)}",
    f"Run 'forge proxy create <template> --name {proxy_id}' to create it.",
    console=console,
)

print_tip(
    "Start an instance with:",
    commands=[f"forge backend start {adapter} --port 4000"],
    console=console,
)
```
