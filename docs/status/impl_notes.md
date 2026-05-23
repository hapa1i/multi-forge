# Implementation Notes

Human-approved memory for details that future Forge sessions should retain.

This file is intentionally selective. The handoff agent should propose additions in a shadow doc; humans promote only
the notes that are worth carrying forward.

## Maintenance

- Updated by humans after reviewing proposed notes, not directly by the handoff agent.
- Source for proposed additions: `.forge/memory/suggested_impl_notes.md`.
- Keep notes durable and actionable. Prefer bullets with links to the source doc, issue, test, or file.
- Remove or rewrite notes when they become obsolete.
- Check size periodically and prune stale notes before appending:

```bash
wc -l docs/status/impl_notes.md
./scripts/count-tokens.py --model <agent-model> docs/status/impl_notes.md
```

## What Belongs Here

- Stable architecture decisions and the rationale behind them.
- Non-obvious invariants, ownership boundaries, and path or state rules.
- Bug causes, fixes, and test patterns likely to recur.
- Operational constraints that future sessions must remember.
- Conventions for executing multi-session work in this repo.

## What Does Not Belong Here

- Raw session summaries.
- Pending tasks or phase plans.
- Detailed command output.
- Unverified hunches.
- Duplicates of `docs/status/change_log.md`.

## Notes

### Memory System Map (Phase 0)

Baseline map of the existing memory system before the `forge memory` migration (`docs/proposals/memory_enhancement.md`).
Organized by subsystem.

#### CLI surface (`forge session memory`)

- Module: `src/forge/cli/session_memory.py` (201 lines). Click group `memory_group` with three commands: `list-docs`,
  `add-doc`, `remove-doc`.
- Registration: `src/forge/cli/session.py:869-877` -- `_register_subgroups()` calls `session.add_command(memory_group)`
  at module import time.
- `VALID_STRATEGIES` set (module top): `{project-state, checklist, changelog, debugging, patterns, suggested, generic}`.
- Validation: `_validate_single_doc()` mirrors `handoff_agent._validate_designated_docs()` so the CLI rejects what the
  agent would silently skip.
- **Read/write split**: `_current_docs()` reads effective intent (merged intent+overrides via
  `compute_effective_intent()`), while `_write_docs()` writes the whole doc list to `overrides.memory.designated_docs`
  through `set_session_override()`. This read-effective / write-override asymmetry matters for Phase 1 passport
  integration.
- Tests: `tests/src/cli/test_session_memory.py` -- 13 test methods (2 list, 8 add, 3 remove) covering all verbs plus
  path-safety, strategy-consistency, duplicate-path, and self-shadow rejection.

#### Data model

- `DesignatedDoc`: `src/forge/session/models.py:102-126` --
  `(path: str, strategy: str = "generic", shadows: str | None = None)`.
- `MemoryIntent`: `src/forge/session/models.py:129-139` -- holds `designated_docs: list[DesignatedDoc]` and
  `auto_update: HandoffConfig | None`.
- `HandoffConfig`: `src/forge/session/models.py:79-99` --
  `(enabled: bool, mode: str, proxy: str | None, direct: bool, min_turns: int)`.
- Only `augment` and `review-only` are valid modes; `review_only` (underscore variant) is explicitly rejected by runtime
  validation (`_VALID_MODES` at `handoff_agent.py:400`) and by tests.

#### Stop-time update chain

Full path from session stop to doc update:

1. **Stop hook** (`src/forge/cli/hooks/commands.py:516-534`): checks `effective.memory.auto_update.enabled`, calls
   `enqueue_handoff_marker()`.
2. **Work queue** (`src/forge/core/workqueue/queue.py`): marker `kind="handoff"`, `marker_id="handoff-{session_id}"`.
   Payload includes session_name, worktree_path, transcript_snapshot_rel, subprocess_proxy, forge_root.
3. **CLI startup** (`src/forge/cli/main.py`): `_handoff_handler` spawns detached `forge handoff run` via
   `subprocess.Popen(start_new_session=True, stdout=DEVNULL)`. **Fire-and-forget**: once Popen succeeds, the marker is
   deleted. Detached handoff failures are not retried by the queue.
4. **CLI runner** (`src/forge/cli/handoff.py:23-111`): reads session manifest, calls `compute_effective_intent()`,
   resolves proxy via `resolve_handoff_base_url()`, invokes `run_handoff_agent()`.
5. **Agent core** (`src/forge/session/handoff_agent.py:349-504`): counts turns (min_turns gate), validates designated
   docs, validates mode, builds multi-doc prompt via `build_multi_doc_prompt()`, calls `run_claude_session()`, persists
   review report.

Strategy prompts: `DOC_STRATEGIES` dict at `handoff_agent.py:49-89`, prompt template at lines 91-167.

#### Handoff report/show surface

- CLI: `src/forge/cli/session_handoff.py` -- `handoff_group` with `show` command (`--latest` default, `--all`).
- Artifact path: `review_dir()` at `handoff_agent.py` returns `<forge_root>/.forge/artifacts/<session>/handoff/`.
- Report naming: `review-{YYYYMMDD-HHMMSS-micros}.md`.
- Report listing: `_list_reports()` reads `review_dir()`, sorts `review-*.md` by filename.
- This surface is read-only and separate from the handoff update agent.
- Tests: `tests/src/cli/test_session_handoff_show.py` -- belongs to the show surface, not the old memory config surface
  (KEEP during migration).

#### Old UX reference inventory

| Action | File                                                | What                                                                                                 |
| ------ | --------------------------------------------------- | ---------------------------------------------------------------------------------------------------- |
| UPDATE | `docs/status/README.md`                             | Setup commands (lines 28-32, 52-60, 66, 93-98)                                                       |
| UPDATE | `docs/design.md`                                    | Command table (lines 899-901), text (line 1604), DesignatedDoc schema (lines 1586-1594)              |
| UPDATE | `docs/end-user/handoff.md`                          | Old-model YAML config (lines 45-51, 74-79), CLI examples (lines 113-124), text (lines 148, 238, 271) |
| UPDATE | `docs/design_appendix.md`                           | Old example configuration G.2 (lines 701-726)                                                        |
| UPDATE | `tests/integration/cli/test_handoff_integration.py` | Shell commands (lines 330, 345)                                                                      |
| UPDATE | `src/skills/walkthrough/resources/checklist.md`     | Walkthrough items (lines 533-537)                                                                    |
| UPDATE | `src/skills/qa/resources/checklist/16-handoff.md`   | QA items (lines 26-48, 122-126)                                                                      |
| UPDATE | `tests/src/review/test_skill_content.py`            | Assertion (lines 479-485)                                                                            |
| REMOVE | `tests/src/cli/test_session_memory.py`              | Old surface tests (entire file)                                                                      |
| REMOVE | `src/forge/cli/session_memory.py`                   | Old CLI module (entire file)                                                                         |
| KEEP   | `src/forge/session/models.py`                       | DesignatedDoc, MemoryIntent, HandoffConfig                                                           |
| KEEP   | `src/forge/session/handoff_agent.py`                | Validation, strategies, agent core                                                                   |
| KEEP   | `tests/src/session/test_handoff_agent.py`           | Runtime agent tests                                                                                  |
| KEEP   | `tests/src/cli/test_session_handoff_show.py`        | Report/show surface tests                                                                            |
| KEEP   | `docs/proposals/memory_enhancement.md`              | Proposal source of truth                                                                             |

#### Helpers-stay-private decision

Reuse privately (import into new `forge memory` CLI, no public re-export):

- `is_safe_designated_doc_path()` from `handoff_agent.py` -- path safety.
- `DOC_STRATEGIES` dict from `handoff_agent.py` -- strategy definitions.
- `build_multi_doc_prompt()` from `handoff_agent.py` -- prompt building.
- `run_handoff_agent()` from `handoff_agent.py` -- agent execution.
- `review_dir()` from `handoff_agent.py` -- artifact paths.
- Session resolution pattern from `_current_docs()` -- reuse `resolve_session()` + `compute_effective_intent()`.
- Override persistence pattern from `_write_docs()` -- reuse `set_session_override()` mechanism.
- Validation pattern from `_validate_single_doc()` -- reuse with passport-aware extensions.

Move to shared location in Phase 1:

- `VALID_STRATEGIES` -- single source for CLI validation, passport validation, and handoff prompts.

**Tombstone decision**: no public compatibility aliases. In Phase 2, `forge session memory` becomes a non-executing
diagnostic path (hidden tombstone command) that fails with a helpful message naming the replacement
(`forge memory track`, `forge memory list`, etc.). It must not execute old behavior or produce a generic "unknown
command" dead end.
