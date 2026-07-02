# Checklist — Rewind Resume Strategy

Execution plan for `card.md` (this dir). Branch: `rewind-resume-strategy`. See `card.md` for motivation, the decided
design points, and risks; this file is the ordered execution plan with observable assertions.

## Current focus

**Slice 3 complete; next up is Slice 4.** The turn-window prefix writer and code-delta primitive are in place with
focused unit coverage. Slice 4 now needs to expose `--strategy rewind --drop-last N`, write the context artifact, and
co-deliver it with native-relocate launch.

## Verified code anchors (re-checked 2026-07-01, card line numbers had drifted)

These were confirmed against the current tree by read-only verification. Use these, not the card's numbers.

| Symbol / behavior                                                                                                | Location (verified)                                                                                           | Note                                                                                                                                         |
| ---------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------- |
| `ResumeStrategy` enum (`MINIMAL/STRUCTURED/FULL/AI_CURATED`)                                                     | `session/transfer.py:101-107`                                                                                 | canonical def; imported elsewhere                                                                                                            |
| Strategy dispatch (structured/full/ai-curated)                                                                   | `session/transfer.py:1200-1229`                                                                               | no `native` branch — dispatch is transfer-only                                                                                               |
| `_generate_ai_curated_context` (falls back to `_generate_structured_context` on parse fail)                      | `session/transfer.py:962`                                                                                     |                                                                                                                                              |
| `_call_llm_for_curation_prompt` / `_call_llm_for_curation` / `_emit_curation_usage` (emit **before** parse gate) | `session/transfer.py:671-787`, emit at `1028-1029`; rewind emit at `rewind.py:368`                            | OpenRouter direct via `SyncAdapter(get_client(...))`                                                                                         |
| `_validate_decision_citations` (drops citations outside `emitted_turns`)                                         | `session/transfer.py:819-844`                                                                                 |                                                                                                                                              |
| `_format_transcript_for_llm` + `_group_entries_into_turns` (`[turn N]` anchors)                                  | `session/transfer.py:600-652`                                                                                 | turns grouped by `requestId`, fallback to user-initiated sequences                                                                           |
| `AI_CURATION_SYSTEM_PROMPT` (untrusted-transcript) / `AI_CURATION_USER_PROMPT_TEMPLATE`                          | `session/transfer.py:72-77` / `83-98`                                                                         |                                                                                                                                              |
| `assemble_transfer_context` (entry, returns `TransferResult`)                                                    | `session/transfer.py:1090`                                                                                    |                                                                                                                                              |
| `Derivation` dataclass (14 fields; `strategy` default `"structured"`)                                            | `session/models.py:441-486`                                                                                   | **no SCHEMA_VERSION on `Derivation`** — it lives on `SessionState` (`:21`)                                                                   |
| "Null for native resumes" note                                                                                   | `session/models.py:456-459` (docstring only)                                                                  | convention, **not** an enforced guard; `rewind` is now the documented exception                                                              |
| `--strategy` Choice `[minimal,structured,full,ai-curated]`                                                       | `cli/session_fork.py:140`                                                                                     |                                                                                                                                              |
| `--resume-mode` Choice `[transfer,native-relocate]`                                                              | `cli/session_fork.py:165`                                                                                     |                                                                                                                                              |
| native-relocate preflights (4 rejections)                                                                        | `cli/session_fork.py:489-556`                                                                                 | `--no-launch`, sidecar, parent-has-transcript, `--into` CWD-differs; worktree check is at runtime                                            |
| strategy populated for transfer forks only                                                                       | `cli/session_lifecycle.py:309` (`_persist_fork_transfer_derivation`), gated by `uses_fresh_transfer` (`:947`) | native-relocate leaves `strategy=None` **by omission**                                                                                       |
| native-relocate copy + derivation write; `relocated_parent_session_id = parent.claude_session_id`                | `session/manager.py:1364-1395` (id at `:1382`)                                                                |                                                                                                                                              |
| relocate GC / reference-count via `_find_shared_transcript_sessions` (keys on `relocated_parent_session_id`)     | `session/manager.py:1818-1855`                                                                                | deletes copy iff no other session references that id                                                                                         |
| shared-transcript id extraction includes rewind id                                                               | `session/manager.py:106-147`                                                                                  | forward-looking additive support for `rewind_relocated_session_id` until the writer lands                                                    |
| rewind raw-prefix writer                                                                                         | `session/rewind.py`                                                                                           | preserves selected JSONL text; snaps positive drops to a complete `tool_use`/`tool_result` boundary and rejects non-contiguous turn prefixes |
| rewind code-delta primitive                                                                                      | `session/rewind.py:206-408`                                                                                   | extracts dropped-window code-edit tool calls, reconciles net-by-file, renders `rewind-code-delta`, and emits parse-failure usage             |
| `relocate_transcript` — **pure byte copy**, `rewrite_paths` raises `NotImplementedError`                         | `session/claude/relocate.py:71-171` (paths `104-108`)                                                         | never touches entries' internal `sessionId`                                                                                                  |
| `RelocateConflictError` (dest differs, no overwrite) / `RelocateSameDirError` (src==dst dir)                     | `session/claude/relocate.py:34-46`                                                                            |                                                                                                                                              |
| Destination path `get_transcript_path(root, uuid)` → `<uuid>.jsonl`                                              | `relocate.py:110-114`, `session/claude/paths.py:79-94`                                                        | stem == UUID today                                                                                                                           |

## Refinements from verification (feed these into the slices)

1. **The "invariant" is a convention, not a guard.** No code asserts `strategy null ⟺ native`. A manifest with
   `strategy="structured"` + `resume_mode="native"` loads without error today. Slice 1's audit is therefore about **read
   sites that *assume* the convention** (status/derivation readers, launch-path branching), plus adding the *write* path
   — not removing a guard that does not exist.
2. **No precedent for stem ≠ internal `sessionId`.** `relocate_transcript` always produces `<uuid>.jsonl` whose stem
   equals the entries' embedded `sessionId`. The fresh-UUID `R` design is the first mismatch case, so the probe (does
   `claude --resume R` tolerate stem ≠ embedded `sessionId`?) has zero in-tree precedent and must be run live.
3. **GC field decision is closed.** `_find_shared_transcript_sessions` keeps `relocated_parent_session_id` for the
   parent UUID used by byte-for-byte native-relocate. `rewind` gets a distinct `rewind_relocated_session_id` for the
   fresh truncated-copy UUID `R`; `_tracked_derivation_transcript_session_ids` already extracts it from dataclass and
   raw-dict derivations.

---

## Slice 1 — Decision + invariant + probe (GATE)

**Goal:** Lock the durable shape and the launch-combo decision, and settle the one empirical unknown, before any
plumbing. Nothing below this line proceeds until this slice is reviewed.

- [x] **`sessionId`-match probe (empirical, blocking).** Write a whole parent JSONL copy under a fresh stem `R` and run
  `claude --resume R --fork-session` against it. **Assertion:** record one of — (a) resume succeeds with stem `R` ≠
  embedded `sessionId` (no envelope rewrite needed), or (b) it fails with "No conversation found"/similar and only
  succeeds after rewriting the envelope `sessionId` to `R` while leaving signed `thinking`/`tool_result` blocks
  byte-intact and signatures revalidating. Capture the exact failure text and the working recipe in `card.md` or an
  `impl_notes` proposal. This is a `relocate.py`-style live pin — unit tests cannot answer it.
- [x] **Probe result:** Claude Code 2.1.197, isolated `HOME`, parent `parent_has_signature=yes`, copied parent JSONL to
  child encoded dir as `<R>.jsonl` with embedded `sessionId=<parent_uuid>`, then ran
  `claude --bare --print --allowed-tools Read --permission-mode bypassPermissions --resume R --fork-session`. Result:
  `mismatch_exit=0`, parent copy unchanged. **No envelope rewrite needed.** This proves stem tolerance only; a truncated
  clean-prefix `<R>.jsonl` remains a Slice 5 integration assertion.
- [x] **`Derivation` shape decision.** Decide and document: `strategy="rewind"` coexisting with
  `resume_mode="native-relocate"`; a new `dropped_turns: int | None = None`; and the closed GC-id field decision
  (refinement #3 above — use `rewind_relocated_session_id`). **Assertion:** the chosen field set is written into
  `card.md` and reflected as `Derivation` field additions; confirm additive-optional fields load under the existing
  strict `SessionState` reader without a `SCHEMA_VERSION` bump (precedent: consumer_lanes T4 additive-no-bump), and add
  a strict-read test that a `rewind` derivation round-trips.
- [x] **Shape result:** keep `relocated_parent_session_id` for byte-for-byte native-relocate's parent UUID; add
  `dropped_turns` and `rewind_relocated_session_id`. Strict store round-trip is covered by
  `tests/src/session/test_models_derivation.py::TestDerivationDataclass::test_rewind_derivation_strict_store_roundtrip`.
  The extraction branch is forward-looking until Slice 4/5 writes `rewind_relocated_session_id`; Slice 1 only proves the
  reader shape.
- [x] **Read-site audit.** Enumerate every site that reads `Derivation.strategy`/`resume_mode` and assumes "native ⟹ no
  context file" or "strategy null ⟹ native" — status renderers, `session show`, launch-path branching in
  `session_lifecycle.py`, GC. **Assertion:** produce a concrete list (file:line) of sites that must tolerate
  `native-relocate` + non-null `strategy` + non-null `context_file`, with the required change per site.
- [x] **Read-site audit result:** `session_lifecycle.py:223-224` only suppresses deferred same-dir native resume for
  `resume_mode=="transfer"`; same-dir rewind must be rejected before this path. `session_lifecycle.py:296-312` hardcodes
  transfer derivation persistence; Slice 4 needs a rewind-specific writer or mode-aware extension.
  `session_lifecycle.py:332-350` resolves `context_file` regardless of mode; OK for rewind.
  `session_lifecycle.py:1829-1903` can already pass both `resume_id`/`fork_session` and a combined prompt file, but
  Slice 4 must set `resume_id=R` and avoid the fresh `session_id` pre-seed path. `session_lifecycle.py:2223-2232` is
  transfer-result-specific fresh resume launch plumbing; Slice 4 needs a rewind branch. `session/manager.py:955-973`
  retry/orphan handling is transfer-only; any rewind context file written before index reservation needs equivalent
  orphan/rename handling. `manager.py:1369-1393` writes `strategy=None`/`context_file=None` for native-relocate; Slice 4
  must populate rewind fields. `manager.py:1823-1842` deletes only byte-for-byte native-relocate copies via
  `relocated_parent_session_id`; Slice 5 must unlink `rewind_relocated_session_id` independently.
  `core/ops/gc.py:250-259` protects any `Derivation.context_file` regardless of mode; OK. `cli/session_manage.py:900`
  emits derivation via `asdict`; OK, with an additive JSON shape change: non-rewind sessions now show null
  `dropped_turns` and `rewind_relocated_session_id`.
- [x] **design.md contract update.** Update the resume-mode × strategy matrix in `docs/design.md` §3.9 to add the
  `rewind` row (native-relocate + `strategy="rewind"` + context file). **Assertion:** the matrix documents the
  shipped-or-committed shape and names the convention-not-guard status.

**Blocker/decision resolved:** Slices 2–6 are now gated only on review of this Slice 1 result. Slice 5 does **not** need
an envelope `sessionId` rewrite; Slice 4 writes `strategy="rewind"`, `dropped_turns=N`, `context_file=<delta>`, and
`rewind_relocated_session_id=R`.

## Slice 2 — Turn window + safe truncation

**Goal:** Split the parent transcript at turn `T−N` on a coherent boundary and write a truncated JSONL prefix.

- [x] **Turn split at `T−N`.** Reuse `_group_entries_into_turns` (`transfer.py`) to define the boundary; `N` counts
  turns, not JSONL lines. **Assertion:** given a parent with `T` turns and `--drop-last N`, the writer selects entries
  belonging to turns `1..(T−N)`.
- [x] **Safe truncation writer.** Snap the cut to the last complete turn ≤ `T−N` so no `tool_use`/`tool_result` pair is
  split. **Assertion:** a fixture with a tool-call pair straddling the cut produces a JSONL that ends on a complete turn
  (unit-assert the last entries form a closed turn; no dangling `tool_use` without its `tool_result`).
- [x] **Degenerate cases.** Pin `N=0` manifest semantics: downgrade to null-strategy native-relocate with no
  `dropped_turns`, no `context_file`, and no `rewind_relocated_session_id`. Pin writer-level `N>=T` semantics as
  `kept_turns=0` plus an empty prefix. **Assertion:** both primitive paths are unit-tested; Slice 4 must reject or fall
  back before launch because an empty prefix is not a native-resume head.
- [x] **Writer-level degenerate behavior:** `drop_last=0` copies the source unchanged and reports no snap/drop;
  `drop_last>=T` writes an empty prefix and reports `actual_dropped_turns=total_turns`. Slice 4 should bypass the rewind
  writer for `N=0` and use plain native-relocate; it must not call `claude --resume` against the empty `N>=T` artifact.
- [x] **Contiguous raw-prefix guard:** requestId-interleaved transcripts are rejected before writing if the raw cutoff
  would include entries from a dropped turn. This documents the real-Claude append-contiguous assumption and fails
  closed if a transcript violates it.

## Slice 3 — Code-delta extractor + prompt

**Goal:** Produce a grounded, net-change code-delta over only the dropped window `(T−N)..T`.

- [x] **Tool-call delta.** Extract `Edit`/`Write`/`MultiEdit`/`NotebookEdit` calls within the dropped window.
  **Assertion:** `extract_rewind_file_deltas` and `build_rewind_code_delta_source` tests prove delta entries reference
  only turns after the actual kept-turn boundary; no head tool calls are included.
- [x] **Net-change reconciliation.** Multiple edits to one file collapse to the net delta (later supersedes earlier).
  **Assertion:** `test_code_delta_reconciles_multiple_edits_to_one_file` yields one file delta with the latest tool-call
  summary and an operation count of 2.
- [x] **Prompt + grounding reuse.** Narrowed variant of `AI_CURATION_USER_PROMPT_TEMPLATE` (files changed + what/why,
  net effect, dangling edits) with the explicit "files already contain these; conversation is rewound to before them"
  framing; reuse `_validate_decision_citations`, `AI_CURATION_SYSTEM_PROMPT` (injection hardening), and the
  `_emit_curation_usage` emit-before-parse-gate. **Assertion:** `generate_rewind_code_delta_context` strips
  out-of-window citations, returns schema marker `rewind-code-delta` on success, and emits a `rewind-code-delta` usage
  event with `status="error"` for unparseable AI output before deterministic fallback.

## Slice 4 — Wire the strategy

**Goal:** Surface `--strategy rewind --drop-last N` and co-deliver a context file with a native-relocate launch.

- [x] **`ResumeStrategy.REWIND` + Choice.** Add the enum member and the `--strategy` Choice value on fork and resume;
  add required `--drop-last N` (no default; non-negative integer). **Assertion:** `--strategy rewind` without
  `--drop-last` errors, negative values fail validation without reaching the writer, and `rewind` resolves
  `resume_mode=native-relocate` (worktree/`--into` only).
- [x] **Co-deliver context file with native-relocate launch (the convention extension).** Extend the strategy-population
  path (currently `_persist_fork_transfer_derivation` gated by `uses_fresh_transfer`, `session_lifecycle.py:309/947`) so
  a rewind fork writes `strategy="rewind"`, `dropped_turns=N`, `context_file=<delta>` AND the launch emits
  `--resume --fork-session` together with `--append-system-prompt-file`. **Assertion:** the launched argv for a rewind
  worktree fork contains both flags (unit-assert on the built command).
- [x] **Shared dropped-window turn numbering.** Wire the prefix writer and code-delta generator from the same raw-order
  turn grouping. Do not pass `RewindPrefixResult.kept_turns` into a separately re-parsed timestamp-sorted transcript:
  `write_rewind_transcript_prefix` currently counts raw JSONL-order dict entries, while `parse_jsonl_transcript` sorts
  by timestamp and skips entries without `message`/`type`. If the two-parser shape remains temporarily, add a guard that
  proves both parsers produce the same turn count/order before launch and otherwise falls back with a note.
  **Assertion:** a fixture with file order != timestamp order, plus a metadata-only dict line, proves the delta window
  matches the prefix writer's dropped window.
- [x] **Degenerate and snap-back UX.** Handle the writer result before launch: `drop_last=0` uses the plain
  native-relocate no-op, `kept_turns=0` rejects or falls back instead of launching an empty transcript, and
  `kept_turns < requested_keep_turns` tells the user how many additional turns the safe-boundary snap dropped. Catch
  defensive writer `ValueError`s (for example, a non-contiguous transcript prefix) and fall back to plain
  native-relocate with a note rather than surfacing a traceback. **Assertion:** unit coverage proves each branch
  surfaces the correct user-facing message.
- [x] **Same-dir / sidecar rejection.** **Assertion:** `--strategy rewind` on a same-dir or sidecar fork is rejected
  with the existing native-relocate-only guidance (reuse the `session_fork.py:489-556` preflight messages).

## Slice 5 — Identity + cleanup

**Goal:** Fresh-UUID unshared truncated copy that GC deletes cleanly without touching parent/siblings.

- [ ] **Fresh rewind-owned UUID `R`.** Write the truncated copy as `<R>.jsonl` in the child's encoded dir; launch
  `--resume R --fork-session`. Apply the Slice-1 probe outcome: keep embedded parent `sessionId`; no envelope rewrite.
  **Assertion:** `R ≠ parent_uuid`; the parent's original `<parent_uuid>.jsonl` is never written or overwritten.
- [ ] **Unshared cleanup.** Record the relocated id per the Slice-1 GC-field decision so
  `_find_shared_transcript_sessions` finds no siblings sharing `R`. Add the delete-time unlink branch for
  `derivation.rewind_relocated_session_id` in `manager.py` independently of the existing `relocated_parent_session_id`
  branch: it must be dir-scoped to the child's resolved Claude project root, unshared by design, and keyed only on `R`
  so same-directory resume rewind can never touch the parent's original UUID. **Assertion:** deleting the rewind session
  unlinks `<R>.jsonl`; a fixture with a sibling/parent in the same encoded dir confirms neither is touched.

## Slice 6 — Fallback + privacy + docs

**Goal:** Degrade safely on AI failure, warn on external send, and sync all normative docs.

- [ ] **Fallback.** On code-delta LLM failure, fall back to plain native-relocate + a "code-delta unavailable" note;
  resume still works. **Assertion:** LLM-error fixture yields a working native-relocate resume with the note.
- [ ] **Privacy warning.** Surface "dropped-window code/transcript sent to `<model>`" (same posture as `ai-curated`).
  **Assertion:** the warning is emitted on any rewind run.
- [ ] **Docs.** Update `docs/design.md` §3.9 (matrix from Slice 1 finalized to shipped state), `docs/design_appendix.md`
  §H (schema marker/frontmatter), `docs/cli_reference.md` (fork/resume `--strategy rewind --drop-last`), and
  `docs/end-user/transfer.md`. Make the fork/resume asymmetry explicit: fork rewind is worktree/`--into` only and
  rejects same-dir/sidecar; `resume --fresh --strategy rewind` is legitimately same-directory because it resumes the
  fresh truncated UUID `<R>`, not the parent's UUID. **Assertion:** each doc reflects shipped behavior, not aspiration.

---

## Acceptance tests

| Test                                  | Fixture                                    | Assertion                                                                                          | Test File                                   |
| ------------------------------------- | ------------------------------------------ | -------------------------------------------------------------------------------------------------- | ------------------------------------------- |
| Truncated relocate carries head       | parent with T turns, `--drop-last N`       | child JSONL has turns 1..T−N, none of T−N+1..T                                                     | `tests/src/session/test_rewind_strategy.py` |
| Truncation snaps to safe boundary     | tool_use/result pair straddling T−N        | relocated JSONL ends on a complete turn (resume not corrupted)                                     | same                                        |
| Delta cites only dropped turns        | edits in the dropped window                | delta lists changed files citing turns T−N+1..T; no head citations                                 | same                                        |
| Native resume + context file together | `--strategy rewind` worktree fork          | launched argv carries `--resume --fork-session` AND `--append-system-prompt-file`                  | `tests/src/cli/test_session_commands.py`    |
| Prefix and delta share dropped window | out-of-timestamp-order JSONL + metadata    | code-delta describes exactly the turns removed by the prefix writer                                | same                                        |
| Empty head is not launched            | `--drop-last >= T`                         | CLI rejects or falls back before running `claude --resume` against an empty `<R>.jsonl`            | `tests/src/cli/test_session_commands.py`    |
| Safe-boundary snap is disclosed       | snap keeps fewer turns than requested      | user-facing output says how many additional turns the snap dropped                                 | `tests/src/cli/test_session_commands.py`    |
| Writer failure falls back             | non-contiguous transcript prefix           | plain native-relocate fallback + note; no traceback                                                | `tests/src/cli/test_session_commands.py`    |
| Resume tolerates fresh UUID           | rewind launch, truncated fresh `<R>.jsonl` | child resumes from clean-prefix `<R>` with embedded parent `sessionId`; no "No conversation found" | integration (real `claude`)                 |
| Manifest records rewind               | `--drop-last N`                            | `resume_mode=native-relocate`, `strategy=rewind`, `dropped_turns=N`                                | `tests/src/cli/test_session_commands.py`    |
| Same-dir/sidecar rejected             | same-dir or sidecar fork + `rewind`        | rejected with native-relocate-only guidance                                                        | `tests/src/cli/test_session_commands.py`    |
| AI failure falls back                 | LLM error                                  | plain native-relocate + "code-delta unavailable" note; resume still works                          | `tests/src/session/test_rewind_strategy.py` |
| Truncated copy is unshared            | sibling/parent in same encoded dir         | `<R>.jsonl` deleted with the session; parent/sibling transcript untouched                          | same                                        |
| Net-change reconciliation             | file edited twice in the window            | delta shows net change, not both edits                                                             | same                                        |
| Privacy warning                       | any rewind run                             | "code/transcript sent to <model>" surfaced                                                         | same                                        |

> The "Resume tolerates fresh UUID" row is an **integration** test (real `claude --resume`), not a unit test. It extends
> the Slice-1 stem probe by adding clean-prefix truncation. Per `testing_guidelines.md`, session fork/resume changes
> require the relevant integration run before closeout, not just unit green.

## Open questions / deferred decisions

1. **Strategy value name** — `rewind` (working) vs `tail-curated` / `code-delta` / `rewind-curated`. Card leans
   `rewind`.
2. **Delta source** — tool-calls only (recommended) vs + `git diff` cross-check.
3. **N-preview UX** — a turn-boundary preview so users pick N without guessing (possible follow-up, out of scope here).
4. **N>=T UX** — reject with guidance or fall back to a transfer-style path; do not launch an empty native transcript.

## Closeout items

- [ ] All slice assertions ticked with verification recorded.
- [ ] `tests/src/session/test_rewind_strategy.py` + `tests/src/cli/test_session_fork.py` green; the real-`claude` resume
  integration test green.
- [ ] `make pre-commit` clean.
- [ ] design.md §3.9 matrix, design_appendix.md §H, cli_reference.md, end-user/transfer.md reflect shipped behavior.
- [ ] Change-log entry added (`docs/board/change_log.md`), durable lessons proposed for `impl_notes.md` review (esp. the
  `sessionId`-stem probe outcome).
- [ ] Card moved `doing/ → done/`.
