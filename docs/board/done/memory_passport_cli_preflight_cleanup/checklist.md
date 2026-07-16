# Checklist: Consolidate memory-passport CLI target preflight

**Branch**: `memory-passport-cli-preflight-cleanup`

## Current focus

Closeout complete. PR #105 merged to `main` at `9288bed2`; the card is in `done/`, inbound links are repointed, and
post-move Markdown validation is green.

## Preflight matrix (shipped behavior to preserve)

The four affected leaves in `src/forge/cli/memory.py` run near-identical plumbing with behavior differences. This matrix
is the message and stream contract Phase 1 pins and Phase 2 must not change. The **Error channel** column covers the
rootless, unsafe-path, and missing-file failures only; the incompatible-pin channel is uniform and documented below the
table.

| Leaf               | Compat pin   | Missing-file wording          | Error channel (rootless/unsafe/missing)     |
| ------------------ | ------------ | ----------------------------- | ------------------------------------------- |
| `track`            | enforced     | `File does not exist: {path}` | `ClickException`                            |
| `passport show`    | NOT enforced | `File not found: {path}`      | `ClickException`                            |
| `passport upgrade` | enforced     | `File not found: {path}`      | `print_error`/`print_tip` (stderr) + exit 1 |
| `passport remove`  | enforced     | `File not found: {path}`      | `ClickException`                            |

**Incompatible-pin channel (uniform, bypasses the leaf channel):** all three mutating leaves call
`enforce_target_project_compatibility` (`src/forge/cli/guards.py:17`), which on refusal emits `print_error` +
`print_tip(e.recovery)` on stderr and `sys.exit(1)` — never `ClickException`, regardless of the leaf's own channel.

**Upgrade's stage-specific tips (each must survive extraction):**

| Failure stage | `Tip:` text                                                       |
| ------------- | ----------------------------------------------------------------- |
| rootless      | `Run 'forge extension enable' first.`                             |
| unsafe path   | `Use a project-relative Markdown path inside this Forge project.` |
| missing file  | `Check the project-relative path and try again.`                  |

**Shared step order in every leaf:** resolve `ExecutionContext.from_cwd()` -> rootless check
(`Not inside a Forge project`) -> [compat pin, mutating leaves only] -> `is_safe_designated_doc_path`
(`Invalid path: {reason}`) -> resolve abs path -> `Path.is_file()` existence check. `track` additionally validates
`--strategy` and the `--shadow-path`-requires-`--propose` combination **before** context resolution
(`src/forge/cli/memory.py:164-171`).

**Resolved finding (2026-07-16 review): the `try/except ForgeOpError` wraps around `from_cwd()` in show/upgrade/remove
are dead structure, not shipped behavior.** `ExecutionContext.from_cwd` (`src/forge/core/ops/context.py:34`) is pure
path derivation and raises no `ForgeOpError` (internal `OSError`/`ValueError` are swallowed; a deleted cwd raises
`OSError`, which the wrap never caught). The track-vs-others wrap difference is therefore not a behavioral contract.
Phase 2 removes the dead wraps (and upgrade's unreachable context-failure tip
`Run this command from an enabled Forge project.`) instead of adding a resolver parameter for them; removal is
contract-neutral by the argument above.

## Phase 0: Acceptance and setup

- [x] Execution branch `memory-passport-cli-preflight-cleanup` created from `main`.
- [x] Card moved `proposed/` -> `doing/` via `git mv`; card status line updated.
- [x] Inbound links in `done/okf_compatible_memory_passports/checklist.md` (former lines 221, 259) repointed `proposed/`
  -> `doing/`; repoint again to `done/` at closeout.
- [x] Checklist created and revised per 2026-07-16 review (matrix channel fix, full per-leaf grid, structured-failure
  resolver shape, dead-wrap finding, precedence tests, stream-exactness wording, Phase 3 ordering).
- [x] Revised checklist reviewed by human; scope confirmed on 2026-07-16.

## Phase 1: Characterization (tests only, no production change)

The card requires the full grid — rootless, unsafe, missing, incompatible, successful — for **every** leaf with explicit
stream placement. Before Phase 1, partial coverage included incompatible-pin refusal for `track`
(`test_track_refuses_incompatible_project_without_editing_doc`), `upgrade`
(`test_upgrade_refuses_incompatible_project_without_modifying_doc`,
`test_upgrade_refuses_invalid_project_config_without_modifying_doc`), and `remove`
(`test_remove_refuses_incompatible_project_without_editing_doc`); missing-file for `track`
(`test_track_rejects_missing_file`), `show` (`test_show_file_not_found`), and `upgrade`
(`test_upgrade_rejects_unsafe_or_missing_path`); unsafe-path for `track` (`test_track_rejects_absolute_path`) and
`upgrade`. The exact matrix below superseded the three weak missing-file tests, which were removed during cleanup. Phase
1 completes the grid and hardens stream assertions:

- [x] Rootless path for each of the four leaves: from a cwd with no `.forge/`, exit 1. For `track`, `show`, and
  `remove`, assert `stdout == ""` and exact stderr
  `` Error: Not inside a Forge project. Run `forge extension enable` first.\n ``. For `upgrade`, assert `stdout == ""`
  and exact stderr `Error: Not inside a Forge project.\n\nTip: Run 'forge extension enable' first.\n`.
- [x] Unsafe-path coverage for every leaf: harden the existing `track` and `upgrade` cases and add `show` and `remove`.
  For a representative `../outside.md` traversal, the three Click leaves assert exact stderr
  `Error: Invalid path: escapes base directory: ../outside.md\n`; `upgrade` asserts exact stderr
  `Error: Invalid path: escapes base directory: ../outside.md\n\nTip: Use a project-relative Markdown path inside this Forge project.\n`.
- [x] Missing-file for `remove`: exit 1, `File not found: {path}`.
- [x] `passport show` read-only exemption: with an incompatible `.forge/project.toml` pin, `show` still succeeds (exit
  0, passport rendered on stdout, stderr empty). This is the load-bearing read-vs-mutation distinction the resolver must
  make explicit.
- [x] No-mutation assertions on every new `remove` error path: existing target bytes stay unchanged where a target
  exists; a missing target remains absent. This matches the existing `*_without_editing_doc` pattern.
- [x] Stream placement asserted explicitly across the full grid rather than through mixed `result.output`:
  - rootless, unsafe, missing, and incompatible refusals have `stdout == ""` and the diagnostic on stderr for every
    affected leaf;
  - the three mutating incompatible-pin tests assert their leaf-level streams in addition to the shared
    `test_target_project_compatibility_guard_uses_shared_recovery` guard coverage;
  - each successful leaf writes its result to stdout with stderr empty; `show --json` and `remove --json` parse
    `result.stdout` with `result.stderr == ""`;
  - pre-JSON failures of `show --json` and `remove --json` keep `stdout == ""`, and all characterized `upgrade`
    preflight failures do likewise.
- [x] Upgrade's three reachable stage tips pinned exactly (rootless / unsafe / missing table above), so a generic shared
  tip cannot silently replace them.
- [x] Existing missing-file wording drift preserved for this cleanup in one test, without treating it as a preferred
  product distinction: `track` says `File does not exist:`; `show`/`upgrade`/`remove` say `File not found:`.
- [x] Precedence tests (which error wins) so extraction cannot reorder:
  - `track` invalid `--strategy` (and `--shadow-path` without `--propose`) fails before context resolution — asserted
    from a rootless cwd (flag error wins over `Not inside a Forge project`).
  - Mutating leaf with incompatible pin AND unsafe path -> compat refusal wins.
  - Mutating leaf with incompatible pin AND missing file -> compat refusal wins.
  - Any leaf with unsafe path AND missing file -> `Invalid path:` wins.
- [x] Success paths hardened in `test_track_writes_passport_no_manifest`, `test_show_valid_passport`,
  `test_upgrade_adds_envelope_preserves_raw_passport_and_is_idempotent`, and `test_remove_existing_passport`; JSON
  stream placement is pinned by `test_show_json_output` and `test_remove_json`.
- [x] Full characterization set passed against unmodified `src/forge/cli/memory.py` (`168 passed`).

## Phase 2: Extraction

- [x] Add a private structured preflight failure (kind: `rootless` | `unsafe` | `missing`, plus the detail needed for
  wording) raised by a module-private resolver in `cli/memory.py`; **rendering stays leaf-owned** (each leaf maps kind
  -> its own channel, wording, and — for `upgrade` — stage tip). Signature shape:
  `_resolve_memory_doc_target(path, *, enforce_compatibility: bool) -> tuple[Path, Path]` (forge_root, abs_path).
- [x] Parameter is named `enforce_compatibility` (not `mutating`). When true, the resolver calls
  `enforce_target_project_compatibility`, which keeps its own stderr/exit-1 channel — it bypasses the structured failure
  and leaf rendering by design; document this at the call site.
- [x] Existence check stays `Path.is_file()` exactly (a directory at the target must keep failing as missing, not be
  admitted by a generic `exists()`).
- [x] Remove the dead `try/except ForgeOpError` wraps and upgrade's unreachable context-failure branch (resolved finding
  above); note the removal in the change-log entry.
- [x] Repoint `track`, `passport show`, `passport upgrade`, `passport remove` through the resolver, preserving `track`'s
  pre-context flag validation order.
- [x] Explicitly kept OUT of the resolver (verified by inspection):
  - `validate_okf_reserved_basenames` and shadow path/collision checks stay in the domain/track layer (card acceptance
    shape: reserved OKF validation not hidden in generic path containment).
  - `read_passport` + malformed-passport wording stays leaf-owned.
  - `list_cmd`, `shadows *`, and `_review_curate` preflight untouched (session-scoped resolution, different shape; card
    scope is the four doc-path leaves).
- [x] Every Phase 1 characterization test passed without modification after the repoint (`168 passed`).
- [x] `test_cli_rich_tips_go_through_output_helpers` and `test_cli_rich_errors_go_through_print_error` are green in the
  focused suite; no hand-rolled `Tip:` / `[red]Error:[/red]` was introduced.

### Deferred decisions

- Resolver location: module-private in `cli/memory.py` (single consumer). Promote to its own module only if it grows a
  second consumer; do not create a new module speculatively.
- (Resolved 2026-07-16) The `ForgeOpError` wrap question — see the resolved finding in the matrix section; eliminated in
  Phase 2, no resolver parameter.

## Acceptance tests

| Test                      | Fixture                                      | Assertion                                                                                  | Test File                      |
| ------------------------- | -------------------------------------------- | ------------------------------------------------------------------------------------------ | ------------------------------ |
| show read-only under pin  | seeded project + incompatible `project.toml` | `show` exit 0 with result on stdout and stderr empty; mutators refuse without side effects | `tests/src/cli/test_memory.py` |
| compatibility streams     | incompatible pin, each mutating leaf         | exit 1; stdout empty; shared compatibility `Error:`/`Tip:` on stderr                       | `tests/src/cli/test_memory.py` |
| rootless per leaf         | tmp cwd without `.forge/`                    | exit 1; exact Click or upgrade stderr preserved; stdout empty                              | `tests/src/cli/test_memory.py` |
| unsafe/missing grid fill  | seeded project; traversal + nonexistent path | complete safety/missing diagnostic preserved; remove target unchanged or absent            | `tests/src/cli/test_memory.py` |
| upgrade stage tips        | rootless cwd / unsafe path / missing file    | exit 1; exact stage `Error:`/`Tip:` on stderr; `stdout == ""`                              | `tests/src/cli/test_memory.py` |
| successful output streams | existing success fixture for each leaf       | result on stdout and stderr empty; JSON parses from stdout                                 | `tests/src/cli/test_memory.py` |
| error precedence          | combined-failure fixtures (see Phase 1 list) | flag > rootless (track); compat > unsafe/missing; unsafe > missing                         | `tests/src/cli/test_memory.py` |
| missing wording preserved | seeded project, nonexistent doc path         | track: `File does not exist:`; show/upgrade/remove: `File not found:`                      | `tests/src/cli/test_memory.py` |
| resolver equivalence      | all Phase 1 characterizations                | pass unmodified after Phase 2 repoint                                                      | `tests/src/cli/test_memory.py` |

## Phase 3: Verification and closeout

- [x] Focused suites:
  `uv run pytest tests/src/cli/test_memory.py tests/src/cli/test_output.py tests/src/cli/test_output_streams.py tests/src/cli/test_command_tree_invariants.py -q`
  (`228 passed`).
- [x] `make test-unit` green (`7907 passed, 1 skipped, 117 deselected`).
- [x] `make pre-commit` clean on the code change.
- [x] Integration decision recorded: this card changes CLI plumbing only (no hooks, session lifecycle, memory-writer
  runtime, proxy, or installer paths), so the integration-trigger list does not apply. Run
  `./scripts/test-integration.sh tests/integration/cli/test_handoff_integration.py` only if any `forge.session.passport`
  / `project_memory` signature is touched (goal: none).
- [x] `docs/developer/cli_style_guidelines.md` checked; no update is needed because the characterized output contracts
  are unchanged.
- [x] Compact entry added to `docs/board/change_log.md` (names the dead-wrap removal).
- [x] Durable-lessons disposition: no new stable architecture or operational invariant emerged beyond the local resolver
  contract and its characterization tests, so no shadow proposal was added.
- [x] Card moved `doing/` -> `done/`; the two inbound references in `done/okf_compatible_memory_passports/checklist.md`
  now point at `done/`.
- [x] Final `make pre-commit-md` and `git diff --check` passed after the change-log, lane-move, and inbound-link edits.
