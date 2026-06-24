# CLI Style Guide

Developer-facing rules for Forge terminal commands (`forge ...`) and user-facing CLI recovery output.

This is the authority for CLI command shape and recovery-tip style. It applies two normative sources to the CLI surface
and does not restate them:

- General clean-break and durable-state rules: [coding_standards.md §5](coding_standards.md).
- Command-core architecture (shared `forge ...` / `%...` implementation): [design.md §3.12](../design.md) and the
  `src/forge/core/ops/__init__.py` module docstring.

Each rule below names the test that guards it. A rule tagged _(review)_ is checked in code review, not mechanically;
those are collected in [Review Checklist](#review-checklist). Do not add a rule with neither a guard nor a _(review)_
tag -- an unenforced rule drifts.

## Command Shape

Forge CLI commands use explicit verbs and predictable command boundaries.

- **Groups orient.** Non-leaf groups print help when invoked without a subcommand. Do not hide work behind a bare group
  command. Use an explicit leaf such as `forge config show` or `forge search query`.

- **Leaves act.** Leaf commands do the sensible action when optional arguments are omitted. For example,
  `forge proxy metrics` shows all proxy metrics rather than failing only because no proxy ID was supplied.

- **Groups earn their depth.** A group earns a path segment only when it holds two or more visible leaves (or a
  documented, imminent one). No single-leaf subgroups and no single-child group nests -- attach the leaf to the parent.
  Non-leaf groups print help and exit 0 on bare invocation; prefer `no_args_is_help=True` over hand-rolling
  `invoke_without_command` only to echo help. _Guard:_ `test_command_tree_invariants::test_no_single_leaf_groups`.

- **Name leaves distinctly.** Sibling leaves must not collide on tab-completion: none may be a prefix of another or
  share a six-character-or-longer prefix, and one verb must not name two different engines in a group. _Guard:_
  `test_command_tree_invariants::test_no_confusable_sibling_leaves`.

- **Leaves fail loudly on missing required input.** When a leaf has no sensible default and a required selector is
  absent, exit non-zero with an actionable message -- never warn and exit 0. _(review)_

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

- **Canonical names follow user vocabulary.** The canonical command name is the word users actually type, not the
  implementation or historical name; the short form is the alias, not the canonical. A new alias needs a recorded
  rationale and a matching update to `_ALIASES`, `_DISPLAY_ALIASES`, and the docs. _(review)_

- **Support scripting on read surfaces.** List/show and other scriptable read commands expose a `--json` flag with a
  stable structured shape. Use the project idiom, which names the option destination `as_json` so it does not shadow the
  stdlib `json` module:

  ```python
  @click.option("--json", "as_json", is_flag=True, help="Output as JSON")
  def list_sessions(..., as_json: bool) -> None:
      ...
  ```

  Read commands (list/show/status and other scriptable reads) default to human output and add `--json` with a stable,
  documented shape -- no free-form or conditionally-built fields in the JSON. A surface that is intentionally raw-text
  or JSON-only states that at the call site. _Guards:_ `test_command_tree_invariants::test_json_option_dest_is_as_json`,
  `test_command_tree_invariants::test_read_leaves_expose_json`.

- **Share business logic through command-core ops.** Logic shared between `forge ...` terminal commands and `%...`
  direct commands (routed through `forge hook user-prompt-submit`) belongs in `src/forge/core/ops/`. Command-core ops
  must be UI-agnostic: no Click, no printing, and no hook JSON. They return structured results (DTOs); the CLI and
  direct-command layers own all rendering. (Many ops use frozen dataclasses, but that is a local convention, not part of
  the contract.)

- **Destructive verbs are predictable.** A `clean` verb previews by default and mutates only with `--yes`. A `delete` or
  `reset` verb may act after a prompt, but the prompt and its `--yes` bypass must be explicit and documented. Use one
  confirmation-bypass flag name across the CLI. _(review)_

- **Sibling resources expose comparable verbs.** Resource groups with a `create`/`start`/`stop`/`delete` lifecycle offer
  the same verb set as their siblings; document any intentional asymmetry at the call site instead of letting it drift.
  _(review)_

- **Session selectors are consistent.** Use an optional positional for the session only when the session is the
  command's primary object (`forge session show [session]`); use `--session` when the session is ambient scope for some
  other primary object (`forge policy status --session`). For multi-entity commands the primary entity is the positional
  and the rest are options (`forge session transfer show <parent> --child <child>`). _(review)_ Audited compliant
  2026-06-23 (all ~32 session-scoped commands; `forge_cli_cleanup` Slice 07 F11) — `telemetry activity [session]`,
  `costs show [proxy_id]`, and `trace list --session` differ correctly because each applies the rule to its own primary
  object.

- **Editable config objects share a verb vocabulary.** Config-like surfaces (`forge config`, `forge proxy`,
  `forge claude preset`, `forge proxy template`) use one verb set for the same operations and document deliberate
  exceptions. _(review)_ The exact vocabulary is being settled in the `forge_cli_cleanup` card; do not enumerate it here
  until it ships.

When adding a new CLI command:

1. Put the Click command in `src/forge/cli/`.
2. Register it in `src/forge/cli/main.py` or the appropriate subgroup.
3. Add tests under `tests/src/cli/`.
4. Update `docs/cli_reference.md` and the relevant end-user guide when the surface is user-facing.

## Output Streams

- **Results to stdout, diagnostics to stderr.** A command's primary result -- including all `--json` output -- goes to
  stdout. Diagnostics, prompts, warnings, and errors go to stderr. A read command's human and `--json` modes use the
  same result stream: do not render the human table on stderr while JSON goes to stdout.
- **Place the non-recovery categories.** Dry-run previews and `Next steps:` blocks are results (stdout); status lines
  like `Backup: {path}` are diagnostics (stderr).
- A mechanical guard wires this contract: `tests/src/cli/test_output_streams.py` (plain `CliRunner()`, which captures
  stdout and stderr separately) asserts that `--json` mode emits valid JSON on stdout and nothing on stderr for the
  telemetry leaves (`costs show`, `trace list`, seeded `activity`) and `proxy audit show|diff`, and that their human
  tables land on stdout. Extend it whenever a new read leaf could split its result stream.

## Tips And Recovery Output

All Rich-styled recovery output goes through `forge.cli.output`. Never hand-roll a `[dim]Tip: ...[/dim]` in a CLI
module: `tests/src/cli/test_output.py::test_cli_rich_tips_go_through_output_helpers` scans `src/forge/cli/**` for the
literal `[dim]Tip:` and fails if it appears anywhere except `output.py`. The same applies to errors: terminal errors go
through `print_error` / `print_error_with_tip`, and `test_output.py::test_cli_rich_errors_go_through_print_error` guards
hand-rolled `[red]Error:[/red]` the same way, with an allowlist tracking the pre-existing call sites the
`forge_cli_cleanup` card retires.

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
    commands=[f"forge model backend start {adapter} --port 4000"],
    console=console,
)
```

## Review Checklist

The rules tagged _(review)_ above are enforced here, not by tests. On any CLI change, confirm:

- A leaf with a missing required selector exits non-zero, not warn-and-exit-0.
- `clean` previews by default; `delete` / `reset` confirmation and its `--yes` bypass are explicit and documented.
- Sibling lifecycle resources expose comparable verbs, or the asymmetry is documented at the call site.
- Session selection follows the positional-vs-`--session` rule.
- Editable config objects use the shared verb vocabulary.
- Canonical names match user vocabulary; any new alias has a recorded rationale and both alias maps updated.
- A read command's human and `--json` output share the stdout result stream.
