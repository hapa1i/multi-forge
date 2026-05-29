# Memory Substrate — Execution Checklist

## Current Focus

Phase 0 complete (baseline verified this session). Decisions resolved. Ready for Phase 1.

## Summary

Resolve the "handoff" naming conflation: two unrelated concepts share the name — the **memory writer** (stop-time doc
updater) and **transfer context** (resume context assembly). This card renames the files, types, CLI surface, config
keys, and durable-state values, then syncs docs.

**Scope boundary:** this card is a *rename + taxonomy documentation* pass only. The 3-layer taxonomy (raw / project /
transfer — see `card.md`) lands as a docs table here; the *transfer-context schema/abstraction* (formal versioned
format, cross-runtime transfer) is deferred to `todo/runtime_abstraction/`. No new runtime abstractions in this card.

## Taxonomy (consistent vocabulary for the rename)

- **Memory writer** — the stop-time agent/module that updates project docs (`memory_writer.py`, `run_memory_writer`,
  `MemoryWriterConfig`, `memory_writer_timeout`).
- **Memory report** — the writer's per-run output artifact + its CLI (`memory_report_dir`, `forge memory report show`).
- **Transfer** — resume/fork context assembly (`transfer.py`, `assemble_transfer_context`, `TransferResult`,
  `--resume-mode transfer`).

## Blast radius (verified 2026-05-28)

Source: **207** `handoff` references across **32** Python files in `src/forge/`; **31** test files; **23** doc files
(includes this card's own files). Counts snapshotted for closeout diff.

Key files to rename:

| Current file                         | New file                                                      | Role                                                          |
| ------------------------------------ | ------------------------------------------------------------- | ------------------------------------------------------------- |
| `src/forge/session/handoff_agent.py` | `src/forge/session/memory_writer.py`                          | Stop-time doc updater (memory writer)                         |
| `src/forge/session/handoff.py`       | `src/forge/session/transfer.py`                               | Resume/fork context assembly (transfer)                       |
| `src/forge/cli/handoff.py`           | `src/forge/cli/memory_writer.py`                              | Detached CLI runner (`forge memory-writer run`)               |
| `src/forge/cli/session_handoff.py`   | tombstone in place **+ new** `src/forge/cli/memory_report.py` | `forge memory report show` (was `forge session handoff show`) |

> **Why not `git mv session_handoff.py → session_memory.py`?** `src/forge/cli/session_memory.py` already exists (a live
> tombstone group at `session_memory.py:12`, registered at `main.py:866,869`) and `forge session memory` already
> redirects to the top-level `forge memory`. The report command therefore moves to **`forge memory report show`** (new
> `cli/memory_report.py`, a `report_group` registered under the top-level `forge memory` group in `cli/memory.py`). The
> old `forge session handoff` path becomes its own tombstone pointing at the new command.

Key types/functions to rename:

| Current name                         | New name                              | Location                       |
| ------------------------------------ | ------------------------------------- | ------------------------------ |
| `HandoffConfig`                      | `MemoryWriterConfig`                  | `session/models.py:79`         |
| `HandoffResult`                      | `TransferResult`                      | `session/transfer.py`          |
| `process_handoff()`                  | `assemble_transfer_context()`         | `session/transfer.py`          |
| `run_handoff_agent()`                | `run_memory_writer()`                 | `session/memory_writer.py`     |
| `resolve_handoff_base_url()`         | `resolve_writer_base_url()`           | `session/memory_writer.py`     |
| `review_dir()`                       | `memory_report_dir()`                 | `session/memory_writer.py:516` |
| `_generate_parent_handoff_context()` | `_generate_parent_transfer_context()` | `cli/session.py:704`           |
| `handoff_timeout`                    | `memory_writer_timeout`               | `runtime_config.py:70`         |

Keep names (already self-descriptive / generic): `build_multi_doc_prompt()`, `count_conversation_turns()`.

## Resolved decisions

- **Single pass vs gradual** → **single-pass, atomic per layer** (session → CLI → config), each a separate commit with
  tests green. No gradual aliasing — research preview allows clean breaks (coding-standards §5).
- **Report CLI surface** → **`forge memory report show`** (top-level `forge memory`). Chosen over
  `forge session memory show` because that path is an occupied tombstone (see blast-radius note).
  `forge session handoff show` becomes a tombstone pointing to the new command.
- **`--resume-mode handoff`** → **rename to `--resume-mode transfer`** (in scope, Phase 2 + Phase 3). This is the most
  visible user-facing instance of the conflated term; it is also persisted as `confirmed.derivation.resume_mode`, so the
  value rename is a durable-state change (Phase 3).

---

## Phase 0: Baseline verification (COMPLETE — verified 2026-05-28)

- [x] Two-concept split confirmed: `handoff_agent.py` (writer) and `handoff.py` (transfer) share no functional code.
  - Verified: no cross-imports; the only mention is a disambiguation docstring in `handoff.py` pointing at
    `handoff_agent.py`. Symbol sets are disjoint (transfer: `process_handoff`, `HandoffResult`, `ResumeStrategy`,
    context generators; writer: `run_handoff_agent`, `build_multi_doc_prompt`, `resolve_handoff_base_url`,
    `review_dir`).
- [x] Public symbols mapped per file; each categorizes cleanly as writer or transfer (see type table above).
- [x] Durable-state fields identified:
  - `confirmed.derivation.resume_mode` — **persists the value `"handoff"`** (design.md §3.9). *Found during review; not
    in the original card.* Renaming the value to `"transfer"` requires stale-value handling (Phase 3).
  - Work queue: `enqueue_handoff_marker`, `kind="handoff"`, `marker_id="handoff-<session_id>"`
    (`core/workqueue/queue.py`). Markers are ephemeral (processed then deleted).
  - `handoff_timeout` in `runtime_config.py:70` (also referenced in `handoff_agent.py`).
- [x] CLI surface identified:
  - `forge handoff run` (hidden) — registered in `main.py`; spawned as a **detached Python subprocess from `main.py`**
    (the work-queue startup processor), *not* a hook/preset entry.
  - `forge session handoff show` (`handoff_group`, registered `main.py:868`).
  - **`--resume-mode handoff`** (`cli/session_lifecycle.py`, `click.Choice(["native", "handoff"])`). *Found during
    review; not in the original card's CLI inventory.*
  - `install/preset.py` references are **permission comments** ("Write/Edit … handoff agent"), not a command invocation.
    `capabilities.py:60` is a credential **description string**, not a permission entry.
- [x] Counts recorded (see Blast radius): 207 refs / 32 files; 31 test files; 23 doc files.

---

## Phase 1: Session-layer rename (core types + files)

Rename the session-layer files and types. Largest blast radius — every importer updates atomically in one commit.

- [ ] `git mv` session files:
  - `session/handoff_agent.py` → `session/memory_writer.py`
  - `session/handoff.py` → `session/transfer.py`
- [ ] Rename public types/functions in the new files (see type table). Includes `review_dir()` → `memory_report_dir()`
  (the returned path stays `.forge/artifacts/<session>/handoff/` — see Phase 3 path note).
- [ ] Rename internal symbols carrying the conflated term:
  - `cli/session.py:_generate_parent_handoff_context` → `_generate_parent_transfer_context` (+ local `handoff_result`
    vars in that function)
- [ ] Update all importers in `src/forge/` (atomic — every caller in same commit).
  - Assertion: `grep -rn "from forge.session.handoff\b\|from forge.session.handoff_agent\b" src/forge/` = 0 hits
  - Assertion: `grep -rn "HandoffConfig\|HandoffResult\|run_handoff_agent\|process_handoff" src/forge/` = 0 hits
- [ ] Update + rename test files (include the regression/integration tests the original card omitted):
  - `tests/src/session/test_handoff_agent.py` → `test_memory_writer.py`
  - `tests/src/session/test_handoff.py` → `test_transfer.py`
  - `tests/src/cli/test_handoff.py` → `test_memory_writer_cli.py`
  - `tests/regression/test_bug_21x_fork_launch_handoff.py` (imports `process_handoff`) — update imports/symbols
  - `tests/regression/test_bug_21x_handoff_output_root.py` (imports `process_handoff`) — update imports/symbols
  - `tests/regression/test_bug_handoff_forge_root.py` — update fixtures/imports as needed
  - `tests/integration/cli/test_handoff_integration.py` (uses `HandoffConfig`) — update imports/symbols

### Acceptance

| Test                    | Fixture   | Assertion                                                                          | Test File   |
| ----------------------- | --------- | ---------------------------------------------------------------------------------- | ----------- |
| No stale imports        | n/a       | `grep -rn "from forge.session.handoff\b\|handoff_agent" src/forge/` = 0 hits       | manual      |
| Types renamed           | n/a       | `grep -rn "HandoffConfig\|HandoffResult" src/forge/` = 0 hits                      | manual      |
| Unit + regression green | full repo | `uv run pytest tests/src tests/regression -m "not integration"` passes             | all         |
| Integration green       | Docker    | `uv run pytest tests/integration/cli/test_handoff_integration.py` passes (renamed) | integration |

> **Coverage note:** the original `pytest tests/src -m "not integration"` gate excludes `tests/regression/` and
> `tests/integration/`, where the omitted handoff tests live — broadened above so renamed-import breakage can't pass
> silently.

---

## Phase 2: CLI-layer rename (commands + runner)

- [ ] `git mv src/forge/cli/handoff.py` → `src/forge/cli/memory_writer.py`; rename `forge handoff run` →
  `forge memory-writer run` (hidden top-level command).
  - Update the **detached-spawn command string in `cli/main.py`** (the work-queue startup processor) and the hidden
    command registration. (There is **no** preset/hook-settings entry invoking `forge handoff run` — do not look for
    one.)
- [ ] Create `src/forge/cli/memory_report.py` with a `report_group` (`show`), register it under the top-level
  `forge memory` group (`cli/memory.py`). Move the report-display logic from `cli/session_handoff.py`.
  - Result: `forge memory report show` (with `--latest`, `--all`, name/UUID resolution, matching the old surface).
- [ ] Tombstone `forge session handoff show`: convert `cli/session_handoff.py`'s `handoff_group` to a tombstone group
  that exits non-zero with `Run 'forge memory report show'`. (Do not delete the registration — keep an actionable
  diagnostic per coding-standards §5 / §6.)
- [ ] Rename `--resume-mode handoff` → `--resume-mode transfer` in `cli/session_lifecycle.py`. Old value `handoff` is a
  rejected/tombstoned choice with guidance (durable-state acceptance handled in Phase 3).
- [ ] Update all CLI tests; rename `tests/src/cli/test_session_handoff_show.py` → `test_memory_report.py`.

### Acceptance

| Test                  | Fixture                       | Assertion                                                                     | Test File                 |
| --------------------- | ----------------------------- | ----------------------------------------------------------------------------- | ------------------------- |
| Old CLI tombstone     | session with a report on disk | `forge session handoff show` exits non-zero naming `forge memory report show` | `test_memory_report.py`   |
| New report CLI works  | session with a report on disk | `forge memory report show` resolves and prints the report                     | `test_memory_report.py`   |
| Hidden runner renamed | n/a                           | `forge memory-writer run --help` exits 0; `forge handoff run` gone            | manual                    |
| resume-mode renamed   | parent session, fresh resume  | `--resume-mode transfer` works; `--resume-mode handoff` errors with guidance  | `test_session_resume*.py` |
| Unit suite green      | full repo                     | `uv run pytest tests/src tests/regression -m "not integration"` passes        | all                       |

---

## Phase 3: Config and durable-state rename

Breaking changes — strict stale-state handling per coding-standards §5.

- [ ] `handoff_timeout` → `memory_writer_timeout` in `runtime_config.py:70`.
  - Runtime config is a user-edited system-boundary file; unknown keys warn+ignore per coding-standards §5 / system
    boundaries (`_dict_to_runtime_config` at `runtime_config.py:262`). Detect `handoff_timeout` on load: warn with
    `"handoff_timeout is renamed to memory_writer_timeout"`, ignore the old key. Make `forge config set handoff_timeout`
    and `forge config reset handoff_timeout` fail with actionable guidance naming the new key.
- [ ] `confirmed.derivation.resume_mode` value `"handoff"` → `"transfer"`. Durable state — old manifests carry
  `"handoff"`. Handle per §5: accept-and-migrate on read (preferred — manifests are long-lived) or reject with a clear
  reset message. Add a regression test for an old-value manifest.
- [ ] Work queue marker kind `handoff`: **keep as-is** (internal + ephemeral; markers are processed-then-deleted, so a
  kind rename risks stranding in-flight markers across upgrade for no user-visible gain). Record this decision; revisit
  only if the queue gains durability.
- [ ] Artifact path `.forge/artifacts/<session>/handoff/`: **keep** (renaming orphans existing artifacts). Note the
  intentional mismatch: `memory_report_dir()` returns a `…/handoff/` path. Add a code comment so a future reader does
  not "fix" one without the other.
- [ ] Update `install/preset.py` permission **comments** and `capabilities.py:60` credential **description string**
  (memory writer wording). These are strings/comments, not functional permission entries.
  - Assertion: `forge extension enable` still installs the same functional permission set (Write/Edit).

### Acceptance

| Test                   | Fixture                                         | Assertion                                                | Test File                                           |
| ---------------------- | ----------------------------------------------- | -------------------------------------------------------- | --------------------------------------------------- |
| Old config key warned  | `~/.forge/config.yaml` with `handoff_timeout`   | warns "renamed to memory_writer_timeout", ignores value  | `test_runtime_config.py`                            |
| New config key works   | config with `memory_writer_timeout: 120`        | value respected                                          | `test_runtime_config.py`                            |
| Stale resume_mode read | manifest with `derivation.resume_mode: handoff` | reads as `transfer` (migrate) or clear reset error       | `tests/regression/test_bug_*_resume_mode_rename.py` |
| Preset wording updated | fresh install                                   | preset comments reference memory writer; perms unchanged | `test_preset.py`                                    |

---

## Phase 4: Documentation sync

- [ ] `docs/design.md`:
  - §3.9 Session Resume: `--resume-mode handoff` → `transfer`; `derivation.resume_mode` value; "resume handoff" wording
  - §3.10 Hook handlers / §3.13 Work queue: memory-writer wording (marker kind kept — note it)
  - §5.6 + §5.6.1–5.6.7: "handoff agent" → "memory writer" throughout; update command table
    (`forge session handoff show` → `forge memory report show`)
  - Add the raw / project / transfer taxonomy table (from `card.md`)
  - Remove the §5.6 "Naming note" disambiguation block (no longer needed)
- [ ] `docs/design_appendix.md`: §C.3 (marker kinds), §G (memory doc reference)
- [ ] `docs/diagrams.md`: node `W6b "designated project docs (handoff agent)"` → "memory writer"; edge
  `fork / resume handoff` → "transfer". Marker-kind refs (`enqueues stop/index/handoff`, deferred-work queue list) stay
  (kind kept per Phase 3).
- [ ] `docs/end-user/handoff.md` → `docs/end-user/memory.md` (verified: no existing `memory.md`, rename is safe).
  - Update inbound links + writer wording: `docs/end-user/{session.md,hook.md,README.md,config.md,authentication.md}`
    and `docs/design.md`
- [ ] `docs/board/impl_notes.md`: memory-system architecture section (writer vs transfer vocabulary)
- [ ] Skill resources referencing handoff (`grep src/skills/`)
- [ ] Regression test docstrings referencing handoff concepts
- [ ] Fix stale contract references: the file is `docs/developer/board-contract.md`, but these cite
  `work-board-contract.md` — `CLAUDE.md` (×3, incl. the `@docs/developer/…` context-load directive, which is therefore
  **silently failing to load the board contract** into agent context), `AGENTS.md:15`, `docs/board/README.md:7` (link
  text only; href already points at `board-contract.md`), and `docs/board/change_log.md:9,26`. (Tangential to the
  rename, found during review.)

### Acceptance

| Test                     | Fixture | Assertion                                                                                                                                      | Test File |
| ------------------------ | ------- | ---------------------------------------------------------------------------------------------------------------------------------------------- | --------- |
| No stale "handoff agent" | n/a     | `rg -n "handoff agent" docs/design.md docs/design_appendix.md docs/end-user docs/developer docs/diagrams.md` = 0 hits                          | manual    |
| No stale resume wording  | n/a     | `rg -n "resume.*handoff\|--resume-mode handoff" docs/design.md docs/design_appendix.md docs/end-user docs/developer docs/diagrams.md` = 0 hits | manual    |
| Design doc accurate      | n/a     | taxonomy table present; command table shows `forge memory report show`                                                                         | review    |

---

## Phase 5: Closeout

- [ ] `make pre-commit` clean
- [ ] `uv run pytest tests/src tests/regression -m "not integration"` passes; integration handoff/memory tests pass
- [ ] Re-run blast-radius grep: residual `handoff` in `src/forge/` only where intentionally kept (marker kind, artifact
  path) — diff against the Phase 0 snapshot
- [ ] Add `change_log.md` entry (Goal / Key changes / Verification)
- [ ] Promote durable lessons to `impl_notes.md` (writer-vs-transfer taxonomy; the `session_memory` tombstone collision;
  `resume_mode` durable-value rename)
- [ ] Move card to `docs/board/done/memory_substrate/`
