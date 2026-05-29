# Memory Substrate — Execution Checklist

## Current Focus

**Phase 5 (closeout) is next.** Phases 0–4 are done. Phase 3 committed as `7fefbef`; Phase 4 (docs sync) is complete on
the working tree with a single `docs:` commit pending — every current/normative doc, end-user guide, diagram, skill, and
three test prose/path touches now use the memory-writer/transfer vocabulary, the 3-layer taxonomy table is in design.md
§5.6, and the obsolete "Naming note" block is gone. Intentional KEEPs (`kind="handoff"`, `enqueue_handoff_marker`, the
`handoff/` artifact path, `queued_handoff` field) are unchanged. Two pre-existing unrelated failures noted under Phase 3
are independent of this card. Remaining: commit Phase 4, then Phase 5 closeout (change_log entry, impl_notes promotion,
move card to `done/`).

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

## Phase 1: Session-layer rename (core types + files) — COMPLETE (committed c5b4822)

Rename the session-layer files and types. Largest blast radius — every importer updates atomically in one commit.

- [x] `git mv` session files:
  - `session/handoff_agent.py` → `session/memory_writer.py`
  - `session/handoff.py` → `session/transfer.py`
- [x] Rename public types/functions in the new files (see type table). Includes `review_dir()` → `memory_report_dir()`
  (the returned path stays `.forge/artifacts/<session>/handoff/` — see Phase 3 path note).
- [x] Rename internal symbols carrying the conflated term:
  - `cli/session.py:_generate_parent_handoff_context` → `_generate_parent_transfer_context` (+ local `handoff_result`
    vars in that function)
  - `cli/session_lifecycle.py:_persist_fork_handoff_derivation` → `_persist_fork_transfer_derivation` (+ `__all__`)
- [x] Update all importers in `src/forge/` (atomic — every caller in same commit).
  - Assertion: `grep -rn "from forge.session.handoff\b\|from forge.session.handoff_agent\b" src/forge/` = 0 hits
  - Assertion: `grep -rn "HandoffConfig\|HandoffResult\|run_handoff_agent\|process_handoff" src/forge/` = 0 hits
  - Also updated stale prose refs in `prev_sessions.py`, `plan_resolution.py`, `core/transcript.py`,
    `shadow_curation.py`, `cli/session_handoff.py` docstring, `cli/session_lifecycle.py` comment
- [x] Update + rename test files (14 files total):
  - `tests/src/session/test_handoff_agent.py` → `test_memory_writer.py`
  - `tests/src/session/test_handoff.py` → `test_transfer.py`
  - `tests/src/cli/test_handoff.py` → `test_memory_writer_cli.py`
  - `tests/regression/test_bug_21x_fork_launch_handoff.py` — updated imports/symbols
  - `tests/regression/test_bug_21x_handoff_output_root.py` — updated imports/symbols
  - `tests/regression/test_bug_prev_sessions_parent_scope.py` — updated imports/symbols
  - `tests/regression/test_bug_handoff_forge_root.py` — no change (marker kind only)
  - `tests/integration/cli/test_handoff_integration.py` — updated `HandoffConfig` → `MemoryWriterConfig`
  - `tests/src/cli/test_artifact_hooks.py` — updated `HandoffConfig` → `MemoryWriterConfig`
  - `tests/src/cli/test_session_commands.py` — updated patch targets
  - `tests/src/cli/test_session_derivation.py` — updated `_persist_fork_transfer_derivation`
  - `tests/src/cli/test_session_extensions.py` — updated imports + patch targets
  - `tests/src/cli/test_session_resume_review.py` — updated `HandoffResult` → `TransferResult`
  - `tests/src/session/test_memory_inheritance.py` — updated `HandoffConfig` → `MemoryWriterConfig`
  - `tests/src/session/test_models.py` — updated `HandoffConfig` → `MemoryWriterConfig`

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

## Phase 2: CLI-layer rename (commands + runner) — COMPLETE (committed 971741c + af742f5)

> **Landed as two commits.** 2a (`971741c`) = CLI surface; 2b (`af742f5`) = the `--resume-mode` value rename, which also
> carried three durable-state items the card had slotted under Phase 3 (see Phase 3 notes).

- [x] `git mv src/forge/cli/handoff.py` → `src/forge/cli/memory_writer.py`; renamed `forge handoff run` →
  `forge memory-writer run` (hidden top-level command).
  - Verified: `cli/memory_writer.py:18` `@click.group("memory-writer", hidden=True)` + `.command("run")`; the detached
    work-queue spawn argv in `cli/main.py:177` is now `"memory-writer"`. Handler keyed by the kept marker kind
    (`main.py:206` `"handoff": _memory_writer_handler`).
- [x] Created `src/forge/cli/memory_report.py` with a `report_group` (`show`), registered under the top-level
  `forge memory` group; report-display logic moved off `cli/session_handoff.py`.
  - Verified: `cli/memory.py:1233-1235` imports `report_group` + `memory.add_command(report_group)`;
    `forge memory report show` supports name/UUID + `--latest`/`--all`.
- [x] Tombstoned `forge session handoff show`: `cli/session_handoff.py:23-27` `_tombstone_show` raises
  `ClickException("...Use: forge memory report show")`; registration kept (actionable diagnostic per §5/§6).
- [x] Renamed `--resume-mode handoff` → `--resume-mode transfer` (`cli/session_lifecycle.py`).
  - Verified: `_validate_resume_mode` (`:332`) rejects `handoff` with
    `BadParameter("'handoff' was renamed to 'transfer'. Use --resume-mode transfer.")`; `effective_resume_mode` defaults
    to `transfer`.
- [x] Renamed CLI tests; `tests/src/cli/test_session_handoff_show.py` → `test_memory_report.py` (git rename verified);
  `test_memory_writer_cli.py` + `tests/integration/cli/test_handoff_integration.py` repointed.

### Acceptance

| Test                  | Fixture                       | Assertion                                                                     | Test File                 |
| --------------------- | ----------------------------- | ----------------------------------------------------------------------------- | ------------------------- |
| Old CLI tombstone     | session with a report on disk | `forge session handoff show` exits non-zero naming `forge memory report show` | `test_memory_report.py`   |
| New report CLI works  | session with a report on disk | `forge memory report show` resolves and prints the report                     | `test_memory_report.py`   |
| Hidden runner renamed | n/a                           | `forge memory-writer run --help` exits 0; `forge handoff run` gone            | manual                    |
| resume-mode renamed   | parent session, fresh resume  | `--resume-mode transfer` works; `--resume-mode handoff` errors with guidance  | `test_session_resume*.py` |
| Unit suite green      | full repo                     | `uv run pytest tests/src tests/regression -m "not integration"` passes        | all                       |

---

## Phase 3: Config and durable-state rename — COMPLETE (committed 7fefbef)

Breaking changes — strict stale-state handling per coding-standards §5.

- [x] `handoff_timeout` → `memory_writer_timeout` in `runtime_config.py` (field, validation, default-content comment).
  - Done: field/validation renamed; read site updated at `session/memory_writer.py:50`. Added `_RENAMED_KEYS` map;
    `_dict_to_runtime_config` emits a targeted "was renamed to 'memory_writer_timeout' … is ignored" warning (old value
    degrades to default, not migrated) instead of the generic unknown-key line. `forge config set/reset handoff_timeout`
    fail via `print_error_with_tip` naming the new key; both also auto-prune a lingering `handoff_timeout` on write so
    following the tip converges the file (the `edit` raw surface is left alone). Tests: `test_runtime_config.py`
    (warned-and-ignored + new-key-works) and `test_config_cli.py` (reject + stale-prune for both set and reset).
- [x] `confirmed.derivation.resume_mode` value `"handoff"` → `"transfer"` — **done in Phase 2b (`af742f5`)**.
  - Chose accept-and-tolerate over reject: `session/models.py:334-348` reads legacy `"handoff"`/`None` as transfer with
    no reader branching; writers emit `"transfer"`. Regression `tests/regression/test_bug_resume_mode_rename.py` covers
    an old-value manifest.
- [x] Work queue marker kind `handoff`: **kept as-is** — decision recorded in Phase 2a.
  - Verified: `cli/main.py:204-206` keeps `kind="handoff"` (ephemeral routing key) with an explanatory comment.
- [x] Artifact path `.forge/artifacts/<session>/handoff/`: **kept** — done in Phase 2a.
  - Verified: `session/memory_writer.py:515-516` keeps the `…/handoff/` path with a comment flagging the intentional
    mismatch vs the renamed `memory_report_dir()`.
- [x] Updated `install/preset.py` permission **comments** (`:9,38`) and `capabilities.py:60` credential **description
  string** to "memory writer". Functional permission set unchanged (Write/Edit).
  - Done: grep gate `rg "handoff agent" src/forge/install/preset.py src/forge/core/auth/capabilities.py` = 0. Test
    mirrors updated: `test_capabilities.py::test_unlocks_features_shown` asserts "memory writer";
    `test_preset.py::test_has_write_edit_permissions` docstring updated (perms assertion unchanged).

### Acceptance

| Test                   | Fixture                                         | Assertion                                                | Test File                                           |
| ---------------------- | ----------------------------------------------- | -------------------------------------------------------- | --------------------------------------------------- |
| Old config key warned  | `~/.forge/config.yaml` with `handoff_timeout`   | warns "renamed to memory_writer_timeout", ignores value  | `test_runtime_config.py`                            |
| New config key works   | config with `memory_writer_timeout: 120`        | value respected                                          | `test_runtime_config.py`                            |
| Stale resume_mode read | manifest with `derivation.resume_mode: handoff` | reads as `transfer` (migrate) or clear reset error       | `tests/regression/test_bug_*_resume_mode_rename.py` |
| Preset wording updated | fresh install                                   | preset comments reference memory writer; perms unchanged | `test_preset.py`                                    |

---

## Phase 4: Documentation sync — COMPLETE (working tree; single `docs:` commit pending)

Synced every current/normative doc to the shipped memory-writer/transfer vocabulary. Historical snapshots
(`change_log.md` dated entries, `done/**`, this card's own `card.md`) intentionally retain "handoff" as accurate record.

- [x] `docs/design.md`: §3.9 "Phase 1: Handoff" → "Phase 1: Capture"; `--resume-mode handoff` → `transfer`;
  `resume_mode` value + "resume handoff"/"handoff file(s)" wording → transfer; §3.10/§3.13 narrative "enqueue
  memory-writer work" (the real `enqueue_handoff_marker` / `kind="handoff"` stay only where the marker itself is
  discussed); §4.0 moved `forge session handoff show` → `forge memory report show` into the memory-management table;
  §5.6 "Naming note" block removed and replaced with the 3-layer taxonomy table (raw / project / transfer); stale
  symbols fixed (`process_handoff`→`assemble_transfer_context`, `run_handoff_agent`→`run_memory_writer`,
  `HandoffConfig`→`MemoryWriterConfig`, `handoff_agent.py`→`memory_writer.py`).
- [x] `docs/design_appendix.md`: `handoff_timeout`→`memory_writer_timeout`; §C.3 marker row description → "Spawn the
  memory writer" (KEEP `kind="handoff"`); `handoff_agent.py`→`memory_writer.py`; §G strategy wording.
- [x] `docs/diagrams.md`: node `Handoff` / `W6b` → "Memory Writer" / "(memory writer)"; edge "resume handoff" → "resume
  transfer". Marker edge `enqueues stop/index/handoff` KEPT (kind).
- [x] `git mv docs/end-user/handoff.md docs/end-user/memory.md`; title → "Forge Memory Writer"; disambiguation block →
  one-line transfer pointer; CLI refs → `forge memory report show` / `forge memory-writer run`. KEEP marker prose +
  `handoff/` path. Repointed 5 inbound links (`design.md`, end-user `README.md`/`hook.md`/`config.md`/`session.md`).
- [x] `docs/end-user/*` sweep: `config.md` `memory_writer_timeout` row; `session.md` resume-mode + transfer wording;
  `hook.md`, `authentication.md`, `README.md`, `model-selection.md` (incl. `handoff_agent.py`→`memory_writer.py` path).
- [x] Current board + agent-context docs (review finding): `docs/board/impl_notes.md` (vocabulary);
  `docs/board/README.md` (`forge memory report show`, transfer wording); `docs/developer/board-contract.md`
  (memory-writer wording; KEEP "handoff marker exists" example); `CLAUDE.md:127` `resume/handoff`→`resume/transfer`;
  `change_log.md:7` maintenance header (dated entries below stay historical).
- [x] `docs/board/todo/runtime_abstraction/**` (parked future work): fixed stale code/command surfaces
  (`handoff_agent.py`→`memory_writer.py`, `session/handoff.py`→`session/transfer.py`, concrete component refs) and added
  a deferred checklist item to reconcile the aspirational "curated handoff" vocabulary +
  `forge session handoff regenerate|edit|diff` surface with this taxonomy when that card executes. The "curated handoff"
  thesis is left intact.
- [x] Skills full rename: `git mv 16-handoff.md` → `16-memory.md` + QA index link/section comment;
  `## 16. Handoff Agent` → `## 16. Memory Writer` + subsection/prose; `SKILL.md` category token + skip note + reference
  table; `report-template.md`; `5-session.md`/`10-resume.md` transfer wording; `walkthrough/resources/checklist.md:524`.
  KEEP fixture filenames, `handoff-${SESSION_ID}.json` marker, `handoff/` path, `queued_handoff` field.
- [x] Test prose/paths: `test_skill_content.py` (`16-memory.md` ×3, `TestQaMemoryWriterChecklist`, `memory_md` var,
  `test_memory_*` methods; KEEP `queued_handoff` + the `"forge handoff run" not in code` negative assertion);
  `test_models.py` class+docstring+var; `test_bug_handoff_forge_root.py` docstring (KEEP file name + marker symbol).

> The Phase 4 plan's "fix stale `work-board-contract.md` references" line was already resolved by `226bba5` (it touched
> `CLAUDE.md`, `AGENTS.md`, `docs/board/README.md`, `docs/board/change_log.md`); the only remaining mention is this
> checklist's own description, so the item is dropped rather than re-ticked under this commit.

### Acceptance

| Test                     | Fixture | Assertion                                                                                                                                                                               | Test File |
| ------------------------ | ------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------- |
| No stale "handoff agent" | n/a     | `rg -ni "handoff[ -]agent" docs/design.md docs/design_appendix.md docs/diagrams.md docs/end-user docs/developer docs/board/impl_notes.md docs/board/README.md CLAUDE.md src/skills` = 0 | manual    |
| No stale symbols         | n/a     | `rg -n "process_handoff\|run_handoff_agent\|resolve_handoff_base_url\|handoff_agent\.py\|HandoffConfig\|HandoffResult"` over current docs = 0                                           | manual    |
| No stale resume wording  | n/a     | `rg -ni -- "--resume-mode handoff\|resume_mode: handoff"` over current docs = 0                                                                                                         | manual    |
| Renamed CLI in docs      | n/a     | `rg -ni "forge session handoff show\|forge handoff run"` over current docs + `src/skills` = 0                                                                                           | manual    |
| Renames landed           | n/a     | `memory.md` / `16-memory.md` exist; `handoff.md` / `16-handoff.md` gone                                                                                                                 | manual    |
| KEEPs intact             | n/a     | `kind="handoff"`, `enqueue_handoff_marker`, `artifacts/<session>/handoff`, `queued_handoff` unchanged in `src/forge/`                                                                   | manual    |
| Design doc accurate      | n/a     | §5.6 taxonomy table present; "Naming note" block removed; command table shows `forge memory report show`                                                                                | review    |
| Touched tests green      | repo    | `uv run pytest tests/src/review/test_skill_content.py tests/src/session/test_models.py tests/regression/test_bug_handoff_forge_root.py` passes (142)                                    | all       |

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
