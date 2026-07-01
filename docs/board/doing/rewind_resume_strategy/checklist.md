# Checklist — Rewind Resume Strategy

Execution plan for `card.md` (this dir). Branch: `rewind-resume-strategy`. See `card.md` for motivation, the
decided design points, and risks; this file is the ordered execution plan with observable assertions.

## Current focus

**Awaiting checklist review.** Nothing implemented yet. Slice 1 is a hard gate — do not start Slices 2–6 until the
`sessionId`-match probe result and the `Derivation` shape are locked and reviewed.

## Verified code anchors (re-checked 2026-07-01, card line numbers had drifted)

These were confirmed against the current tree by read-only verification. Use these, not the card's numbers.

| Symbol / behavior | Location (verified) | Note |
| ----------------- | ------------------- | ---- |
| `ResumeStrategy` enum (`MINIMAL/STRUCTURED/FULL/AI_CURATED`) | `session/transfer.py:101-107` | canonical def; imported elsewhere |
| Strategy dispatch (structured/full/ai-curated) | `session/transfer.py:1182-1215` | no `native` branch — dispatch is transfer-only |
| `_generate_ai_curated_context` (falls back to `_generate_structured_context` on parse fail) | `session/transfer.py:944` | |
| `_call_llm_for_curation` / `_emit_curation_usage` (emit **before** parse gate) | `session/transfer.py:671-728` / `731-771`, emit at `1008-1010` | OpenRouter direct via `SyncAdapter(get_client(...))` |
| `_validate_decision_citations` (drops citations outside `emitted_turns`) | `session/transfer.py:801-826` | |
| `_format_transcript_for_llm` + `_group_entries_into_turns` (`[turn N]` anchors) | `session/transfer.py:600-652` | turns grouped by `requestId`, fallback to user-initiated sequences |
| `AI_CURATION_SYSTEM_PROMPT` (untrusted-transcript) / `AI_CURATION_USER_PROMPT_TEMPLATE` | `session/transfer.py:72-77` / `83-98` | |
| `assemble_transfer_context` (entry, returns `TransferResult`) | `session/transfer.py:1072` | |
| `Derivation` dataclass (12 fields; `strategy` default `"structured"`) | `session/models.py:441-479` | **no SCHEMA_VERSION on `Derivation`** — it lives on `SessionState` (`:21`) |
| "Null for native resumes" note | `session/models.py:457` (docstring only) | convention, **not** an enforced guard |
| `--strategy` Choice `[minimal,structured,full,ai-curated]` | `cli/session_fork.py:140` | |
| `--resume-mode` Choice `[transfer,native-relocate]` | `cli/session_fork.py:165` | |
| native-relocate preflights (4 rejections) | `cli/session_fork.py:489-556` | `--no-launch`, sidecar, parent-has-transcript, `--into` CWD-differs; worktree check is at runtime |
| strategy populated for transfer forks only | `cli/session_lifecycle.py:309` (`_persist_fork_transfer_derivation`), gated by `uses_fresh_transfer` (`:947`) | native-relocate leaves `strategy=None` **by omission** |
| native-relocate copy + derivation write; `relocated_parent_session_id = parent.claude_session_id` | `session/manager.py:1358-1390` (id at `:1376`) | |
| relocate GC / reference-count via `_find_shared_transcript_sessions` (keys on `relocated_parent_session_id`) | `session/manager.py:1812-1850` | deletes copy iff no other session references that id |
| `relocate_transcript` — **pure byte copy**, `rewrite_paths` raises `NotImplementedError` | `session/claude/relocate.py:71-171` (paths `104-108`) | never touches entries' internal `sessionId` |
| `RelocateConflictError` (dest differs, no overwrite) / `RelocateSameDirError` (src==dst dir) | `session/claude/relocate.py:34-46` | |
| Destination path `get_transcript_path(root, uuid)` → `<uuid>.jsonl` | `relocate.py:110-114`, `session/claude/paths.py:79-94` | stem == UUID today |

## Refinements from verification (feed these into the slices)

1. **The "invariant" is a convention, not a guard.** No code asserts `strategy null ⟺ native`. A manifest with
   `strategy="structured"` + `resume_mode="native"` loads without error today. Slice 1's audit is therefore about
   **read sites that *assume* the convention** (status/derivation readers, launch-path branching), plus adding the
   *write* path — not removing a guard that does not exist.
2. **No precedent for stem ≠ internal `sessionId`.** `relocate_transcript` always produces `<uuid>.jsonl` whose stem
   equals the entries' embedded `sessionId`. The fresh-UUID `R` design is the first mismatch case, so the probe
   (does `claude --resume R` tolerate stem ≠ embedded `sessionId`?) has zero in-tree precedent and must be run live.
3. **GC field decision is open.** `_find_shared_transcript_sessions` keys on `relocated_parent_session_id`. For a
   fresh `R`, either overload that field with `R` (name then lies — it is not the parent's id) or add a distinct
   `rewind_relocated_session_id` field. Decide in Slice 1; it changes the `Derivation` shape.

---

## Slice 1 — Decision + invariant + probe (GATE)

**Goal:** Lock the durable shape and the launch-combo decision, and settle the one empirical unknown, before any
plumbing. Nothing below this line proceeds until this slice is reviewed.

- [ ] **`sessionId`-match probe (empirical, blocking).** Write a truncated JSONL copy under a fresh stem `R` and run
      `claude --resume R --fork-session` against it. **Assertion:** record one of — (a) resume succeeds with stem `R` ≠
      embedded `sessionId` (no envelope rewrite needed), or (b) it fails with "No conversation found"/similar and only
      succeeds after rewriting the envelope `sessionId` to `R` while leaving signed `thinking`/`tool_result` blocks
      byte-intact and signatures revalidating. Capture the exact failure text and the working recipe in `card.md` or an
      `impl_notes` proposal. This is a `relocate.py`-style live pin — unit tests cannot answer it.
- [ ] **`Derivation` shape decision.** Decide and document: `strategy="rewind"` coexisting with
      `resume_mode="native-relocate"`; a new `dropped_turns: int | None = None`; and the GC-id field question
      (refinement #3 above — overload `relocated_parent_session_id` vs new field). **Assertion:** the chosen field set
      is written into `card.md` and reflected as `Derivation` field additions; confirm additive-optional fields load
      under the existing strict `SessionState` reader without a `SCHEMA_VERSION` bump (precedent: consumer_lanes T4
      additive-no-bump), and add a strict-read test that a `rewind` derivation round-trips.
- [ ] **Read-site audit.** Enumerate every site that reads `Derivation.strategy`/`resume_mode` and assumes
      "native ⟹ no context file" or "strategy null ⟹ native" — status renderers, `session show`, launch-path branching
      in `session_lifecycle.py`, GC. **Assertion:** produce a concrete list (file:line) of sites that must tolerate
      `native-relocate` + non-null `strategy` + non-null `context_file`, with the required change per site.
- [ ] **design.md contract update.** Update the resume-mode × strategy matrix in `docs/design.md` §3.9 to add the
      `rewind` row (native-relocate + `strategy="rewind"` + context file). **Assertion:** the matrix documents the
      shipped-or-committed shape and names the convention-not-guard status.

**Blocker/decision:** Slices 2–6 are gated on the probe result (it determines whether Slice 5 needs an envelope
rewrite) and the `Derivation` shape (it determines Slice 4's manifest writes).

## Slice 2 — Turn window + safe truncation

**Goal:** Split the parent transcript at turn `T−N` on a coherent boundary and write a truncated JSONL prefix.

- [ ] **Turn split at `T−N`.** Reuse `_group_entries_into_turns` (`transfer.py`) to define the boundary; `N` counts
      turns, not JSONL lines. **Assertion:** given a parent with `T` turns and `--drop-last N`, the writer selects
      entries belonging to turns `1..(T−N)`.
- [ ] **Safe truncation writer.** Snap the cut to the last complete turn ≤ `T−N` so no `tool_use`/`tool_result` pair is
      split. **Assertion:** a fixture with a tool-call pair straddling the cut produces a JSONL that ends on a complete
      turn (unit-assert the last entries form a closed turn; no dangling `tool_use` without its `tool_result`).
- [ ] **Degenerate cases.** `N=0` → behave as plain native-relocate (whole file, no delta). `N≥T` → minimal head +
      whole-session delta. **Assertion:** both paths are unit-tested and do not crash or corrupt resume.

## Slice 3 — Code-delta extractor + prompt

**Goal:** Produce a grounded, net-change code-delta over only the dropped window `(T−N)..T`.

- [ ] **Tool-call delta.** Extract `Edit`/`Write`/`MultiEdit`/`NotebookEdit` calls within the dropped window.
      **Assertion:** delta entries reference only turns `T−N+1..T`; no head turns cited.
- [ ] **Net-change reconciliation.** Multiple edits to one file collapse to the net delta (later supersedes earlier).
      **Assertion:** a fixture editing one file twice in the window yields one net entry, not two.
- [ ] **Prompt + grounding reuse.** Narrowed variant of `AI_CURATION_USER_PROMPT_TEMPLATE` (files changed + what/why,
      net effect, dangling edits) with the explicit "files already contain these; conversation is rewound to before
      them" framing; reuse `_validate_decision_citations`, `AI_CURATION_SYSTEM_PROMPT` (injection hardening), and the
      `_emit_curation_usage` emit-before-parse-gate. **Assertion:** ungrounded citations are dropped; a usage event is
      emitted even on an unparseable LLM response (`status="error"`).

## Slice 4 — Wire the strategy

**Goal:** Surface `--strategy rewind --drop-last N` and co-deliver a context file with a native-relocate launch.

- [ ] **`ResumeStrategy.REWIND` + Choice.** Add the enum member and the `--strategy` Choice value on fork and resume;
      add required `--drop-last N` (no default; integer). **Assertion:** `--strategy rewind` without `--drop-last`
      errors; `rewind` resolves `resume_mode=native-relocate` (worktree/`--into` only).
- [ ] **Co-deliver context file with native-relocate launch (the convention extension).** Extend the strategy-population
      path (currently `_persist_fork_transfer_derivation` gated by `uses_fresh_transfer`, `session_lifecycle.py:309/947`)
      so a rewind fork writes `strategy="rewind"`, `dropped_turns=N`, `context_file=<delta>` AND the launch emits
      `--resume --fork-session` together with `--append-system-prompt-file`. **Assertion:** the launched argv for a
      rewind worktree fork contains both flags (unit-assert on the built command).
- [ ] **Same-dir / sidecar rejection.** **Assertion:** `--strategy rewind` on a same-dir or sidecar fork is rejected
      with the existing native-relocate-only guidance (reuse the `session_fork.py:489-556` preflight messages).

## Slice 5 — Identity + cleanup

**Goal:** Fresh-UUID unshared truncated copy that GC deletes cleanly without touching parent/siblings.

- [ ] **Fresh rewind-owned UUID `R`.** Write the truncated copy as `<R>.jsonl` in the child's encoded dir; launch
      `--resume R --fork-session`. Apply the Slice-1 probe outcome (envelope `sessionId` rewrite only if required).
      **Assertion:** `R ≠ parent_uuid`; the parent's original `<parent_uuid>.jsonl` is never written or overwritten.
- [ ] **Unshared cleanup.** Record the relocated id per the Slice-1 GC-field decision so `_find_shared_transcript_sessions`
      finds no siblings sharing `R`. **Assertion:** deleting the rewind session unlinks `<R>.jsonl`; a fixture with a
      sibling/parent in the same encoded dir confirms neither is touched.

## Slice 6 — Fallback + privacy + docs

**Goal:** Degrade safely on AI failure, warn on external send, and sync all normative docs.

- [ ] **Fallback.** On code-delta LLM failure, fall back to plain native-relocate + a "code-delta unavailable" note;
      resume still works. **Assertion:** LLM-error fixture yields a working native-relocate resume with the note.
- [ ] **Privacy warning.** Surface "dropped-window code/transcript sent to `<model>`" (same posture as `ai-curated`).
      **Assertion:** the warning is emitted on any rewind run.
- [ ] **Docs.** Update `docs/design.md` §3.9 (matrix from Slice 1 finalized to shipped state), `docs/cli_reference.md`
      (fork/resume `--strategy rewind --drop-last`), and `docs/end-user/transfer.md`. **Assertion:** each doc reflects
      shipped behavior, not aspiration.

---

## Acceptance tests

| Test | Fixture | Assertion | Test File |
| ---- | ------- | --------- | --------- |
| Truncated relocate carries head | parent with T turns, `--drop-last N` | child JSONL has turns 1..T−N, none of T−N+1..T | `tests/src/session/test_rewind_strategy.py` |
| Truncation snaps to safe boundary | tool_use/result pair straddling T−N | relocated JSONL ends on a complete turn (resume not corrupted) | same |
| Delta cites only dropped turns | edits in the dropped window | delta lists changed files citing turns T−N+1..T; no head citations | same |
| Native resume + context file together | `--strategy rewind` worktree fork | launched argv carries `--resume --fork-session` AND `--append-system-prompt-file` | same |
| Resume tolerates fresh UUID | rewind launch, fresh `<R>.jsonl` | child resumes from `<R>` (sessionId rewritten iff probe requires); no "No conversation found" | integration (real `claude`) |
| Manifest records rewind | `--drop-last N` | `resume_mode=native-relocate`, `strategy=rewind`, `dropped_turns=N` | same |
| Same-dir/sidecar rejected | same-dir or sidecar fork + `rewind` | rejected with native-relocate-only guidance | `tests/src/cli/test_session_fork.py` |
| AI failure falls back | LLM error | plain native-relocate + "code-delta unavailable" note; resume still works | `tests/src/session/test_rewind_strategy.py` |
| Truncated copy is unshared | sibling/parent in same encoded dir | `<R>.jsonl` deleted with the session; parent/sibling transcript untouched | same |
| Net-change reconciliation | file edited twice in the window | delta shows net change, not both edits | same |
| Privacy warning | any rewind run | "code/transcript sent to <model>" surfaced | same |

> The "Resume tolerates fresh UUID" row is an **integration** test (real `claude --resume`), not a unit test — it is the
> executable form of the Slice-1 probe. Per `testing_guidelines.md`, session fork/resume changes require the relevant
> integration run before closeout, not just unit green.

## Open questions / deferred decisions

1. **Strategy value name** — `rewind` (working) vs `tail-curated` / `code-delta` / `rewind-curated`. Card leans `rewind`.
2. **Delta source** — tool-calls only (recommended) vs + `git diff` cross-check.
3. **GC-id field** — overload `relocated_parent_session_id` with `R` vs add `rewind_relocated_session_id` (Slice 1).
4. **N-preview UX** — a turn-boundary preview so users pick N without guessing (possible follow-up, out of scope here).

## Closeout items

- [ ] All slice assertions ticked with verification recorded.
- [ ] `tests/src/session/test_rewind_strategy.py` + `tests/src/cli/test_session_fork.py` green; the real-`claude`
      resume integration test green.
- [ ] `make pre-commit` clean.
- [ ] design.md §3.9 matrix, cli_reference.md, end-user/transfer.md reflect shipped behavior.
- [ ] Change-log entry added (`docs/board/change_log.md`), durable lessons proposed for `impl_notes.md` review
      (esp. the `sessionId`-stem probe outcome).
- [ ] Card moved `doing/ → done/`.
